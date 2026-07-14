"""Tests for monthly-from-daily rollup dependency helpers."""


from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agent_neo.analytical_product.identity import AnalyticalProductIdentity
from agent_neo.analytical_product.monthly_rollup_deps import (
    collect_daily_dep_instances_for_monthly_identity,
    prefetch_daily_instances_by_cache_key,
)
from agent_neo.analytical_product.request import AnalyticalProductRequest
from agent_neo.util.datetime import TemporalGranularity


@dataclass
class _StubInstance:
    cache_key: str


def test_prefetch_daily_instances_by_cache_key_builds_daily_request() -> None:
    received_requests: list[AnalyticalProductRequest] = []

    def ensure_instances(compute_request: AnalyticalProductRequest) -> list[_StubInstance]:
        received_requests.append(compute_request)
        return [
            _StubInstance(cache_key='daily-a'),
            _StubInstance(cache_key='daily-b'),
        ]

    parent_request = AnalyticalProductRequest(
        subject_kind='building',
        subject_key='9A',
        temporal_granularity=TemporalGranularity.MONTHLY,
        local_period_start=datetime(2026, 5, 1),
        local_period_end=datetime(2026, 6, 1),
        day_classif='weekday',
        hour_classif='facility_operating',
    )
    indexed_instances = prefetch_daily_instances_by_cache_key(
        ensure_instances=ensure_instances,
        request=parent_request,
    )

    assert len(received_requests) == 1
    daily_request = received_requests[0]
    assert daily_request.temporal_granularity == TemporalGranularity.DAILY
    assert daily_request.subject_kind == 'building'
    assert daily_request.subject_key == '9A'
    assert daily_request.day_classif == 'weekday'
    assert daily_request.hour_classif == 'facility_operating'
    assert indexed_instances == {
        'daily-a': _StubInstance(cache_key='daily-a'),
        'daily-b': _StubInstance(cache_key='daily-b'),
    }


def test_collect_daily_dep_instances_for_monthly_identity_filters_missing() -> None:
    monthly_identity = AnalyticalProductIdentity(
        computed_node_class_name='HVACEquipmentTemperatureComfort',
        scope_name='nvidia-voyager',
        subject_kind='hvac_equipment',
        subject_key='AHU-1',
        temporal_granularity=TemporalGranularity.MONTHLY,
        local_period_start=datetime(2026, 5, 1),
        local_period_end=datetime(2026, 5, 4),
    )
    may_first_identity = AnalyticalProductIdentity(
        computed_node_class_name=monthly_identity.computed_node_class_name,
        scope_name=monthly_identity.scope_name,
        subject_kind=monthly_identity.subject_kind,
        subject_key=monthly_identity.subject_key,
        temporal_granularity=TemporalGranularity.DAILY,
        local_period_start=datetime(2026, 5, 1),
        local_period_end=datetime(2026, 5, 2),
    )
    may_third_identity = AnalyticalProductIdentity(
        computed_node_class_name=monthly_identity.computed_node_class_name,
        scope_name=monthly_identity.scope_name,
        subject_kind=monthly_identity.subject_kind,
        subject_key=monthly_identity.subject_key,
        temporal_granularity=TemporalGranularity.DAILY,
        local_period_start=datetime(2026, 5, 3),
        local_period_end=datetime(2026, 5, 4),
    )
    daily_instances_by_cache_key = {
        may_first_identity.cache_key: _StubInstance(cache_key=may_first_identity.cache_key),
        may_third_identity.cache_key: _StubInstance(cache_key=may_third_identity.cache_key),
    }

    daily_dep_instances = collect_daily_dep_instances_for_monthly_identity(
        slot_identity=monthly_identity,
        daily_instances_by_cache_key=daily_instances_by_cache_key,
    )

    assert len(daily_dep_instances) == 2
    assert daily_dep_instances[0].cache_key == may_first_identity.cache_key
    assert daily_dep_instances[1].cache_key == may_third_identity.cache_key
