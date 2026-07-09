"""Indexed period spine fields shared by rollup NeoModels."""


from __future__ import annotations

from typing import LiteralString

from neomodel.properties import Property, StringProperty


__all__: tuple[LiteralString, ...] = (
    'PERIOD_SPINE_MAX_STRING_LENGTH',
    'PeriodSpineMixin',
)


PERIOD_SPINE_MAX_STRING_LENGTH = 3333


class PeriodSpineMixin:
    """Common cache identity and period bounds for period rollup graph nodes."""

    cache_key: Property = StringProperty(
        primary_key=True,
        unique_index=True,
        required=True,
        db_property='cache_key',
        max_length=PERIOD_SPINE_MAX_STRING_LENGTH,
    )
    facility_name: Property = StringProperty(
        index=True,
        required=True,
        db_property='facility_name',
        max_length=PERIOD_SPINE_MAX_STRING_LENGTH,
    )
    time_granularity: Property = StringProperty(
        index=True,
        required=True,
        db_property='time_granularity',
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
    algorithm_version: Property = StringProperty(
        index=True,
        required=True,
        db_property='algorithm_version',
        max_length=PERIOD_SPINE_MAX_STRING_LENGTH,
    )
