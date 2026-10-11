"""Graph database operations for analytical period rollups: packaged templates and bulk helpers.

The generic graph-DB layer these build on — connection config and lifecycle, query
loading, retried and batched Cypher execution, template binding — is
``django_neomodel.graph_db``.
"""


from __future__ import annotations

from typing import LiteralString

from agent_neo.graph_db.cypher_templates import (
    COUNT_ROLLUPS_IN_WINDOW,
    DELETE_ROLLUPS_IN_WINDOW,
    FETCH_CACHE_KEYS_BY_SPINE_WINDOW,
    FETCH_ROWS_BY_CACHE_KEYS,
    MERGE_ROWS_BY_CACHE_KEY,
    MERGE_ROWS_BY_CACHE_KEY_ON_MATCH,
    PRELOAD_PERIOD_ROLLUPS_BY_SPINE_WINDOW,
)
from agent_neo.graph_db.period_rollup_bulk import (
    fetch_cache_keys_by_indexed_filters_cypher,
    fetch_period_rollup_cache_keys_by_spine_window_cypher,
    fetch_period_rollup_rows_by_cache_keys_cypher,
    rows_by_cache_key_from_cypher_rows,
    merge_period_rollup_rows_cypher,
    preload_period_rollups_by_spine_window_cypher,
    property_maps_from_cypher_rows,
    spine_window_where_clauses,
)


__all__: tuple[LiteralString, ...] = (
    "COUNT_ROLLUPS_IN_WINDOW",
    "DELETE_ROLLUPS_IN_WINDOW",
    "FETCH_CACHE_KEYS_BY_SPINE_WINDOW",
    "FETCH_ROWS_BY_CACHE_KEYS",
    "MERGE_ROWS_BY_CACHE_KEY",
    "MERGE_ROWS_BY_CACHE_KEY_ON_MATCH",
    "PRELOAD_PERIOD_ROLLUPS_BY_SPINE_WINDOW",
    "fetch_cache_keys_by_indexed_filters_cypher",
    "fetch_period_rollup_cache_keys_by_spine_window_cypher",
    "fetch_period_rollup_rows_by_cache_keys_cypher",
    "rows_by_cache_key_from_cypher_rows",
    "merge_period_rollup_rows_cypher",
    "preload_period_rollups_by_spine_window_cypher",
    "property_maps_from_cypher_rows",
    "spine_window_where_clauses",
)
