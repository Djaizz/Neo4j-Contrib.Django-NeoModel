"""Label-agnostic Neo4j bulk helpers for period rollup and hourly summary cache nodes."""


from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, LiteralString
import json
import logging

from agent_neo.graph_db.execute import DEFAULT_IN_CHUNK_SIZE, cypher_read, cypher_write, for_each_chunk
from agent_neo.graph_db.query_bind import bind_label, bind_where_clause


__all__: tuple[LiteralString, ...] = (
    'fetch_cache_keys_by_indexed_filters_cypher',
    'fetch_hvac_hourly_summaries_by_cache_keys_cypher',
    'fetch_period_rollup_cache_keys_by_spine_window_cypher',
    'fetch_period_rollup_rows_by_cache_keys_cypher',
    'hourly_summary_maps_from_cypher_rows',
    'merge_period_rollup_rows_cypher',
    'neo4j_bulk_timestamps',
    'preload_hvac_hourly_summaries_by_asset_window_cypher',
    'preload_meter_rollups_by_spine_window_cypher',
    'preload_period_rollups_by_spine_window_cypher',
    'property_maps_from_cypher_rows',
    'safe_connect_relationship',
    'spine_window_where_clauses',
)


log = logging.getLogger(__name__)


def neo4j_bulk_timestamps() -> dict[str, datetime]:
    """UTC datetimes for Cypher-created nodes (matches DjangoNeoModel save semantics)."""
    now = datetime.now(UTC)
    return {'created': now, 'updated': now}


def _normalize_period_rollup_datetime_for_merge(value: Any) -> Any:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return value
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return value


def _normalize_period_rollup_row_for_merge(row: dict[str, Any]) -> dict[str, Any]:
    normalized_row = dict(row)
    for key, value in tuple(normalized_row.items()):
        if value is None:
            continue
        if key in {'created', 'updated'}:
            normalized_row[key] = _normalize_period_rollup_datetime_for_merge(value)
            continue
        if key.endswith('_json'):
            if isinstance(value, str):
                normalized_row[key] = value
            else:
                normalized_row[key] = json.dumps(value, sort_keys=True)
    return normalized_row


def safe_connect_relationship(
    connect_callable: Any,
    *,
    description: str,
    reraise_cardinality: bool = True,
) -> None:
    """Run a NeoModel ``.connect()`` with cluster leader retries on transient errors."""
    from agent_neo.graph_db import reconnect_neo4j_driver, retry_neo4j_cluster_operation

    try:
        retry_neo4j_cluster_operation(
            connect_callable,
            description=description,
            reconnect=reconnect_neo4j_driver,
        )
    except Exception as exc:
        if reraise_cardinality:
            try:
                from neomodel.exceptions import CardinalityViolation  # noqa: PLC0415

                if isinstance(exc, CardinalityViolation):
                    raise
            except ImportError:
                pass
        log.warning(
            '%s: relationship connect failed (%s): %s',
            description,
            type(exc).__name__,
            exc,
        )


def spine_window_where_clauses(
    *,
    node_alias: str = 'n',
    facility_name: str,
    time_granularity: str | None = None,
    algorithm_version: str | None = None,
    local_period_start_gte: str | None = None,
    local_period_start_lt: str | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Build indexed ``WHERE`` fragments for period-spine range scans (populate, preload)."""
    where_clauses = [f'{node_alias}.facility_name = $facility_name']
    params: dict[str, Any] = {'facility_name': facility_name}
    if time_granularity is not None:
        where_clauses.append(f'{node_alias}.time_granularity = $time_granularity')
        params['time_granularity'] = time_granularity
    if algorithm_version is not None:
        where_clauses.append(f'{node_alias}.algorithm_version = $algorithm_version')
        params['algorithm_version'] = algorithm_version
    if local_period_start_gte is not None:
        where_clauses.append(f'{node_alias}.local_period_start >= $local_period_start_gte')
        params['local_period_start_gte'] = local_period_start_gte
    if local_period_start_lt is not None:
        where_clauses.append(f'{node_alias}.local_period_start < $local_period_start_lt')
        params['local_period_start_lt'] = local_period_start_lt
    return where_clauses, params


def fetch_cache_keys_by_indexed_filters_cypher(
    label: str,
    where_clauses: list[str],
    params: dict[str, Any],
    *,
    fetch_cache_keys_for_filter_query: str,
    cache_key_property: str = 'cache_key',
) -> list[str]:
    """Return ``cache_key`` values matching indexed filters (no ORM node hydration)."""
    if not where_clauses:
        return []
    if cache_key_property != 'cache_key':
        where_clauses = [*where_clauses]
        return_clause = f'RETURN n.{cache_key_property} AS cache_key'
        base = bind_where_clause(
            bind_label(fetch_cache_keys_for_filter_query, label),
            where_clauses,
        )
        query = base.rsplit('RETURN', 1)[0] + return_clause
    else:
        query = bind_where_clause(
            bind_label(fetch_cache_keys_for_filter_query, label),
            where_clauses,
        )
    rows, _ = cypher_read(query, params)
    return [str(row[0]) for row in rows if row and row[0]]


def property_maps_from_cypher_rows(
    rows: list[list[Any]],
    columns: list[str],
) -> dict[str, dict[str, Any]]:
    """Build ``cache_key`` → flat property dict from ``properties(n)`` result rows."""
    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        row_dict = dict(zip(columns, row, strict=False))
        cache_key = str(row_dict.get('cache_key') or '')
        node_properties = row_dict.get('node_properties')
        if not cache_key or node_properties is None:
            continue
        flat = dict(node_properties)
        flat['cache_key'] = cache_key
        by_key[cache_key] = flat
    return by_key


def hourly_summary_maps_from_cypher_rows(
    rows: list[list[Any]],
    columns: list[str],
) -> dict[str, dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        row_dict = dict(zip(columns, row, strict=False))
        cache_key = str(row_dict.pop('cache_key', '') or '')
        if cache_key:
            by_key[cache_key] = row_dict
    return by_key


def fetch_period_rollup_cache_keys_by_spine_window_cypher(
    label: str,
    params: dict[str, Any],
    *,
    fetch_cache_keys_by_spine_window_query: str | Any,
) -> set[str]:
    """Return existing ``cache_key`` values for a period rollup label in a spine window."""
    query = bind_label(fetch_cache_keys_by_spine_window_query, label)
    rows, _ = cypher_read(query, params)
    return {str(row[0]) for row in rows if row and row[0]}


def preload_meter_rollups_by_spine_window_cypher(
    label: str,
    params: dict[str, Any],
    *,
    preload_meter_rollups_by_spine_window_query: str | Any,
) -> tuple[list[list[Any]], list[str]]:
    """Load meter rollup rows for bulk index construction."""
    query = bind_label(preload_meter_rollups_by_spine_window_query, label)
    return cypher_read(query, params)


def fetch_period_rollup_rows_by_cache_keys_cypher(
    label: str,
    cache_keys: list[str],
    *,
    fetch_rows_by_cache_keys_query: str | Any,
    chunk_size: int = DEFAULT_IN_CHUNK_SIZE,
) -> dict[str, dict[str, Any]]:
    """Batch-fetch period rollup property maps by ``cache_key`` (indexed IN lookup)."""
    if not cache_keys:
        return {}

    by_key: dict[str, dict[str, Any]] = {}
    query = bind_label(fetch_rows_by_cache_keys_query, label)

    def _fetch_chunk(chunk_keys: list[str]) -> None:
        rows, columns = cypher_read(query, {'keys': chunk_keys})
        by_key.update(property_maps_from_cypher_rows(rows, columns))

    for_each_chunk(cache_keys, chunk_size=chunk_size, action=_fetch_chunk)
    return by_key


def preload_period_rollups_by_spine_window_cypher(
    label: str,
    params: dict[str, Any],
    *,
    preload_period_rollups_by_spine_window_query: str | Any,
) -> dict[str, dict[str, Any]]:
    """Load all period rollup property maps in a spine window keyed by ``cache_key``."""
    query = bind_label(preload_period_rollups_by_spine_window_query, label)
    rows, columns = cypher_read(query, params)
    return property_maps_from_cypher_rows(rows, columns)


def fetch_hvac_hourly_summaries_by_cache_keys_cypher(
    label: str,
    cache_keys: list[str],
    *,
    fetch_hourly_summaries_by_cache_keys_query: str | Any,
    chunk_size: int = DEFAULT_IN_CHUNK_SIZE,
) -> dict[str, dict[str, Any]]:
    """Batch-fetch hourly HVAC summary rows by ``cache_key``."""
    if not cache_keys:
        return {}

    by_key: dict[str, dict[str, Any]] = {}
    query = bind_label(fetch_hourly_summaries_by_cache_keys_query, label)

    def _fetch_chunk(chunk_keys: list[str]) -> None:
        rows, columns = cypher_read(query, {'keys': chunk_keys})
        by_key.update(hourly_summary_maps_from_cypher_rows(rows, columns))

    for_each_chunk(cache_keys, chunk_size=chunk_size, action=_fetch_chunk)
    return by_key


def preload_hvac_hourly_summaries_by_asset_window_cypher(
    label: str,
    params: dict[str, Any],
    *,
    preload_hourly_summaries_by_asset_window_query: str | Any,
) -> dict[str, dict[str, Any]]:
    """Load hourly HVAC summaries for one asset in a local-hour window."""
    query = bind_label(preload_hourly_summaries_by_asset_window_query, label)
    rows, columns = cypher_read(query, params)
    return hourly_summary_maps_from_cypher_rows(rows, columns)


def merge_period_rollup_rows_cypher(
    label: str,
    rows: list[dict[str, Any]],
    *,
    merge_rows_by_cache_key_query: str,
    merge_rows_by_cache_key_on_match_query: str,
    chunk_size: int = DEFAULT_IN_CHUNK_SIZE,
    update_on_match: bool = False,
) -> int:
    """MERGE period rollup nodes by ``cache_key``; returns rows written."""
    if not rows:
        return 0
    normalized_rows = [_normalize_period_rollup_row_for_merge(row) for row in rows]
    template = merge_rows_by_cache_key_on_match_query if update_on_match else merge_rows_by_cache_key_query
    query = bind_label(template, label)
    written = 0

    def _merge_chunk(chunk_rows: list[dict[str, Any]]) -> None:
        nonlocal written
        cypher_write(query, {'rows': chunk_rows})
        written += len(chunk_rows)

    for_each_chunk(normalized_rows, chunk_size=chunk_size, action=_merge_chunk)
    return written
