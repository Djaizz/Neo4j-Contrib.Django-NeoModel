"""Tests for the flat-row (``count_key=None``) chunking path.

The property that matters: a flat-row caller must get *exactly* the division a
hand-rolled ``rows[start:start + batch_size]`` loop produces. That equivalence is
the whole argument for replacing such loops with the shared helper — it is what
makes the swap a no-op for throughput, so the only things that change are the
retry coverage and the results accumulation the helper adds.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_neo.graph_db._core import (
    _chunk_rows_by_item_budget,
    batched_cypher_execute,
)


def _flat_rows(count: int) -> list[dict[str, Any]]:
    """Rows with no list-valued key — one row is one node."""
    return [
        {'uuid': f'uuid-{index}', 'name': f'name-{index}'} for index in range(count)
    ]


def _manual_slices(
    rows: list[dict[str, Any]], batch_size: int,
) -> list[list[dict[str, Any]]]:
    """The hand-rolled chunk loop the flat-row path is meant to reproduce."""
    return [rows[start:start + batch_size] for start in range(0, len(rows), batch_size)]


# ============================================================================
# Chunk boundaries are byte-identical to manual slicing
# ============================================================================

@pytest.mark.parametrize('row_count', [0, 1, 9, 10, 11, 20, 21, 37])
def test_flat_row_chunks_are_identical_to_manual_slicing(row_count: int) -> None:
    rows = _flat_rows(row_count)
    assert _chunk_rows_by_item_budget(
        rows, count_key=None, batch_size=10,
    ) == _manual_slices(rows, 10)


def test_no_rows_produces_no_chunks() -> None:
    assert _chunk_rows_by_item_budget([], count_key=None, batch_size=10) == []


def test_one_row_produces_one_chunk_of_one() -> None:
    rows = _flat_rows(1)
    assert _chunk_rows_by_item_budget(rows, count_key=None, batch_size=10) == [rows]


def test_exactly_batch_size_rows_produce_one_full_chunk() -> None:
    """The boundary an off-by-one gets wrong in the cheap direction."""
    rows = _flat_rows(10)
    chunks = _chunk_rows_by_item_budget(rows, count_key=None, batch_size=10)
    assert [len(chunk) for chunk in chunks] == [10]


def test_batch_size_plus_one_rows_produce_a_full_chunk_and_a_remainder() -> None:
    """The boundary an off-by-one gets wrong in the expensive direction."""
    rows = _flat_rows(11)
    chunks = _chunk_rows_by_item_budget(rows, count_key=None, batch_size=10)
    assert [len(chunk) for chunk in chunks] == [10, 1]


def test_flat_rows_are_passed_through_untouched() -> None:
    """No key is added, removed or reordered — the row reaches Cypher as written."""
    rows = _flat_rows(3)
    chunks = _chunk_rows_by_item_budget(rows, count_key=None, batch_size=10)
    assert chunks[0][0] is rows[0]


def test_every_flat_row_reaches_a_statement_exactly_once_and_in_order() -> None:
    submitted: list[str] = []

    def _capture(_query: str, params: dict[str, Any]) -> tuple[list, None]:
        submitted.extend(row['uuid'] for row in params['rows'])
        return ([], None)

    with patch('agent_neo.graph_db._core.db') as mock_db:
        mock_db.cypher_query.side_effect = _capture
        batched_cypher_execute(
            _flat_rows(25), 'UNWIND $rows AS row MERGE (:X {uuid: row.uuid})',
            count_key=None, batch_size=10,
        )
    assert submitted == [f'uuid-{index}' for index in range(25)]
    assert mock_db.cypher_query.call_count == 3


def test_flat_row_results_are_accumulated_across_chunks() -> None:
    """What a ``read_back=False`` caller counts to confirm its write landed."""
    with patch('agent_neo.graph_db._core.db') as mock_db:
        mock_db.cypher_query.return_value = ([['written']], None)
        results = batched_cypher_execute(
            _flat_rows(25), 'UNWIND $rows AS row MERGE (n:X) RETURN n.uuid AS uuid',
            count_key=None, batch_size=10,
        )
    assert results == [['written'], ['written'], ['written']]


def test_count_key_is_still_honoured_when_given() -> None:
    """The default must not change the behaviour of the 16 existing call sites."""
    rows = [
        {'source': 'a', 'targets': [1, 2, 3, 4]},
        {'source': 'b', 'targets': [1, 2, 3, 4]},
        {'source': 'c', 'targets': [1, 2, 3, 4]},
    ]
    chunks = _chunk_rows_by_item_budget(rows, count_key='targets', batch_size=10)
    assert [len(chunk) for chunk in chunks] == [2, 1]


# ============================================================================
# allow_row_split with no count_key must raise
# ============================================================================

def test_row_split_without_a_count_key_raises_in_the_chunker() -> None:
    """Silently not splitting would ship the unbounded statement, under a flag
    whose name promises it cannot happen."""
    with pytest.raises(ValueError, match='allow_row_split=True requires a count_key'):
        _chunk_rows_by_item_budget(
            _flat_rows(3), count_key=None, batch_size=10, allow_row_split=True,
        )


def test_row_split_without_a_count_key_raises_before_any_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_db = MagicMock()
    monkeypatch.setattr('agent_neo.graph_db._core.db', mock_db)

    with pytest.raises(ValueError, match='allow_row_split=True requires a count_key'):
        batched_cypher_execute(
            _flat_rows(3), 'UNWIND $rows AS row RETURN 1',
            count_key=None, allow_row_split=True,
        )

    mock_db.cypher_query.assert_not_called()


def test_row_split_without_a_count_key_raises_even_for_an_empty_payload() -> None:
    """An incoherent request is incoherent regardless of what it was handed.

    The empty-payload early return sits before the chunker, so validating only
    there would let the contract violation through on any run that happened to
    have nothing to write.
    """
    with pytest.raises(ValueError, match='allow_row_split=True requires a count_key'):
        batched_cypher_execute(
            [], 'UNWIND $rows AS row RETURN 1',
            count_key=None, allow_row_split=True,
        )


def test_row_split_with_a_count_key_still_works() -> None:
    chunks = _chunk_rows_by_item_budget(
        [{'source': 'a', 'targets': list(range(25))}],
        count_key='targets', batch_size=10, allow_row_split=True,
    )
    assert [len(chunk[0]['targets']) for chunk in chunks] == [10, 10, 5]
