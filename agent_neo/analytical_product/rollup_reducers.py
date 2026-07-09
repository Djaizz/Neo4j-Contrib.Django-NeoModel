"""Pure domain reducers for energy derivative MetricSets."""


from __future__ import annotations

from statistics import median
from typing import Any, LiteralString

from agent_neo.analytical_product.energy_window_helpers import fraction_of_window_occupied


__all__: tuple[LiteralString, ...] = (
    'kwh_from_consumption_payload',
    'sum_kwh_values_or_none',
    'compute_energy_cost_payload',
    'compute_energy_co2_payload',
    'compute_building_eui_payload',
    'compute_occupancy_split_payload',
    'compute_spike_finding_payload',
    'compute_hour_of_day_profile_rows',
    'compute_meter_health_payload',
)


def kwh_from_consumption_payload(consumption_payload: dict[str, Any]) -> float:
    for key in ('kwh', 'kwh_total', 'combined_kwh_total'):
        value = consumption_payload.get(key)
        if value is not None:
            return float(value)
    raise KeyError('consumption payload missing kwh field')


def sum_kwh_values_or_none(kwh_values: list[float | None]) -> float | None:
    numeric_values = [float(value) for value in kwh_values if value is not None]
    if not numeric_values:
        return None
    return round(sum(numeric_values), 4)


def compute_energy_cost_payload(
    *,
    kwh: float,
    tariff_rate_per_kwh: float,
    currency_code: str,
    currency_symbol: str,
    tariff_label: str,
    source_cache_key: str,
) -> dict[str, Any]:
    return {
        'kwh': float(kwh),
        'tariff_rate_per_kwh': tariff_rate_per_kwh,
        'cost_currency_amount': round(float(kwh) * tariff_rate_per_kwh, 4),
        'currency_code': currency_code,
        'currency_symbol': currency_symbol,
        'tariff_label': tariff_label,
        'calculation_method': 'kwh_times_facility_tariff',
        'source_rollup_cache_key': source_cache_key,
    }


def compute_energy_co2_payload(
    *,
    kwh: float,
    emission_factor_kg_per_kwh: float,
    emission_factor_source_label: str,
    source_cache_key: str,
) -> dict[str, Any]:
    return {
        'kwh': float(kwh),
        'emission_factor_kg_per_kwh': emission_factor_kg_per_kwh,
        'co2_kg': round(float(kwh) * emission_factor_kg_per_kwh, 4),
        'emission_factor_source_label': emission_factor_source_label,
        'calculation_method': 'kwh_times_facility_emission_factor',
        'source_rollup_cache_key': source_cache_key,
    }


def compute_building_eui_payload(
    *,
    kwh: float,
    floor_area_ft2: float,
    source_cache_key: str,
) -> dict[str, Any]:
    eui_kwh_per_ft2 = round(float(kwh) / floor_area_ft2, 6) if floor_area_ft2 else 0.0
    return {
        'kwh': float(kwh),
        'floor_area_ft2': floor_area_ft2,
        'eui_kwh_per_ft2': eui_kwh_per_ft2,
        'calculation_method': 'kwh_divided_by_facility_floor_area',
        'source_rollup_cache_key': source_cache_key,
    }


def compute_occupancy_split_payload(
    *,
    kwh_total: float,
    local_period_start: Any,
    local_period_end: Any,
    occupied_start_hour: float,
    occupied_end_hour: float,
    occupied_window_label: str,
    holidays_iso_dates: set[str],
    source_cache_key: str,
) -> dict[str, Any]:
    occupied_hours, unoccupied_hours = fraction_of_window_occupied(
        local_period_start=local_period_start,
        local_period_end=local_period_end,
        occupied_start_hour=occupied_start_hour,
        occupied_end_hour=occupied_end_hour,
        holidays_iso_dates=holidays_iso_dates,
        weekend_weekday_indices_0_mon={5, 6},
    )
    total_hours = occupied_hours + unoccupied_hours
    occupied_fraction = occupied_hours / total_hours if total_hours else 0.0
    unoccupied_fraction = 1.0 - occupied_fraction if total_hours else 0.0
    return {
        'kwh_total': float(kwh_total),
        'occupied_kwh': round(float(kwh_total) * occupied_fraction, 4),
        'unoccupied_kwh': round(float(kwh_total) * unoccupied_fraction, 4),
        'occupied_fraction': round(occupied_fraction, 4),
        'unoccupied_fraction': round(unoccupied_fraction, 4),
        'occupied_window_label': occupied_window_label,
        'occupied_hour_count': round(occupied_hours, 4),
        'unoccupied_hour_count': round(unoccupied_hours, 4),
        'calculation_method': 'period_kwh_prorated_by_facility_schedule_hours',
        'source_rollup_cache_key': source_cache_key,
    }


def compute_spike_finding_payload(
    *,
    source_rollups: list[dict[str, Any]],
    target_rollup: dict[str, Any],
    time_granularity: str,
) -> dict[str, Any]:
    observed_kwh_by_period_start = {
        source_rollup['local_period_start']: kwh_from_consumption_payload(source_rollup)
        for source_rollup in source_rollups
    }
    observed_kwh = observed_kwh_by_period_start[target_rollup['local_period_start']]
    baseline_values = [
        baseline_kwh
        for baseline_period_start, baseline_kwh in observed_kwh_by_period_start.items()
        if baseline_period_start != target_rollup['local_period_start']
    ]
    median_baseline_kwh = float(median(baseline_values)) if baseline_values else observed_kwh
    residual_kwh = observed_kwh - median_baseline_kwh
    absolute_deviations = [abs(value - median_baseline_kwh) for value in baseline_values]
    median_absolute_deviation_kwh = float(median(absolute_deviations)) if absolute_deviations else None
    multiplier = (
        residual_kwh / median_absolute_deviation_kwh
        if median_absolute_deviation_kwh
        else None
    )
    local_period_start = target_rollup['local_period_start']
    weekday_index_0_mon = None
    if time_granularity == 'daily' and hasattr(local_period_start, 'weekday'):
        weekday_index_0_mon = local_period_start.weekday()
    return {
        'weekday_index_0_mon': weekday_index_0_mon,
        'observed_kwh': observed_kwh,
        'median_baseline_kwh': median_baseline_kwh,
        'residual_kwh': round(residual_kwh, 4),
        'median_absolute_deviation_kwh': median_absolute_deviation_kwh,
        'median_absolute_deviation_multiplier': multiplier,
        'is_atypical_spike': bool(multiplier is not None and multiplier >= 3 and residual_kwh > 0),
        'is_high_vs_baseline': residual_kwh > 0,
        'baseline_start_period': source_rollups[0]['local_period_start'] if source_rollups else None,
        'baseline_end_period': source_rollups[-1]['local_period_end'] if source_rollups else None,
        'baseline_method_label': 'leave_one_out_median',
        'detection_method': 'period_median_plus_mad',
        'source_rollup_cache_key': target_rollup.get('cache_key'),
    }


def compute_hour_of_day_profile_rows(
    *,
    hourly_consumption_rows: list[dict[str, Any]],
    day_class: str,
) -> list[dict[str, Any]]:
    kwh_values_by_hour_of_day: dict[int, list[float]] = {hour: [] for hour in range(24)}
    for hourly_row in hourly_consumption_rows:
        local_period_start = hourly_row['local_period_start']
        if day_class != 'all' and hasattr(local_period_start, 'weekday'):
            if day_class == 'weekday' and local_period_start.weekday() >= 5:
                continue
            if day_class == 'weekend' and local_period_start.weekday() < 5:
                continue
        kwh_values_by_hour_of_day[local_period_start.hour].append(kwh_from_consumption_payload(hourly_row))

    profile_rows: list[dict[str, Any]] = []
    for hour_of_day_0_23 in range(24):
        kwh_values = kwh_values_by_hour_of_day[hour_of_day_0_23]
        profile_rows.append({
            'hour_of_day_0_23': hour_of_day_0_23,
            'sample_day_count': len(kwh_values),
            'average_kwh': round(sum(kwh_values) / len(kwh_values), 4) if kwh_values else 0.0,
            'median_kwh': round(float(median(kwh_values)), 4) if kwh_values else None,
            'min_kwh': round(min(kwh_values), 4) if kwh_values else None,
            'max_kwh': round(max(kwh_values), 4) if kwh_values else None,
            'p95_kwh': _percentile(kwh_values, 0.95),
            'calculation_method': 'hourly_source_rollups_grouped_by_local_hour',
            'source_rollup_count': len(hourly_consumption_rows),
        })
    return profile_rows


def compute_meter_health_payload(
    *,
    meter_consumption_payload: dict[str, Any],
    expected_hour_count: int,
) -> dict[str, Any]:
    sample_count = int(
        meter_consumption_payload.get('sample_count')
        or meter_consumption_payload.get('numeric_sample_count')
        or 0
    )
    numeric_sample_count = int(meter_consumption_payload.get('numeric_sample_count') or sample_count)
    expected_minutes = max(1, expected_hour_count * 60)
    coverage_ratio = round(min(sample_count / expected_minutes, 1.0), 4)
    hours_with_samples = min(expected_hour_count, sample_count)
    health_status = 'healthy'
    health_label = 'Healthy sampling'
    if coverage_ratio < 0.5:
        health_status = 'degraded'
        health_label = 'Low coverage'
    if coverage_ratio < 0.1:
        health_status = 'missing'
        health_label = 'Missing or stale data'
    return {
        'expected_hour_count': expected_hour_count,
        'hours_with_samples': hours_with_samples,
        'sample_count': sample_count,
        'numeric_sample_count': numeric_sample_count,
        'coverage_ratio': coverage_ratio,
        'longest_gap_hours': None,
        'register_increased': None,
        'last_value_string': None,
        'last_seen_local_iso': None,
        'health_status': health_status,
        'health_label': health_label,
        'calculation_method': 'meter_consumption_coverage_diagnostics',
        'source_rollup_cache_key': meter_consumption_payload.get('cache_key'),
    }


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    index = int(round((len(sorted_values) - 1) * quantile))
    return round(sorted_values[index], 4)
