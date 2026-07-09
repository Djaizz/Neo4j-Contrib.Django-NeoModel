"""Tests for packaged graph_db Cypher templates and bulk helpers."""


from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent_neo.graph_db import (
    FETCH_CACHE_KEYS_BY_SPINE_WINDOW,
    FETCH_ROWS_BY_CACHE_KEYS,
    MERGE_ROWS_BY_CACHE_KEY,
    PRELOAD_PERIOD_ROLLUPS_BY_SPINE_WINDOW,
    bind_label,
    bind_label_and_property,
    merge_period_rollup_rows_cypher,
    spine_window_where_clauses,
)
from agent_neo.graph_db.cypher_templates import (
    COUNT_NODES_BY_PROPERTY_IN_KEYS,
    COUNT_ROLLUPS_IN_WINDOW,
)
from agent_neo.graph_db.query_bind import LABEL_PLACEHOLDER, WHERE_PLACEHOLDER


def test_cypher_templates_load_non_empty() -> None:
    assert COUNT_NODES_BY_PROPERTY_IN_KEYS
    assert COUNT_ROLLUPS_IN_WINDOW
    assert 'RETURN' in str(FETCH_CACHE_KEYS_BY_SPINE_WINDOW.query)
    assert 'UNWIND $rows AS row' in MERGE_ROWS_BY_CACHE_KEY


def test_bind_label_substitutes_placeholder() -> None:
    query = bind_label(FETCH_CACHE_KEYS_BY_SPINE_WINDOW, 'Test_PeriodRollup')
    assert LABEL_PLACEHOLDER not in query
    assert 'Test_PeriodRollup' in query
    assert 'RETURN n.cache_key AS cache_key' in query


def test_bind_label_and_property_for_cache_key_delete() -> None:
    query = bind_label_and_property(
        COUNT_NODES_BY_PROPERTY_IN_KEYS,
        label='Test_PeriodRollup',
        property_name='cache_key',
    )
    assert 'Test_PeriodRollup' in query
    assert 'n.cache_key IN $keys' in query


def test_fetch_rows_by_cache_keys_template() -> None:
    query = bind_label(FETCH_ROWS_BY_CACHE_KEYS, 'Test_PeriodRollup')
    assert 'Test_PeriodRollup' in query
    assert 'cache_key IN $keys' in query
    assert 'node_properties' in query


def test_preload_period_rollups_by_spine_window_template() -> None:
    query = bind_label(PRELOAD_PERIOD_ROLLUPS_BY_SPINE_WINDOW, 'Test_PeriodRollup')
    assert 'Test_PeriodRollup' in query
    assert 'local_period_start >=' in query
    assert 'algorithm_version' not in query


def test_spine_window_where_clauses_omit_algorithm_version() -> None:
    clauses, params = spine_window_where_clauses(
        facility_name='Fac',
        time_granularity='daily',
        local_period_start_gte='2026-01-01T00:00',
        local_period_start_lt='2026-02-01T00:00',
    )
    assert 'n.facility_name = $facility_name' in clauses
    assert 'n.local_period_start >= $local_period_start_gte' in clauses
    assert 'algorithm_version' not in params
    assert not any('algorithm_version' in clause for clause in clauses)


def test_merge_template_has_unwind() -> None:
    query = bind_label(MERGE_ROWS_BY_CACHE_KEY, 'Test_Label')
    assert 'UNWIND $rows AS row' in query
    assert 'MERGE (n:`Test_Label`' in query


@patch('agent_neo.graph_db.period_rollup_bulk.cypher_write')
def test_merge_period_rollup_rows_uses_default_template(mock_write: MagicMock) -> None:
    written = merge_period_rollup_rows_cypher(
        'ForgeODB_Analytical_HVACZoneComfortPeriodRollup',
        [{'cache_key': 'k1', 'facility_name': 'F'}],
        chunk_size=500,
    )
    assert written == 1
    assert mock_write.call_count == 1
    assert 'UNWIND $rows AS row' in mock_write.call_args[0][0]
