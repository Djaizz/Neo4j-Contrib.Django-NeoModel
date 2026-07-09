"""Placeholder substitution for parameterized Cypher templates."""


from __future__ import annotations

from typing import LiteralString

from agent_neo.graph_db._core import GraphDbQueryAndReturnHeaderList


__all__: tuple[LiteralString, ...] = (
    'LABEL_PLACEHOLDER',
    'PROPERTY_PLACEHOLDER',
    'WHERE_PLACEHOLDER',
    'bind_label',
    'bind_label_and_property',
    'bind_where_clause',
)


LABEL_PLACEHOLDER = '__LABEL__'
PROPERTY_PLACEHOLDER = '__PROPERTY__'
WHERE_PLACEHOLDER = '__WHERE__'


def bind_label(query: GraphDbQueryAndReturnHeaderList | str, label: str) -> str:
    """Substitute ``__LABEL__`` with a NeoModel ``__label__`` (not user input)."""
    text = query.query if isinstance(query, GraphDbQueryAndReturnHeaderList) else query
    if LABEL_PLACEHOLDER not in text:
        raise ValueError(f'query missing {LABEL_PLACEHOLDER!r}')
    return text.replace(LABEL_PLACEHOLDER, label)


def bind_label_and_property(query_text: str, *, label: str, property_name: str) -> str:
    """Substitute label and property placeholders for invalidation templates."""
    if PROPERTY_PLACEHOLDER not in query_text:
        raise ValueError(f'query missing {PROPERTY_PLACEHOLDER!r}')
    return bind_label(
        query_text.replace(PROPERTY_PLACEHOLDER, property_name),
        label,
    )


def bind_where_clause(query_text: str, where_clauses: list[str]) -> str:
    """Replace ``__WHERE__`` with ``WHERE a AND b`` or remove if empty."""
    if not where_clauses:
        return query_text.replace(WHERE_PLACEHOLDER, '').strip()
    return query_text.replace(WHERE_PLACEHOLDER, f"WHERE {' AND '.join(where_clauses)}")
