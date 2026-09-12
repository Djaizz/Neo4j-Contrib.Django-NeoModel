"""Product layer: Concept / Ask / Identity / Instance / Refuse.

Playground stub — no persistence, no force-redo knob.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


__all__ = (
    'Ask',
    'Concept',
    'Identity',
    'Instance',
    'LifecycleStatus',
    'Refuse',
    'RefuseReason',
)


class LifecycleStatus(StrEnum):
    OFFICIAL = 'official'
    PROVISIONAL = 'provisional'
    RETIRED = 'retired'


class RefuseReason(StrEnum):
    """Typed refusal — more valuable than a wrong number."""

    ILL_TYPED_ROLL = 'ill_typed_roll'
    INCOMPLETE_PARTITION = 'incomplete_partition'
    IMMATURE_WINDOW = 'immature_window'
    STALE = 'stale'
    NO_MERGEABLE_ACCUMULATOR = 'no_mergeable_accumulator'
    NONLINEAR_SCALE_OVER_WINDOW = 'nonlinear_scale_over_window'
    AUTHORITY = 'authority'
    UNSUPPORTED_COMPOSITION = 'unsupported_composition'


@dataclass(frozen=True, slots=True)
class Refuse:
    """First-class result when an op cannot lawfully proceed."""

    reason: RefuseReason
    detail: str = ''
    context: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Concept:
    """Design-level product meaning (recipe today; term later).

    Dependencies are declared strings in this sketch. A future term language
    would derive them from free variables instead.
    """

    name: str
    layer: str
    depends_on: tuple[str, ...] = ()
    lifecycle: LifecycleStatus = LifecycleStatus.OFFICIAL


@dataclass(frozen=True, slots=True)
class Ask:
    """Canonical ask — no force-redo / recompute knob.

    Invalidation is only via lineage + Gate (maturity / freshness).
    Policy *values* (staleness bound, maturity lag) are slots for domain packs.
    """

    concept_name: str
    scope_name: str
    subject_kind: str
    subject_key: str
    temporal_granularity: str
    local_period_start: str | None = None
    local_period_end: str | None = None
    classifications: Mapping[str, str] = field(default_factory=dict)
    max_staleness_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class Identity:
    """Fully resolved slot coordinates (de-versioned cache key analogue)."""

    concept_name: str
    scope_name: str
    subject_kind: str
    subject_key: str
    temporal_granularity: str
    period_anchor: str
    classifications: Mapping[str, str] = field(default_factory=dict)

    @property
    def cache_key(self) -> str:
        classif_suffix = ''.join(
            f'|{key}={value}' for key, value in sorted(self.classifications.items())
        )
        return (
            f'{self.concept_name}|{self.scope_name}|'
            f'{self.subject_kind}={self.subject_key}|'
            f'{self.temporal_granularity}|{self.period_anchor}'
            f'{classif_suffix}'
        )


@dataclass(frozen=True, slots=True)
class Instance:
    """Computed product at an Identity — payload + gate metadata."""

    identity: Identity
    payload: Mapping[str, Any]
    lifecycle: LifecycleStatus = LifecycleStatus.OFFICIAL
    needs_redo: bool = False
    lineage: tuple[str, ...] = ()
