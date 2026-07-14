"""The canonical :class:`AnalyticalProductRequest` for the unified ``.get(request)`` path.

An ``AnalyticalProductRequest`` is the *only* way to ask for a computed graph node. It carries identity
coordinates (scope, subject, period bounds, temporal_granularity, day/hour classif, design node
selection) plus serving-side time-freshness (distinct from lineage ``needs_redo``). Given the
scope timezone it resolves to a maturity-clamped sequence of :class:`AnalyticalProductIdentity` slots.

Rationale: no force-redo/recompute knob — invalidation is only via lineage/freshness gates
on ensure-on-read.

Window resolution and maturity clamping live in :mod:`agent_neo.util.datetime`; this module
composes them into :class:`AnalyticalProductRequest`.
"""


from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from typing import LiteralString

from agent_neo.util.datetime import (
    TELEMETRY_LAG_MATURITY_MINUTES,
    TemporalGranularity,
    VALID_TEMPORAL_GRANULARITIES,
    period_windows_for_range,
    resolve_window_for_temporal_granularity,
)

from .freshness import FreshnessPolicy, DEFAULT_FRESHNESS_POLICY
from .identity import AnalyticalProductIdentity


__all__: tuple[LiteralString, ...] = ('AnalyticalProductRequest',)


@dataclass(frozen=True, slots=True)
class AnalyticalProductRequest:
    """A single, canonical ask for a computed graph node (the only entry-point argument).

    ``scope_name`` is usually taken from the active :class:`~agent_neo.analytical_product.scope.AnalyticalProductScope`
    rather than passed by callers. ``subject_kind``/``subject_key`` name the topology subject
    (meter, floor, building, whole_site, zone, plant, asset, …). Period bounds are scope-local
    and may be open-ended; ``None`` bounds resolve to the latest mature period at
    ``temporal_granularity``. ``concept_selection`` is ``'current'`` for normal reads — a sentinel
    meaning "whichever design node is currently in force, ``official`` or ``provisional``" — or
    a concrete ``concept_key`` to pin a historical (possibly ``retired``) computation for
    audit/replay.
    """

    subject_kind: str
    subject_key: str
    temporal_granularity: TemporalGranularity | str = TemporalGranularity.DAILY
    local_period_start: datetime | str | None = None
    local_period_end: datetime | str | None = None
    day_classif: str = 'all'
    hour_classif: str = 'all'
    freshness: FreshnessPolicy = field(default_factory=lambda: DEFAULT_FRESHNESS_POLICY)
    concept_selection: str = 'current'  # TODO: review necessity

    def __post_init__(self) -> None:
        if self.temporal_granularity not in VALID_TEMPORAL_GRANULARITIES:
            raise ValueError(
                f'temporal_granularity must be one of {sorted(VALID_TEMPORAL_GRANULARITIES)}; got {self.temporal_granularity!r}',
            )

    def resolve_identities(
        self,
        *,
        analytical_product_class_name: str,
        scope_name: str,
        local_tz: tzinfo,
        now: datetime | None = None,
        maturity_minutes: int = TELEMETRY_LAG_MATURITY_MINUTES,
    ) -> list[AnalyticalProductIdentity]:
        """Resolve this request to its maturity-clamped sequence of computed-node identities.

        Maturity is a *produceability* gate — may we compute an open-ended window yet? — not
        the serving-side age gate in :class:`FreshnessPolicy`. Open-ended / over-reaching bounds
        clamp to the latest mature period; older explicit bounds pass through. One identity per
        aligned period in the resolved range.
        """
        local_from, local_to_exclusive = resolve_window_for_temporal_granularity(
            self.local_period_start,
            self.local_period_end,
            temporal_granularity=self.temporal_granularity,
            local_tz=local_tz,
            now=now,
            maturity_minutes=maturity_minutes,
        )
        return [
            AnalyticalProductIdentity(
                analytical_product_class_name=analytical_product_class_name,
                scope_name=scope_name,
                subject_kind=self.subject_kind,
                subject_key=self.subject_key,
                temporal_granularity=self.temporal_granularity,
                local_period_start=window_start,
                local_period_end=window_end,
                day_classif=self.day_classif,
                hour_classif=self.hour_classif,
            )
            for window_start, window_end in period_windows_for_range(
                from_datetime=local_from,
                to_datetime=local_to_exclusive,
                temporal_granularity=self.temporal_granularity,
            )
        ]
