"""The canonical :class:`ComputeRequest` for the unified ``.get(request)`` path (E4/E5/E7).

A ``ComputeRequest`` is the *only* way to ask for an analytical product. It carries identity
coordinates (facility is implicit, subject, period bounds, time_granularity, day/hour
classif, Concept selection) plus serving-side time-freshness (distinct from lineage
``needs_redo``). Given the facility timezone it resolves to a maturity-clamped sequence
of :class:`ComputedSlotIdentity` slots.

Rationale (``OP : ANALYTICAL-NO-FORCE-REDO-ARGS``): no force-redo/recompute knob — invalidation
is only via lineage/freshness gates on ensure-on-read.

Design (DjangoNeoModel-GraphDB) — bidirectional with:
  dana/ontologist/odb-governance-harness/necessary-and-sufficient-design/concretized/DjangoNeoModel-GraphDB/
    identity-request-and-probe.md
    ensure-path-and-lifecycle.md
    IMPLEMENTATION-CROSSWALK.md

Also: ``abstract/GET-ENSURE-PATH.md``, ``abstract/FRESHNESS-AND-MATURITY.md``,
``!-REQUIREMENTS/PRESENT/ANALYTICAL-FRESHNESS.md``.

Window resolution and maturity clamping live in :mod:`agent_neo.time.periods`; this
module composes them into :class:`ComputeRequest`.
"""


from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from typing import LiteralString

from agent_neo.time.periods import (
    TELEMETRY_LAG_MATURITY_MINUTES,
    TimeGranularity,
    VALID_TIME_GRANULARITIES,
    period_windows_for_range,
    resolve_window_for_time_granularity,
)

from .freshness import FreshnessPolicy, DEFAULT_FRESHNESS_POLICY
from .identity import ComputedSlotIdentity


__all__: tuple[LiteralString, ...] = ('ComputeRequest',)


@dataclass(frozen=True, slots=True)
class ComputeRequest:
    """A single, canonical ask for an analytical product (the only entry-point argument).

    ``scope_name`` is usually taken from the active :class:`~scope.scope.ComputeScope`
    rather than passed by callers. ``subject_kind``/``subject_key`` name the topology subject
    (meter, floor, building, whole_site, zone, plant, asset, …). Period bounds are facility-local
    and may be open-ended; ``None`` bounds resolve to the latest mature period (E7) at
    ``time_granularity``. ``concept_selection`` is ``'current'`` for normal reads — a sentinel meaning
    "whichever Concept is currently in force, ``official`` or ``provisional``" — or a concrete
    ``concept_key`` to pin a historical (possibly ``retired``) computation for audit/replay.
    """

    subject_kind: str
    subject_key: str
    time_granularity: TimeGranularity | str = TimeGranularity.DAILY
    local_period_start: datetime | str | None = None
    local_period_end: datetime | str | None = None
    day_classif: str = 'all'
    hour_classif: str = 'all'
    freshness: FreshnessPolicy = field(default_factory=lambda: DEFAULT_FRESHNESS_POLICY)
    concept_selection: str = 'current'  # TODO: review necessity

    def __post_init__(self) -> None:
        if self.time_granularity not in VALID_TIME_GRANULARITIES:
            raise ValueError(
                f'time_granularity must be one of {sorted(VALID_TIME_GRANULARITIES)}; got {self.time_granularity!r}',
            )

    def resolve_identities(
        self,
        *,
        computed_node_class_name: str,
        scope_name: str,
        local_tz: tzinfo,
        now: datetime | None = None,
        maturity_minutes: int = TELEMETRY_LAG_MATURITY_MINUTES,
    ) -> list[ComputedSlotIdentity]:
        """Resolve this request to its maturity-clamped sequence of product-instance identities.

        Maturity (``DATETIME : MATURITY-DEF`` / E7) is a *produceability* gate — may we compute
        an open-ended window yet? — not the serving-side age gate in :class:`FreshnessPolicy`.
        Open-ended / over-reaching bounds clamp to the latest mature period; older explicit
        bounds pass through. One identity per aligned period in the resolved range.
        """
        local_from, local_to_exclusive = resolve_window_for_time_granularity(
            self.local_period_start,
            self.local_period_end,
            time_granularity=self.time_granularity,
            local_tz=local_tz,
            now=now,
            maturity_minutes=maturity_minutes,
        )
        return [
            ComputedSlotIdentity(
                computed_node_class_name=computed_node_class_name,
                scope_name=scope_name,
                subject_kind=self.subject_kind,
                subject_key=self.subject_key,
                time_granularity=self.time_granularity,
                local_period_start=window_start,
                local_period_end=window_end,
                day_classif=self.day_classif,
                hour_classif=self.hour_classif,
            )
            for window_start, window_end in period_windows_for_range(
                from_datetime=local_from,
                to_datetime=local_to_exclusive,
                time_granularity=self.time_granularity,
            )
        ]
