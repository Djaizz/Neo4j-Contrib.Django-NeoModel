"""Deterministic helpers for weekday baselines and spike thresholds (no I/O)."""


from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Final, Literal, LiteralString

from agent_neo.analytical_product.time_classification import (
    DAY_SLICE_WEEKDAY,
    DAY_SLICE_WEEKEND,
    classify_day,
)


SpikeBaselineDayClass = Literal['weekday', 'weekend']


SUSPICIOUS_RESIDUAL_KWH_THRESHOLD: Final[float] = 100_000.0


__all__: tuple[LiteralString, ...] = (
    'SUSPICIOUS_RESIDUAL_KWH_THRESHOLD',
    'SpikeBaselineDayClass',
    'build_contextual_baseline_by_day',
    'leave_one_out_weekday_weekend_mean_baseline',
    'mean_kwh_by_weekday_index_0_mon',
    'mean_of_floats',
    'median_absolute_deviation_around_median',
    'median_of_floats',
    'rank_weekday_indices_descending',
    'spike_baseline_day_class',
    'summarize_baseline_by_day_class',
    'weekday_is_in_top_consumption_tier',
)


def mean_of_floats(values: Sequence[float]) -> float:
    if not values:
        raise ValueError('mean_of_floats requires a non-empty sequence')
    return sum(float(value) for value in values) / len(values)


def median_of_floats(values: Sequence[float]) -> float:
    if not values:
        raise ValueError('median_of_floats requires a non-empty sequence')
    sorted_values = sorted(float(value) for value in values)
    middle_index = len(sorted_values) // 2
    if len(sorted_values) % 2 == 1:
        return sorted_values[middle_index]
    lower = sorted_values[middle_index - 1]
    upper = sorted_values[middle_index]
    return (lower + upper) / 2.0


def median_absolute_deviation_around_median(
    values: Sequence[float],
    median_value: float | None = None,
) -> float:
    if not values:
        raise ValueError('median_absolute_deviation_around_median requires a non-empty sequence')
    center = median_of_floats(values) if median_value is None else float(median_value)
    absolute_deviations = [abs(float(value) - center) for value in values]
    return median_of_floats(absolute_deviations)


def mean_kwh_by_weekday_index_0_mon(calendar_day_to_kwh: Mapping[date, float]) -> dict[int, float]:
    sums_by_weekday: dict[int, float] = defaultdict(float)
    counts_by_weekday: dict[int, int] = defaultdict(int)
    for calendar_day, kwh in calendar_day_to_kwh.items():
        weekday_index_0_mon = int(calendar_day.weekday())
        sums_by_weekday[weekday_index_0_mon] += float(kwh)
        counts_by_weekday[weekday_index_0_mon] += 1
    means: dict[int, float] = {}
    for weekday_index_0_mon, total_kwh in sums_by_weekday.items():
        day_count = counts_by_weekday[weekday_index_0_mon]
        if day_count:
            means[weekday_index_0_mon] = total_kwh / day_count
    return means


def rank_weekday_indices_descending(mean_by_weekday: Mapping[int, float]) -> list[int]:
    pairs = sorted(mean_by_weekday.items(), key=lambda item: item[1], reverse=True)
    return [weekday_index for weekday_index, _mean_kwh in pairs]


def spike_baseline_day_class(
    local_date: date,
    *,
    holidays_iso_dates: set[str],
) -> SpikeBaselineDayClass | None:
    if classify_day(local_date, day_slice=DAY_SLICE_WEEKDAY, holidays_iso_dates=holidays_iso_dates):
        return 'weekday'
    if classify_day(local_date, day_slice=DAY_SLICE_WEEKEND, holidays_iso_dates=holidays_iso_dates):
        return 'weekend'
    return None


def leave_one_out_weekday_weekend_mean_baseline(
    calendar_day_to_kwh: Mapping[date, float],
    target_day: date,
    *,
    holidays_iso_dates: set[str],
) -> tuple[float | None, list[float], SpikeBaselineDayClass | None]:
    target_class = spike_baseline_day_class(target_day, holidays_iso_dates=holidays_iso_dates)
    if target_class is None:
        return None, [], None
    peer_values = [
        float(kwh)
        for calendar_day, kwh in calendar_day_to_kwh.items()
        if calendar_day != target_day
        and spike_baseline_day_class(calendar_day, holidays_iso_dates=holidays_iso_dates) == target_class
    ]
    if not peer_values:
        return None, peer_values, target_class
    return mean_of_floats(peer_values), peer_values, target_class


def build_contextual_baseline_by_day(
    calendar_day_to_kwh: Mapping[date, float],
    *,
    holidays_iso_dates: set[str],
) -> dict[date, dict[str, float | SpikeBaselineDayClass | None]]:
    baseline_by_day: dict[date, dict[str, float | SpikeBaselineDayClass | None]] = {}
    for calendar_day, observed_kwh in calendar_day_to_kwh.items():
        baseline_kwh, _peers, day_class = leave_one_out_weekday_weekend_mean_baseline(
            calendar_day_to_kwh,
            calendar_day,
            holidays_iso_dates=holidays_iso_dates,
        )
        if day_class is None or baseline_kwh is None:
            baseline_by_day[calendar_day] = {
                'baseline_kwh': None,
                'extra_kwh': None,
                'baseline_day_class': None,
            }
            continue
        observed = float(observed_kwh)
        baseline_by_day[calendar_day] = {
            'baseline_kwh': float(baseline_kwh),
            'extra_kwh': observed - float(baseline_kwh),
            'baseline_day_class': day_class,
        }
    return baseline_by_day


def summarize_baseline_by_day_class(
    calendar_day_to_kwh: Mapping[date, float],
    baseline_by_day: Mapping[date, Mapping[str, float | SpikeBaselineDayClass | None]],
) -> list[dict[str, float | int | str]]:
    buckets: dict[SpikeBaselineDayClass, dict[str, float | int]] = {
        'weekday': {
            'day_count': 0,
            'observed_total': 0.0,
            'baseline_total': 0.0,
            'extra_total': 0.0,
        },
        'weekend': {
            'day_count': 0,
            'observed_total': 0.0,
            'baseline_total': 0.0,
            'extra_total': 0.0,
        },
    }
    for calendar_day, observed_kwh in calendar_day_to_kwh.items():
        metrics = baseline_by_day.get(calendar_day) or {}
        day_class = metrics.get('baseline_day_class')
        baseline_kwh = metrics.get('baseline_kwh')
        extra_kwh = metrics.get('extra_kwh')
        if day_class not in ('weekday', 'weekend') or baseline_kwh is None or extra_kwh is None:
            continue
        bucket = buckets[day_class]
        bucket['day_count'] = int(bucket['day_count']) + 1
        bucket['observed_total'] = float(bucket['observed_total']) + float(observed_kwh)
        bucket['baseline_total'] = float(bucket['baseline_total']) + float(baseline_kwh)
        bucket['extra_total'] = float(bucket['extra_total']) + float(extra_kwh)

    summaries: list[dict[str, float | int | str]] = []
    for day_class in ('weekday', 'weekend'):
        bucket = buckets[day_class]
        day_count = int(bucket['day_count'])
        if day_count <= 0:
            continue
        summaries.append(
            {
                'day_class': day_class,
                'day_count': day_count,
                'avg_observed_kwh': float(bucket['observed_total']) / day_count,
                'avg_baseline_kwh': float(bucket['baseline_total']) / day_count,
                'avg_extra_kwh': float(bucket['extra_total']) / day_count,
            }
        )
    return summaries


def weekday_is_in_top_consumption_tier(
    mean_by_weekday: Mapping[int, float],
    weekday_index_0_mon: int,
    tier_size: int = 2,
) -> bool:
    if weekday_index_0_mon not in mean_by_weekday:
        return False
    ranked = rank_weekday_indices_descending(mean_by_weekday)
    if not ranked:
        return False
    top_slice = ranked[: max(1, int(tier_size))]
    return weekday_index_0_mon in top_slice
