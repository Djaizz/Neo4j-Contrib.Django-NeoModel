"""Shared monthly-from-daily rollup dependency helpers for computed graph nodes."""


from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, LiteralString

from agent_neo.analytical_product.identity import AnalyticalProductIdentity
from agent_neo.analytical_product.request import AnalyticalProductRequest
from agent_neo.util.datetime import TemporalGranularity, period_windows_for_range


__all__: tuple[LiteralString, ...] = (
    'collect_daily_dep_instances_for_monthly_identity',
    'prefetch_daily_instances_by_cache_key',
)


def prefetch_daily_instances_by_cache_key(
    *,
    ensure_instances: Callable[[AnalyticalProductRequest], Iterable[Any]],
    request: AnalyticalProductRequest,
) -> dict[str, Any]:
    """Ensure daily computed-node instances for the same scope/range; index by ``cache_key``."""
    daily_request = AnalyticalProductRequest(
        subject_kind=request.subject_kind,
        subject_key=request.subject_key,
        temporal_granularity=TemporalGranularity.DAILY,
        local_period_start=request.local_period_start,
        local_period_end=request.local_period_end,
        day_classif=request.day_classif,
        hour_classif=request.hour_classif,
        freshness=request.freshness,
        concept_selection=request.concept_selection,
    )
    return {
        instance.cache_key: instance
        for instance in ensure_instances(daily_request)
    }


def collect_daily_dep_instances_for_monthly_identity(
    *,
    slot_identity: AnalyticalProductIdentity,
    daily_instances_by_cache_key: dict[str, Any],
) -> list[Any]:
    """Return persisted daily instances that roll up into one monthly slot identity."""
    daily_windows = period_windows_for_range(
        from_datetime=slot_identity.local_period_start,
        to_datetime=slot_identity.local_period_end,
        temporal_granularity=TemporalGranularity.DAILY,
    )
    daily_dep_instances: list[Any] = []
    for window_start, window_end in daily_windows:
        daily_identity = AnalyticalProductIdentity(
            computed_node_class_name=slot_identity.computed_node_class_name,
            scope_name=slot_identity.scope_name,
            subject_kind=slot_identity.subject_kind,
            subject_key=slot_identity.subject_key,
            temporal_granularity=TemporalGranularity.DAILY,
            local_period_start=window_start,
            local_period_end=window_end,
            day_classif=slot_identity.day_classif,
            hour_classif=slot_identity.hour_classif,
        )
        daily_instance = daily_instances_by_cache_key.get(daily_identity.cache_key)
        if daily_instance is not None:
            daily_dep_instances.append(daily_instance)
    return daily_dep_instances
