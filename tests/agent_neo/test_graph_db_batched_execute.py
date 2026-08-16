"""Tests for ``batched_cypher_execute`` chunk bounding, results and retry tuning.

Each test names the property it protects. The three that matter most are the ones
an item-only budget cannot give you: an empty item list is a legitimate payload
and must survive to the statement, a crowd of such rows must still be bounded,
and an over-budget single row must be divisible when the payload is idempotent.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from agent_neo.graph_db._core import (
    _chunk_rows_by_item_budget,
    _split_row_by_item_budget,
    batched_cypher_execute,
)


def _rows(*item_counts: int, key: str = 'targets') -> list[dict[str, Any]]:
    """Rows carrying ``item_counts`` items each, plus a distinguishing source."""
    return [
        {'source': f'src-{index}', key: [f'tgt-{index}-{n}' for n in range(count)]}
        for index, count in enumerate(item_counts)
    ]


# ============================================================================
# _split_row_by_item_budget
# ============================================================================

def test_split_row_leaves_a_within_budget_row_untouched() -> None:
    row = _rows(3)[0]
    assert _split_row_by_item_budget(row, count_key='targets', batch_size=10) == [row]


def test_split_row_divides_an_over_budget_row_and_copies_other_keys() -> None:
    row = _rows(5)[0]
    parts = _split_row_by_item_budget(row, count_key='targets', batch_size=2)
    assert [len(part['targets']) for part in parts] == [2, 2, 1]
    # Every sub-row is the same statement applied to a slice of one subject.
    assert {part['source'] for part in parts} == {'src-0'}
    # No item is lost or duplicated.
    assert [t for part in parts for t in part['targets']] == row['targets']


# ============================================================================
# _chunk_rows_by_item_budget — the item budget (HFCODB-0003 D1: items, not rows)
# ============================================================================

def test_chunks_are_bounded_by_item_count() -> None:
    chunks = _chunk_rows_by_item_budget(
        _rows(4, 4, 4), count_key='targets', batch_size=10,
    )
    # Greedy: two rows fit in 10 items, the third opens a new chunk.
    assert [sum(len(r['targets']) for r in chunk) for chunk in chunks] == [8, 4]


def test_no_chunk_exceeds_the_item_budget_unless_one_row_alone_does() -> None:
    chunks = _chunk_rows_by_item_budget(
        _rows(6, 6, 6), count_key='targets', batch_size=10,
    )
    # Two 6-item rows cannot share a 10-item budget, so each stands alone.
    assert [sum(len(r['targets']) for r in chunk) for chunk in chunks] == [6, 6, 6]


def test_a_single_over_budget_row_is_not_split_by_default() -> None:
    chunks = _chunk_rows_by_item_budget(
        _rows(25), count_key='targets', batch_size=10,
    )
    assert len(chunks) == 1
    assert len(chunks[0][0]['targets']) == 25


def test_allow_row_split_divides_an_over_budget_row() -> None:
    chunks = _chunk_rows_by_item_budget(
        _rows(25), count_key='targets', batch_size=10, allow_row_split=True,
    )
    assert [sum(len(r['targets']) for r in chunk) for chunk in chunks] == [10, 10, 5]


# ============================================================================
# _chunk_rows_by_item_budget — the row budget
# ============================================================================

def test_rows_with_empty_item_lists_are_kept_not_skipped() -> None:
    """An empty item list is how "this subject now has none" is expressed.

    HFCODB-0002's verb vocabulary: ``set`` means replace with exactly this, and
    the empty set is a legal target state that must clear rather than be ignored.
    """
    chunks = _chunk_rows_by_item_budget(
        _rows(0, 0, 2), count_key='targets', batch_size=10,
    )
    assert sum(len(chunk) for chunk in chunks) == 3


def test_a_crowd_of_empty_rows_is_still_bounded_by_the_row_budget() -> None:
    """The failure an item-only budget cannot prevent.

    Empty rows contribute zero items, so an item-only budget would put all
    50 of these in one statement no matter how many there were.
    """
    chunks = _chunk_rows_by_item_budget(
        _rows(*([0] * 50)), count_key='targets', batch_size=10,
    )
    assert max(len(chunk) for chunk in chunks) <= 10
    assert sum(len(chunk) for chunk in chunks) == 50


# ============================================================================
# batched_cypher_execute
# ============================================================================

def test_returns_accumulated_result_rows_across_chunks() -> None:
    """The graph's own account of the write, which the caller needs to verify it."""
    with patch('agent_neo.graph_db._core.db') as mock_db:
        mock_db.cypher_query.return_value = ([[7]], None)
        results = batched_cypher_execute(
            _rows(4, 4, 4), 'UNWIND $rows AS row RETURN 1 AS deleted',
            count_key='targets', batch_size=10,
        )
    assert mock_db.cypher_query.call_count == 2
    assert results == [[7], [7]]


def test_returns_empty_list_for_no_rows_without_touching_the_database() -> None:
    with patch('agent_neo.graph_db._core.db') as mock_db:
        assert batched_cypher_execute(
            [], 'UNWIND $rows AS row RETURN 1', count_key='targets',
        ) == []
    mock_db.cypher_query.assert_not_called()


def test_a_write_with_no_return_contributes_no_results() -> None:
    with patch('agent_neo.graph_db._core.db') as mock_db:
        mock_db.cypher_query.return_value = ([], None)
        assert batched_cypher_execute(
            _rows(2), 'UNWIND $rows AS row MERGE (:X {id: row.source})',
            count_key='targets',
        ) == []


def test_retry_tuning_reaches_the_retry_loop() -> None:
    """The values in force must be the values used.

    ``retry_neo4j_cluster_operation`` binds its tuning as parameter defaults at
    definition time, so a caller configuring retries elsewhere has no effect
    unless the tuning is passed through here.
    """
    with (
        patch('agent_neo.graph_db._core.db') as mock_db,
        patch('agent_neo.graph_db._core.retry_neo4j_cluster_operation') as mock_retry,
    ):
        mock_db.cypher_query.return_value = ([], None)
        mock_retry.return_value = ([], None)
        batched_cypher_execute(
            _rows(2), 'UNWIND $rows AS row RETURN 1',
            count_key='targets',
            retry_tuning={'max_attempts': 42, 'retry_delay_seconds': 1.5},
        )
    assert mock_retry.call_args.kwargs['max_attempts'] == 42
    assert mock_retry.call_args.kwargs['retry_delay_seconds'] == 1.5


def test_omitted_retry_tuning_forwards_nothing() -> None:
    with (
        patch('agent_neo.graph_db._core.db') as mock_db,
        patch('agent_neo.graph_db._core.retry_neo4j_cluster_operation') as mock_retry,
    ):
        mock_db.cypher_query.return_value = ([], None)
        mock_retry.return_value = ([], None)
        batched_cypher_execute(
            _rows(2), 'UNWIND $rows AS row RETURN 1', count_key='targets',
        )
    assert 'max_attempts' not in mock_retry.call_args.kwargs


def test_every_row_reaches_a_statement_exactly_once() -> None:
    submitted: list[str] = []

    def _capture(_query: str, params: dict[str, Any]) -> tuple[list, None]:
        submitted.extend(row['source'] for row in params['rows'])
        return ([], None)

    with patch('agent_neo.graph_db._core.db') as mock_db:
        mock_db.cypher_query.side_effect = _capture
        batched_cypher_execute(
            _rows(4, 0, 4, 0, 4), 'UNWIND $rows AS row RETURN 1',
            count_key='targets', batch_size=6,
        )
    assert submitted == [f'src-{index}' for index in range(5)]
