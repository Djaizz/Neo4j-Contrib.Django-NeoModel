"""Canonical computed-graph-node identity and the single ``cache_key`` builder.

Every computed graph node instance is addressed by **one** deterministic logical-slot key.
This module is the single source of truth for that key (no parallel family-specific builders).

Rationale: the key is **de-versioned** — *which design produced an instance* lives on the
``computes_design`` edge; *whether it is current* is ``lifecycle_status``. Never bake a
version token into the key. Audit/replay pins a design node via ``ComputeRequest.concept_selection``.
"""


from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import LiteralString

from agent_neo.util.datetime import TimeGranularity, period_anchor


__all__: tuple[LiteralString, ...] = (
    'ComputedSlotIdentity',
    'build_slot_key',
)


def build_slot_key(
    *,
    computed_node_class_name: str,
    scope_name: str,
    subject_kind: str,
    subject_key: str,
    time_granularity: TimeGranularity | str,
    local_period_start: datetime,
    day_classif: str = 'all',
    hour_classif: str = 'all',
) -> str:
    """The one canonical logical-slot id for any computed graph node instance.

    Format (de-versioned)::

        {computed_node_class_name}|{scope_name}|{subject_kind}={subject_key}|{time_granularity}|{period_anchor}

    When either classification is non-``all`` the key is suffixed with ``|d={day}|h={hour}`` so
    sliced rollups occupy distinct slots; the common unsliced case omits the suffix.
    ``computed_node_class_name`` is the concrete class name (``cls.__name__``).
    """
    anchor = period_anchor(time_granularity=time_granularity, local_period_start=local_period_start)
    base = f'{computed_node_class_name}|{scope_name}|{subject_kind}={subject_key}|{time_granularity}|{anchor}'
    if day_classif == 'all' and hour_classif == 'all':
        return base
    return f'{base}|d={day_classif}|h={hour_classif}'


@dataclass(frozen=True, slots=True)
class ComputedSlotIdentity:
    """The fully-resolved coordinates of a single computed graph node instance.

    A ``ComputeRequest`` resolves to a *sequence* of these (one per period window in its range);
    each one addresses exactly one logical slot via :attr:`cache_key`.
    """

    computed_node_class_name: str
    scope_name: str
    subject_kind: str
    subject_key: str
    time_granularity: TimeGranularity | str
    local_period_start: datetime
    local_period_end: datetime
    day_classif: str = 'all'
    hour_classif: str = 'all'

    @property
    def cache_key(self) -> str:
        """The canonical de-versioned slot id for this identity."""
        return build_slot_key(
            computed_node_class_name=self.computed_node_class_name,
            scope_name=self.scope_name,
            subject_kind=self.subject_kind,
            subject_key=self.subject_key,
            time_granularity=self.time_granularity,
            local_period_start=self.local_period_start,
            day_classif=self.day_classif,
            hour_classif=self.hour_classif,
        )
