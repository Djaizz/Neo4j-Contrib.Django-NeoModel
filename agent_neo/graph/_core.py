"""Neo4j batch helpers and GraphDbConfig."""


from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
import re
from typing import Any, LiteralString, TypeVar
from urllib.parse import quote, urlparse

from tqdm import tqdm

from neomodel.config import get_config
from neomodel.sync_.database import db

from agent_neo.util.env import resolve_env_placeholder


__all__: tuple[LiteralString, ...] = (
    'GRAPH_DB_BATCH_SIZE',
    'NEO4J_CLUSTER_LEADER_SWITCH_MAX_ATTEMPTS',
    'NEO4J_CLUSTER_LEADER_SWITCH_BACKOFF_MULTIPLIER',
    'NEO4J_CLUSTER_LEADER_SWITCH_RETRY_DELAY_SECONDS',
    'NEO4J_CLUSTER_LEADER_SWITCH_MAX_RETRY_DELAY_SECONDS',
    'batched_cypher_execute',
    'GraphDbConfig',
    'GraphDbQueryAndReturnHeaderList',
    'is_graph_db_connected',
    'is_transient_neo4j_error',
    'load_query',
    'reconnect_graph_db_if_needed',
    'reconnect_neo4j_driver',
    'retry_neo4j_cluster_operation',
)


GRAPH_DB_BATCH_SIZE: int = 10**4
NEO4J_CLUSTER_LEADER_SWITCH_MAX_ATTEMPTS: int = int(
    os.environ.get('AGENT_NEO_NEO4J_CLUSTER_LEADER_SWITCH_MAX_ATTEMPTS', '5')
)
NEO4J_CLUSTER_LEADER_SWITCH_RETRY_DELAY_SECONDS: float = float(
    os.environ.get('AGENT_NEO_NEO4J_CLUSTER_LEADER_SWITCH_RETRY_DELAY_SECONDS', '30.0')
)
NEO4J_CLUSTER_LEADER_SWITCH_BACKOFF_MULTIPLIER: float = float(
    os.environ.get('AGENT_NEO_NEO4J_CLUSTER_LEADER_SWITCH_BACKOFF_MULTIPLIER', '2.0')
)
NEO4J_CLUSTER_LEADER_SWITCH_MAX_RETRY_DELAY_SECONDS: float = float(
    os.environ.get('AGENT_NEO_NEO4J_CLUSTER_LEADER_SWITCH_MAX_RETRY_DELAY_SECONDS', '120.0')
)

_active_database_url: str | None = None
_labels_installed_for_url: str | None = None

_label_install_callback: Callable[[], None] | None = None


def set_label_install_callback(callback: Callable[[], None] | None) -> None:
    """Register callback invoked when ``connect_db(install_labels_and_indexes=True)`` runs."""
    global _label_install_callback
    _label_install_callback = callback


def _install_labels() -> None:
    if _label_install_callback is None:
        return
    if _quiet_neo4j_install_enabled():
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            _label_install_callback()
    else:
        _label_install_callback()


def reconnect_neo4j_driver() -> None:
    """Drop the active Bolt driver so the next operation opens a fresh routing view."""
    global _active_database_url
    _active_database_url = None
    db.close_connection()


def is_graph_db_connected(*, expected_database_url: str | None = None) -> bool:
    """Return whether the process-global NeoModel driver is alive for ``expected_database_url``."""
    global _active_database_url
    if _active_database_url is None:
        return False
    if expected_database_url is not None and _active_database_url != expected_database_url:
        return False
    try:
        db.cypher_query('RETURN 1 AS ok')
    except Exception:
        _active_database_url = None
        return False
    return True


def reconnect_graph_db_if_needed(graph_db_config: GraphDbConfig) -> None:
    """Ensure the process-global NeoModel driver is connected for ``graph_db_config``."""
    graph_db_config.connect_db()


def _quiet_neo4j_install_enabled() -> bool:
    """Suppress neomodel ``install_all_labels`` chatter (populate sets this by default)."""
    return os.environ.get('AGENT_NEO_QUIET_NEO4J_INSTALL', '1').lower() not in (
        '0',
        'false',
        'no',
        'off',
    )


_T = TypeVar('_T')

_TRANSIENT_NEO4J_MESSAGE_MARKERS: tuple[str, ...] = (
    'not the leader',
    'no leader found',
    'no longer the leader',
    'leader election',
    'leader switch',
    'replicationfailure',
    'failed to obtain connection',
    'service unavailable',
    'connection reset',
    'connection refused',
    'broken pipe',
    'failed to establish connection',
    'database unavailable',
    'session expired',
    'defunct connection',
    'unable to retrieve routing',
    'routing table',
    'cluster member',
)


log = logging.getLogger(__name__)


def _retry_delay_for_attempt(
    attempt_index: int,
    *,
    base_delay_seconds: float,
    backoff_multiplier: float,
    max_retry_delay_seconds: float,
) -> float:
    """Return the bounded delay before retrying a transient Neo4j operation."""
    if attempt_index <= 1:
        return base_delay_seconds
    grown_delay = base_delay_seconds * (backoff_multiplier ** (attempt_index - 1))
    return min(grown_delay, max_retry_delay_seconds)


def is_transient_neo4j_error(exc: BaseException) -> bool:
    """Return whether ``exc`` likely reflects a transient Neo4j cluster/leader issue."""
    try:
        from neo4j.exceptions import (  # noqa: PLC0415
            DatabaseUnavailable,
            ServiceUnavailable,
            SessionExpired,
            TransientError,
        )
    except ImportError:
        transient_exception_types: tuple[type[BaseException], ...] = ()
    else:
        transient_exception_types = (
            ServiceUnavailable,
            SessionExpired,
            TransientError,
            DatabaseUnavailable,
        )

    if isinstance(exc, transient_exception_types):
        return True
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True

    message = str(exc).lower()
    return any(marker in message for marker in _TRANSIENT_NEO4J_MESSAGE_MARKERS)


def retry_neo4j_cluster_operation(
    operation: Callable[[], _T],
    *,
    description: str,
    reconnect: Callable[[], None] | None = None,
    max_attempts: int = NEO4J_CLUSTER_LEADER_SWITCH_MAX_ATTEMPTS,
    retry_delay_seconds: float = NEO4J_CLUSTER_LEADER_SWITCH_RETRY_DELAY_SECONDS,
    backoff_multiplier: float = NEO4J_CLUSTER_LEADER_SWITCH_BACKOFF_MULTIPLIER,
    max_retry_delay_seconds: float = NEO4J_CLUSTER_LEADER_SWITCH_MAX_RETRY_DELAY_SECONDS,
) -> _T:
    """Run ``operation`` with retries when the Neo4j cluster is switching leaders."""
    last_error: BaseException | None = None
    for attempt_index in range(1, max_attempts + 1):
        try:
            return operation()
        except BaseException as exc:
            last_error = exc
            if attempt_index >= max_attempts or not is_transient_neo4j_error(exc):
                raise
            delay_seconds = _retry_delay_for_attempt(
                attempt_index,
                base_delay_seconds=retry_delay_seconds,
                backoff_multiplier=backoff_multiplier,
                max_retry_delay_seconds=max_retry_delay_seconds,
            )
            log.warning(
                '%s: transient Neo4j error on attempt %s/%s (%s); '
                'waiting %ss before reconnect and retry',
                description,
                attempt_index,
                max_attempts,
                exc,
                delay_seconds,
            )
            print(
                f'[neo4j] {description}: cluster leader unavailable ({exc}); '
                f'waiting {delay_seconds:.0f}s before retry '
                f'({attempt_index}/{max_attempts - 1} retries used, '
                f'{max_attempts - attempt_index} attempt(s) left)...',
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay_seconds)
            if reconnect is not None:
                reconnect()
    raise RuntimeError(f'{description}: retry loop exited without result') from last_error


@dataclass
class GraphDbConfig:
    """Graph database connection configuration."""
    uri: str
    username: str
    password: str
    database: str

    @staticmethod
    def _resolve_env_placeholder(value: str) -> str:
        return resolve_env_placeholder(value)

    def get_resolved_uri(self) -> str:
        return self._resolve_env_placeholder(self.uri)

    def get_resolved_username(self) -> str:
        return self._resolve_env_placeholder(self.username)

    def get_resolved_password(self) -> str:
        return self._resolve_env_placeholder(self.password)

    def get_resolved_database(self) -> str:
        return self._resolve_env_placeholder(self.database)

    def build_neomodel_database_url(self) -> str:
        """Bolt URL for django-neomodel / neomodel.config (matches ``connect_db``)."""
        uri = self.get_resolved_uri()
        username = self.get_resolved_username()
        password = self.get_resolved_password()
        database = self.get_resolved_database()
        if not uri:
            raise RuntimeError(f"URI not resolved - check environment variable: {self.uri}")
        if not username:
            raise RuntimeError(f"Username not resolved - check environment variable: {self.username}")
        if not database:
            raise RuntimeError(f"Database not resolved - check environment variable: {self.database}")

        parsed_uri = urlparse(uri)
        protocol = parsed_uri.scheme
        host = parsed_uri.hostname or 'localhost'
        port = parsed_uri.port or 7687
        encoded_username = quote(username, safe="")
        encoded_password = quote(password, safe="")
        return f"{protocol}://{encoded_username}:{encoded_password}@{host}:{port}/{database}"

    def connect_db(self, *, install_labels_and_indexes: bool = False) -> None:
        """Open Bolt and optionally install NeoModel labels/indexes via registered callback.

        Idempotent within a process: if the driver is already connected to the same
        database URL and responds to a health check, this returns without reconnecting.
        When ``install_labels_and_indexes=True`` and labels have not yet been installed
        for this URL in the current process, ``install_all_labels`` runs once.

        Retries up to ``NEO4J_CLUSTER_LEADER_SWITCH_MAX_ATTEMPTS`` (default 3) with
        ``NEO4J_CLUSTER_LEADER_SWITCH_RETRY_DELAY_SECONDS`` (default 60s) between attempts
        when the cluster is electing a leader or otherwise transiently unavailable.
        """
        global _active_database_url, _labels_installed_for_url

        uri = self.get_resolved_uri()
        username = self.get_resolved_username()
        password = self.get_resolved_password()
        database = self.get_resolved_database()
        if not uri:
            raise RuntimeError(f"URI not resolved - check environment variable: {self.uri}")
        if not username:
            raise RuntimeError(f"Username not resolved - check environment variable: {self.username}")
        if not database:
            raise RuntimeError(f"Database not resolved - check environment variable: {self.database}")

        database_url = self.build_neomodel_database_url()

        if is_graph_db_connected(expected_database_url=database_url):
            if install_labels_and_indexes and _labels_installed_for_url != database_url:
                _install_labels()
                _labels_installed_for_url = database_url
            return

        connect_target = (
            'Bolt + label/index install'
            if install_labels_and_indexes
            else 'Bolt'
        )
        print(
            f'[neo4j] connecting ({connect_target}); '
            f'will retry up to {NEO4J_CLUSTER_LEADER_SWITCH_MAX_ATTEMPTS} times '
            f'starting at {NEO4J_CLUSTER_LEADER_SWITCH_RETRY_DELAY_SECONDS:.0f}s '
            f'and backing off to {NEO4J_CLUSTER_LEADER_SWITCH_MAX_RETRY_DELAY_SECONDS:.0f}s '
            f'on leader election',
            file=sys.stderr,
            flush=True,
        )

        def _open_bolt_connection() -> None:
            db.close_connection()
            config = get_config()
            config.database_url = database_url
            db.set_connection(url=database_url)
            if install_labels_and_indexes:
                _install_labels()

        retry_neo4j_cluster_operation(
            _open_bolt_connection,
            description='connect_db',
            reconnect=reconnect_neo4j_driver,
        )
        _active_database_url = database_url
        if install_labels_and_indexes:
            _labels_installed_for_url = database_url
        print('[neo4j] connected', file=sys.stderr, flush=True)


@dataclass
class GraphDbQueryAndReturnHeaderList:
    query: str
    return_headers: list[str]

    def get_column_index(self, column_name: str) -> int:
        try:
            return self.return_headers.index(column_name)
        except ValueError as exc:
            raise ValueError(
                f"Column '{column_name}' not found in RETURN statement. "
                f"Available columns: {self.return_headers}"
            ) from exc


def load_query(cypher_file_path: Path) -> GraphDbQueryAndReturnHeaderList:
    query_text = cypher_file_path.read_text(encoding='utf-8').strip()
    return_headers = _parse_return_headers(query_text)
    return GraphDbQueryAndReturnHeaderList(query=query_text, return_headers=return_headers)


def _parse_return_headers(query_text: str) -> list[str]:
    return_matches = list(re.finditer(r'\bRETURN\b', query_text, re.IGNORECASE))
    if not return_matches:
        raise ValueError(
            "RETURN statement not found in query. "
            "This query may not be a SELECT-style query (e.g., CREATE, MERGE, DELETE)."
        )
    return_match = return_matches[-1]
    return_start = return_match.end()
    return_section = query_text[return_start:]
    order_by_match = re.search(r'\bORDER\s+BY\b', return_section, re.IGNORECASE)
    limit_match = re.search(r'\bLIMIT\b', return_section, re.IGNORECASE)
    end_positions = []
    if order_by_match:
        end_positions.append(order_by_match.start())
    if limit_match:
        end_positions.append(limit_match.start())
    if end_positions:
        return_section = return_section[:min(end_positions)]
    return_section = return_section.strip().rstrip(';')
    return_section = re.sub(r'/\*.*?\*/', '', return_section, flags=re.DOTALL)
    lines = return_section.split('\n')
    cleaned_lines = []
    for line in lines:
        if '//' in line:
            line = line[:line.index('//')]
        cleaned_lines.append(line)
    return_section = '\n'.join(cleaned_lines)
    columns = []
    current_column = []
    paren_depth = 0
    for char in return_section:
        if char == '(':
            paren_depth += 1
            current_column.append(char)
        elif char == ')':
            paren_depth -= 1
            current_column.append(char)
        elif char == ',' and paren_depth == 0:
            column_str = ''.join(current_column).strip()
            if column_str:
                columns.append(column_str)
            current_column = []
        else:
            current_column.append(char)
    if current_column:
        column_str = ''.join(current_column).strip()
        if column_str:
            columns.append(column_str)
    column_names = []
    for column in columns:
        if not column:
            continue
        as_match = re.search(r'\bAS\s+([a-zA-Z_][a-zA-Z0-9_]*)', column, re.IGNORECASE)
        if as_match:
            column_name = as_match.group(1)
        else:
            column = column.strip()
            if '.' in column:
                parts = column.rsplit('.', 1)
                if len(parts) == 2:
                    after_dot = parts[1].strip()
                    if '(' in after_dot:
                        func_match = re.match(r'([a-zA-Z_][a-zA-Z0-9_]*)', after_dot)
                        if func_match:
                            column_name = func_match.group(1)
                        else:
                            column_name = after_dot.split('(')[0].strip()
                    else:
                        column_name = after_dot.split()[0]
                else:
                    column_name = column.split()[0]
            else:
                identifier_match = re.match(r'([a-zA-Z_][a-zA-Z0-9_]*)', column)
                if identifier_match:
                    column_name = identifier_match.group(1)
                else:
                    column_name = column.split()[0] if column.split() else column
        column_name = column_name.split('(')[0].split()[0].strip()
        if column_name:
            column_names.append(column_name)
    if not column_names:
        raise ValueError(
            "Could not parse any columns from RETURN statement. "
            f"RETURN section: {return_section[:200]}..."
        )
    return column_names


def batched_cypher_execute(
    cleaned_rows: list[dict[str, Any]],
    query: str,
    *,
    count_key: str,
    verb: str = "Processing",
    label: str = "relationships",
    timer_enabled: bool = False,
) -> None:
    if not cleaned_rows:
        return
    total = sum(len(row[count_key]) for row in cleaned_rows)
    batch_description = f'{verb} {label}'

    def _execute_cypher(rows: list[dict[str, Any]]) -> None:
        retry_neo4j_cluster_operation(
            lambda: db.cypher_query(query, {'rows': rows}),
            description=batch_description,
            reconnect=reconnect_neo4j_driver,
        )

    if total <= GRAPH_DB_BATCH_SIZE:
        if timer_enabled:
            log.info("graph_db.batch.start %s %s batched=False", verb, label)
            start_time: float = time.time()
        _execute_cypher(cleaned_rows)
        if timer_enabled:
            elapsed_time: float = time.time() - start_time
            log.info("graph_db.batch.done %s elapsed=%s", label, elapsed_time)
    else:
        if timer_enabled:
            log.info("graph_db.batch.start %s %s batched=True", verb, label)
        batch_chunks: list[list[dict[str, Any]]] = []
        current_chunk: list[dict[str, Any]] = []
        current_chunk_count = 0
        for row in cleaned_rows:
            row_count = len(row[count_key])
            if current_chunk_count + row_count > GRAPH_DB_BATCH_SIZE and current_chunk:
                batch_chunks.append(current_chunk)
                current_chunk = [row]
                current_chunk_count = row_count
            else:
                current_chunk.append(row)
                current_chunk_count += row_count
        if current_chunk:
            batch_chunks.append(current_chunk)
        for chunk in tqdm(batch_chunks, desc=f"{verb} {label}", unit="batch"):
            _execute_cypher(chunk)


def connect_graph_db(graph_db_config: GraphDbConfig, *, install_labels_and_indexes: bool = False) -> None:
    graph_db_config.connect_db(install_labels_and_indexes=install_labels_and_indexes)
