"""Indexed period spine fields shared by rollup NeoModels."""


from __future__ import annotations

from typing import LiteralString

from neomodel.properties import Property, StringProperty

from agent_neo.graph_db.cypher_templates import SCOPE_NAME_DB_PROPERTY


__all__: tuple[LiteralString, ...] = (
    'PERIOD_SPINE_MAX_STRING_LENGTH',
    'PeriodSpineMixin',
)


PERIOD_SPINE_MAX_STRING_LENGTH = 4096


class PeriodSpineMixin:
    """Common cache identity and period bounds for period rollup graph nodes."""

    cache_key: Property = StringProperty(
        primary_key=True,
        unique_index=True,
        required=True,
        db_property='cache_key',
        max_length=PERIOD_SPINE_MAX_STRING_LENGTH,
    )
    # Stored under ``SCOPE_NAME_DB_PROPERTY``; code reads and writes ``scope_name``.
    scope_name: Property = StringProperty(
        index=True,
        required=True,
        db_property=SCOPE_NAME_DB_PROPERTY,
        max_length=PERIOD_SPINE_MAX_STRING_LENGTH,
    )
    temporal_granularity: Property = StringProperty(
        index=True,
        required=True,
        db_property='temporal_granularity',
        max_length=PERIOD_SPINE_MAX_STRING_LENGTH,
    )
    local_period_start: Property = StringProperty(
        index=True,
        required=True,
        db_property='local_period_start',
        max_length=PERIOD_SPINE_MAX_STRING_LENGTH,
    )
    local_period_end: Property = StringProperty(
        index=True,
        required=True,
        db_property='local_period_end',
        max_length=PERIOD_SPINE_MAX_STRING_LENGTH,
    )
