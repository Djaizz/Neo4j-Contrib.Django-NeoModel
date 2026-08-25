"""Neo4j batch helpers and GraphDbConfig."""


from __future__ import annotations

from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, LiteralString, TypeVar
from urllib.parse import quote, urlparse
import logging
import os
import re
import sys
import time

from neomodel.config import get_config
from neomodel.sync_.database import db
from tqdm import tqdm

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
    'connect_graph_db',
    'set_label_install_callback',
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
    runner = _label_install_callback
    if _label_install_precheck_enabled():
        runner = _with_install_precheck(runner)
    if _quiet_neo4j_install_enabled():
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            runner()
    else:
        runner()


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


def _label_install_precheck_enabled() -> bool:
    """Whether to skip ``install_all_labels`` when the schema is already complete."""
    return os.environ.get('AGENT_NEO_LABEL_INSTALL_PRECHECK', '1').lower() not in (
        '0',
        'false',
        'no',
        'off',
    )


def _structured_node_subclasses(cls: Any) -> list[Any]:
    """All subclasses of ``cls``, transitively.

    Deliberately the same recursion ``Database.install_all_labels`` uses to decide
    what to install, duplicates and all — the point of this pre-check is to derive
    exactly the set of schema objects that call would create, so any divergence in
    discovery would be a divergence in the answer. Names are deduplicated by the
    sets they land in.
    """
    subclasses: list[Any] = cls.__subclasses__()
    if not subclasses:
        return []
    return subclasses + [
        grandchild
        for subclass in cls.__subclasses__()
        for grandchild in _structured_node_subclasses(subclass)
    ]


def _expected_schema_object_names() -> tuple[frozenset[str], frozenset[str]] | None:
    """Return ``(index names, constraint names)`` ``install_all_labels`` would create.

    Mirrors ``Database.install_labels`` / ``_install_node`` / ``_install_relationship``
    and the six emitters' own name formats: ``index_{label}_{prop}``,
    ``fulltext_index_{label}_{prop}``, ``vector_index_{label}_{prop}``,
    ``constraint_unique_{label}_{prop}``, and the relationship-type variants of all
    four (which substitute the relationship type for the label). ``index`` and
    ``unique_index`` are ``elif``-exclusive there, so they are here too.

    Returns ``None`` when the set cannot be derived — an unexpected model shape, a
    missing ``definition`` key, anything. ``None`` means "fall through to the full
    install": the caller must never read an underivable set as an empty one, because
    an empty expected set is a subset of everything.

    Version-gated objects (fulltext, vector, relationship constraints) are listed
    unconditionally. If the server is too old to hold one, it will be absent, the
    subset test will fail, and the full install runs — which is exactly what happens
    today, ``FeatureNotSupported`` and all. Suppressing that error by skipping the
    install would be a behaviour change hiding behind a performance one.
    """
    try:
        from neomodel.sync_.node import StructuredNode

        index_names: set[str] = set()
        constraint_names: set[str] = set()

        for cls in _structured_node_subclasses(StructuredNode):
            if not hasattr(cls, '__label__'):
                continue  # abstract; install_labels returns early for these too
            label = cls.__label__

            for property_name, property_definition in cls.defined_properties(
                aliases=False, rels=False
            ).items():
                _collect_property_schema_names(
                    owner=label,
                    property_name=property_name,
                    property_definition=property_definition,
                    index_names=index_names,
                    constraint_names=constraint_names,
                )

            for relationship in cls.defined_properties(
                aliases=False, rels=True, properties=False
            ).values():
                relationship_cls = relationship.definition['model']
                if relationship_cls is None:
                    continue
                relationship_type = relationship.definition['relation_type']
                relationship_properties = relationship_cls.defined_properties(
                    aliases=False, rels=False
                )
                for property_name, property_definition in relationship_properties.items():
                    _collect_property_schema_names(
                        owner=relationship_type,
                        property_name=property_name,
                        property_definition=property_definition,
                        index_names=index_names,
                        constraint_names=constraint_names,
                    )
    except Exception:
        log.warning(
            'label install pre-check: could not derive the expected schema object '
            'names; running the full install',
            exc_info=True,
        )
        return None

    return frozenset(index_names), frozenset(constraint_names)


def _collect_property_schema_names(
    *,
    owner: str,
    property_name: str,
    property_definition: Any,
    index_names: set[str],
    constraint_names: set[str],
) -> None:
    """Add the schema object names one property contributes, for a label or rel type.

    ``owner`` is the node label or the relationship type; the emitters interpolate
    it into otherwise identical name formats, which is why one function covers both.
    """
    db_property = property_definition.get_db_property_name(property_name)
    if property_definition.index:
        index_names.add(f'index_{owner}_{db_property}')
    elif property_definition.unique_index:
        constraint_names.add(f'constraint_unique_{owner}_{db_property}')
    if property_definition.fulltext_index:
        index_names.add(f'fulltext_index_{owner}_{db_property}')
    if property_definition.vector_index:
        index_names.add(f'vector_index_{owner}_{db_property}')


def _observed_schema_object_names() -> tuple[frozenset[str], frozenset[str]] | None:
    """Return ``(index names, constraint names)`` the database already holds.

    Two statements — one ``SHOW INDEXES``, one ``SHOW CONSTRAINTS`` — via the
    driver's own public listing helpers. ``None`` on any failure, meaning "fall
    through to the full install".
    """
    try:
        index_names = frozenset(
            str(entry['name']) for entry in db.list_indexes() if entry.get('name')
        )
        constraint_names = frozenset(
            str(entry['name']) for entry in db.list_constraints() if entry.get('name')
        )
    except Exception:
        log.warning(
            'label install pre-check: SHOW INDEXES / SHOW CONSTRAINTS failed; '
            'running the full install',
            exc_info=True,
        )
        return None
    return index_names, constraint_names


def _schema_is_already_complete() -> bool:
    """Whether every schema object ``install_all_labels`` would create already exists.

    Gates on ``expected ⊆ observed`` and nothing else. A database carrying *extra*
    indexes still skips — they are not this code's business, and ``install_all_labels``
    would not have removed them. Anything that leaves the answer in doubt returns
    ``False``, because the acceptable failure here is "slow", never "missing index".

    Presence is checked by name, which is what ``install_all_labels`` can achieve:
    ``CREATE INDEX`` on an existing name is caught and swallowed as
    ``INDEX_ALREADY_EXISTS``, so a POPULATING or FAILED index is no more repaired by
    running the install than by skipping it.
    """
    expected = _expected_schema_object_names()
    if expected is None:
        return False
    expected_index_names, expected_constraint_names = expected
    if not expected_index_names and not expected_constraint_names:
        # No models registered, or none carrying an index — there is nothing to
        # gate on, and the empty set is a subset of everything. Install.
        log.info(
            'label install pre-check: no expected schema objects derived; '
            'running the full install'
        )
        return False

    observed = _observed_schema_object_names()
    if observed is None:
        return False
    observed_index_names, observed_constraint_names = observed

    missing_index_names = expected_index_names - observed_index_names
    missing_constraint_names = expected_constraint_names - observed_constraint_names
    if missing_index_names or missing_constraint_names:
        log.info(
            'label install pre-check: %s of %s indexes and %s of %s constraints are '
            'missing (e.g. %s); running the full install',
            len(missing_index_names),
            len(expected_index_names),
            len(missing_constraint_names),
            len(expected_constraint_names),
            sorted(missing_index_names | missing_constraint_names)[:5],
        )
        return False

    log.info(
        'label install pre-check: all %s expected indexes and %s expected constraints '
        'are present; skipping the full install',
        len(expected_index_names),
        len(expected_constraint_names),
    )
    return True


def _with_install_precheck(callback: Callable[[], None]) -> Callable[[], None]:
    """Wrap ``callback`` so its ``install_all_labels()`` becomes a no-op when complete.

    The check has to run *after* the callback's own side-effect imports, not before
    it: those imports are what register the ``StructuredNode`` subclasses the
    expected-name derivation reads. Deriving first would silently gate on whatever
    subset of the model tree happened to be imported already, and a subset of the
    expectations is a subset of the observations — the one failure mode this
    pre-check may not have. So the gate is installed on the ``install_all_labels``
    call itself, which the callback reaches only once its models are registered.

    A callback that installs some other way is simply not gated, and pays the full
    cost as before.
    """
    def _run() -> None:
        real_install_all_labels = db.install_all_labels
        had_own_attribute = 'install_all_labels' in vars(db)

        def _gated_install_all_labels(*args: Any, **kwargs: Any) -> None:
            if _schema_is_already_complete():
                return
            real_install_all_labels(*args, **kwargs)

        db.install_all_labels = _gated_install_all_labels  # type: ignore[method-assign]
        try:
            callback()
        finally:
            if had_own_attribute:
                db.install_all_labels = real_install_all_labels  # type: ignore[assignment]
            else:
                del db.install_all_labels  # type: ignore[attr-defined]

    return _run


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
    max_attempts: int | None = None,
    retry_delay_seconds: float | None = None,
    backoff_multiplier: float | None = None,
    max_retry_delay_seconds: float | None = None,
) -> _T:
    """Run ``operation`` with retries when the Neo4j cluster is switching leaders.

    The four tuning knobs default to ``None`` and are resolved from the
    ``NEO4J_CLUSTER_LEADER_SWITCH_*`` module globals **inside the body**, at call
    time. This is a correctness requirement, not a performance one: binding them as
    parameter defaults reads the globals once, at ``def`` time, so a consumer that
    tunes retries by assigning to those globals — which is the documented way to
    tune them — changed nothing the retry loop read, while ``connect_db`` printed
    the assigned values. The log claimed a tuning that was not in effect.

    An explicit argument still wins over the global, so every existing call site
    behaves exactly as before.
    """
    resolved_max_attempts: int = (
        NEO4J_CLUSTER_LEADER_SWITCH_MAX_ATTEMPTS
        if max_attempts is None
        else max_attempts
    )
    resolved_retry_delay_seconds: float = (
        NEO4J_CLUSTER_LEADER_SWITCH_RETRY_DELAY_SECONDS
        if retry_delay_seconds is None
        else retry_delay_seconds
    )
    resolved_backoff_multiplier: float = (
        NEO4J_CLUSTER_LEADER_SWITCH_BACKOFF_MULTIPLIER
        if backoff_multiplier is None
        else backoff_multiplier
    )
    resolved_max_retry_delay_seconds: float = (
        NEO4J_CLUSTER_LEADER_SWITCH_MAX_RETRY_DELAY_SECONDS
        if max_retry_delay_seconds is None
        else max_retry_delay_seconds
    )

    last_error: BaseException | None = None
    for attempt_index in range(1, resolved_max_attempts + 1):
        try:
            return operation()
        except BaseException as exc:
            last_error = exc
            if attempt_index >= resolved_max_attempts:
                raise
            if not is_transient_neo4j_error(exc):
                raise
            delay_seconds = _retry_delay_for_attempt(
                attempt_index,
                base_delay_seconds=resolved_retry_delay_seconds,
                backoff_multiplier=resolved_backoff_multiplier,
                max_retry_delay_seconds=resolved_max_retry_delay_seconds,
            )
            log.warning(
                '%s: transient Neo4j error on attempt %s/%s (%s); '
                'waiting %ss before reconnect and retry',
                description,
                attempt_index,
                resolved_max_attempts,
                exc,
                delay_seconds,
            )
            print(
                f'[neo4j] {description}: cluster leader unavailable ({exc}); '
                f'waiting {delay_seconds:.0f}s before retry '
                f'({attempt_index}/{resolved_max_attempts - 1} retries used, '
                f'{resolved_max_attempts - attempt_index} attempt(s) left)...',
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


def _split_row_by_item_budget(
    row: dict[str, Any],
    *,
    count_key: str,
    batch_size: int,
) -> list[dict[str, Any]]:
    """Split one row into sub-rows whose ``count_key`` lists each fit ``batch_size``.

    Every other key is copied verbatim onto each sub-row, so the sub-rows are the
    same statement applied to slices of one subject's item list. Only correct for
    an **idempotent** payload — an additive `MERGE`, or a `DELETE` of named
    targets — where processing a subset and then the rest reaches the same end
    state as processing the whole. A replace-all write must never be split: its
    delete-then-rebuild is atomic per row, and a second sub-row would delete what
    the first one wrote.
    """
    items: list[Any] = list(row[count_key])
    if len(items) <= batch_size:
        return [row]
    return [
        {**row, count_key: items[start:start + batch_size]}
        for start in range(0, len(items), batch_size)
    ]


def _reject_row_split_without_count_key(
    *,
    count_key: str | None,
    allow_row_split: bool,
) -> None:
    """Refuse ``allow_row_split=True`` with ``count_key=None``, loudly.

    With no ``count_key`` a row carries no item list, so there is nothing to
    divide: an over-budget row would ship whole. That is precisely the unbounded
    statement this chunker exists to prevent, and honouring the flag by silently
    not splitting would ship it under a name that says it cannot happen.
    """
    if allow_row_split and count_key is None:
        raise ValueError(
            'allow_row_split=True requires a count_key. With count_key=None each '
            'row counts as exactly one item, so there is no item list to divide '
            'and an over-budget row would be shipped whole — the unbounded '
            'statement this chunker exists to prevent.'
        )


def _chunk_rows_by_item_budget(
    cleaned_rows: list[dict[str, Any]],
    *,
    count_key: str | None,
    batch_size: int,
    allow_row_split: bool = False,
) -> list[list[dict[str, Any]]]:
    """Group rows into chunks bounded by **both** item count and row count.

    Two budgets, because either alone leaves an unbounded statement:

    * **Items** — the individual nodes or relationships written. This is the unit
      that matters, and summing ``len(row[count_key])`` is what bounds it.
    * **Rows** — the subjects. A row whose item list is empty contributes zero
      items yet still costs a ``MATCH``, so an item-only budget lets an unbounded
      number of empty rows land in one statement. An empty item list is a
      legitimate payload (it is how "this subject now has none" is expressed), so
      the row budget is what keeps that case bounded.

    ``count_key=None`` is the **flat-row** case: the row *is* the item, so it
    counts as one. The two budgets then reduce to the same predicate and the
    result is chunks of exactly ``batch_size`` rows — identical to slicing the
    list, which is what a hand-rolled chunk loop does. It is spelled as a
    ``count_key`` value rather than a separate function so a flat-row caller gets
    the retry wrapper and the results accumulation for free.

    With ``allow_row_split``, a single row carrying more than ``batch_size`` items
    is divided rather than shipped whole; see :func:`_split_row_by_item_budget`
    for when that is sound. Without it, such a row is emitted as its own chunk and
    is deliberately over budget — the caller has asked for row atomicity, and
    silently splitting would break the semantics it asked for.
    """
    _reject_row_split_without_count_key(
        count_key=count_key, allow_row_split=allow_row_split,
    )

    rows: list[dict[str, Any]] = []
    for row in cleaned_rows:
        if allow_row_split:
            # count_key is not None here: _reject_row_split_without_count_key said so.
            rows.extend(
                _split_row_by_item_budget(
                    row, count_key=str(count_key), batch_size=batch_size,
                )
            )
        else:
            rows.append(row)

    chunks: list[list[dict[str, Any]]] = []
    current_chunk: list[dict[str, Any]] = []
    current_item_count = 0
    for row in rows:
        row_item_count = 1 if count_key is None else len(row[count_key])
        would_exceed_items = current_item_count + row_item_count > batch_size
        would_exceed_rows = len(current_chunk) + 1 > batch_size
        if (would_exceed_items or would_exceed_rows) and current_chunk:
            chunks.append(current_chunk)
            current_chunk = [row]
            current_item_count = row_item_count
        else:
            current_chunk.append(row)
            current_item_count += row_item_count
    if current_chunk:
        chunks.append(current_chunk)
    return chunks


def batched_cypher_execute(
    cleaned_rows: list[dict[str, Any]],
    query: str,
    *,
    count_key: str | None = None,
    verb: str = "Processing",
    label: str = "relationships",
    timer_enabled: bool = False,
    batch_size: int = GRAPH_DB_BATCH_SIZE,
    allow_row_split: bool = False,
    retry_tuning: dict[str, Any] | None = None,
) -> list[list[Any]]:
    """Execute one ``UNWIND $rows`` statement per bounded chunk of ``cleaned_rows``.

    Args:
        cleaned_rows: UNWIND rows, already validated by the caller. A row whose
            ``count_key`` list is empty is passed through, not skipped — for a
            replace-all statement that row is the request to clear.
        query: Cypher taking a ``$rows`` parameter.
        count_key: The row key whose list length counts as that row's item total.
            ``None`` for a **flat** payload, where one row is one node or one
            relationship: each row then counts as one item, the item and row
            budgets coincide, and the chunks are exactly ``batch_size`` rows —
            the same division a hand-rolled slice loop produces.
        verb: Progress/log verb, e.g. ``"Adding"``.
        label: Progress/log noun, e.g. ``"Asset-to-Point"``.
        timer_enabled: Log start/elapsed for the whole call.
        batch_size: Per-chunk budget, applied to items **and** rows.
        allow_row_split: Divide a single over-budget row instead of shipping it
            whole. Sound only for idempotent payloads — see
            :func:`_split_row_by_item_budget`. Raises with ``count_key=None``,
            which has no item list to divide.
        retry_tuning: Keyword arguments forwarded to
            :func:`retry_neo4j_cluster_operation` (``max_attempts``,
            ``retry_delay_seconds``, ``backoff_multiplier``,
            ``max_retry_delay_seconds``). Omitting it uses that function's own
            defaults, which it resolves from its module globals at call time — so
            a caller that tunes retries by assigning to those globals no longer
            needs to pass them here.

    Returns:
        The result rows of every chunk, concatenated in execution order. Empty
        when there was nothing to execute. Returning them is what lets a caller
        confirm a write by what the graph reported rather than by the payload it
        submitted; a statement with no ``RETURN`` simply contributes nothing.
    """
    # Ahead of the empty-payload exit, so the contract violation is reported for
    # any payload rather than only for a non-empty one.
    _reject_row_split_without_count_key(
        count_key=count_key, allow_row_split=allow_row_split,
    )
    if not cleaned_rows:
        return []
    batch_description = f'{verb} {label}'
    forwarded_retry_tuning: dict[str, Any] = dict(retry_tuning or {})
    results: list[list[Any]] = []

    def _execute_cypher(rows: list[dict[str, Any]]) -> None:
        chunk_results, _meta = retry_neo4j_cluster_operation(
            lambda: db.cypher_query(query, {'rows': rows}),
            description=batch_description,
            reconnect=reconnect_neo4j_driver,
            **forwarded_retry_tuning,
        )
        if chunk_results:
            results.extend(chunk_results)

    batch_chunks = _chunk_rows_by_item_budget(
        cleaned_rows,
        count_key=count_key,
        batch_size=batch_size,
        allow_row_split=allow_row_split,
    )

    if len(batch_chunks) <= 1:
        if timer_enabled:
            log.info("graph_db.batch.start %s %s batched=False", verb, label)
            start_time: float = time.time()
        # Exactly one chunk: ``cleaned_rows`` is non-empty by the guard above, and a
        # non-empty input always produces at least one chunk, so there is no
        # zero-chunk case to fall back to.
        _execute_cypher(batch_chunks[0])
        if timer_enabled:
            elapsed_time: float = time.time() - start_time
            log.info("graph_db.batch.done %s elapsed=%s", label, elapsed_time)
    else:
        if timer_enabled:
            log.info("graph_db.batch.start %s %s batched=True", verb, label)
        for chunk in tqdm(batch_chunks, desc=f"{verb} {label}", unit="batch"):
            _execute_cypher(chunk)

    return results


def connect_graph_db(graph_db_config: GraphDbConfig, *, install_labels_and_indexes: bool = False) -> None:
    graph_db_config.connect_db(install_labels_and_indexes=install_labels_and_indexes)
