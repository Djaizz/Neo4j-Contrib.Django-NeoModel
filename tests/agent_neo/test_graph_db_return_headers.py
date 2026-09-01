"""`_parse_return_headers` reads the query, not its commentary.

This function had **no test at all** until 2026-09, which is why three silent
truncations survived in it: every one returned a plausible, shorter column list
instead of raising, and a short header list only surfaces much later, as a lookup
for a column the caller was told does not exist.

What is guarded here is the **order of operations** — comments are stripped before
the RETURN is located and before the clause is truncated — not the particular
regexes that implement it.
"""


from __future__ import annotations

import pytest

from agent_neo.graph_db._core import _parse_return_headers, _strip_cypher_comments


def test_a_plain_return_yields_its_aliases() -> None:
    assert _parse_return_headers('MATCH (n) RETURN n.a AS a, n.b AS b') == ['a', 'b']


def test_a_header_block_above_the_query_is_not_part_of_the_query() -> None:
    """The shape every governed `.cypher` file uses: title, parameters, columns.

    The header names the columns in prose, and the prose must not be mistaken for
    the projection.
    """
    query = (
        '// Read chunks by identity key.\n'
        '//\n'
        '// Parameters:\n'
        '//   $chunk_keys (list[str]): identity keys (required)\n'
        '//\n'
        '// Returns:\n'
        '//   chunk_key: the identity key\n'
        '//   is_empty: true when the window carries no samples\n'
        'MATCH (n) RETURN n.chunk_key AS chunk_key, n.is_empty AS is_empty'
    )
    assert _parse_return_headers(query) == ['chunk_key', 'is_empty']


def test_a_comment_inside_the_return_clause_does_not_truncate_it() -> None:
    """A per-column comment saying "LIMIT" must not act as a LIMIT clause.

    The clause-terminator search looks for ORDER BY and LIMIT. Run before the
    comment strip, it found this comment's `LIMIT` and cut the projection there,
    silently dropping columns `b` and `c`.
    """
    query = (
        'MATCH (n)\n'
        'RETURN n.a AS a,   // no LIMIT is applied here\n'
        '       n.b AS b,\n'
        '       n.c AS c'
    )
    assert _parse_return_headers(query) == ['a', 'b', 'c']


def test_a_comment_saying_order_by_does_not_truncate_either() -> None:
    query = (
        'MATCH (n)\n'
        'RETURN n.a AS a,   // callers ORDER BY this themselves\n'
        '       n.b AS b'
    )
    assert _parse_return_headers(query) == ['a', 'b']


def test_a_commented_return_below_the_query_does_not_win() -> None:
    """The LAST `RETURN` is the one taken, so a comment could impersonate it."""
    query = (
        'MATCH (n)\n'
        'RETURN n.a AS a\n'
        '// RETURN columns: nonsense, ignored'
    )
    assert _parse_return_headers(query) == ['a']


def test_a_real_order_by_and_limit_still_terminate_the_clause() -> None:
    """The fix must not cost the behaviour the truncation existed for."""
    query = 'MATCH (n) RETURN n.a AS a, n.b AS b ORDER BY n.a LIMIT 10'
    assert _parse_return_headers(query) == ['a', 'b']


def test_a_block_comment_is_stripped_too() -> None:
    assert _parse_return_headers(
        'MATCH (n) /* commentary */ RETURN n.a AS a, n.b AS b'
    ) == ['a', 'b']


def test_a_query_with_no_return_raises_rather_than_guessing() -> None:
    with pytest.raises(ValueError, match='RETURN statement not found'):
        _parse_return_headers('MATCH (n) SET n.x = 1')


def test_a_query_that_is_only_a_comment_saying_return_still_raises() -> None:
    """Stripping first means a commented RETURN cannot fake a projection."""
    with pytest.raises(ValueError, match='RETURN statement not found'):
        _parse_return_headers('// RETURN a, b\nMATCH (n) SET n.x = 1')


def test_the_comment_stripper_leaves_the_code_around_a_comment_intact() -> None:
    assert _strip_cypher_comments('MATCH (n)  // note\nRETURN n') == 'MATCH (n)  \nRETURN n'
    assert _strip_cypher_comments('a /* b */ c') == 'a  c'
