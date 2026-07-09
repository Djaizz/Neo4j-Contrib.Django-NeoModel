"""Facility-local hour/day classification for analytical period rollups (agent_neo)."""


from __future__ import annotations

from datetime import date, datetime
from typing import Any, Final, LiteralString

from agent_neo.util.datetime import TimeGranularity


__all__: tuple[LiteralString, ...] = (
    'DAILY_HOUR_SLICES',
    'DAY_SLICE_ALL',
    'DAY_SLICE_HOLIDAY',
    'DAY_SLICE_NON_HOLIDAY',
    'DAY_SLICE_WEEKDAY',
    'DAY_SLICE_WEEKEND',
    'HOUR_SLICE_ALL',
    'HOUR_SLICE_FACILITY_NON_OPERATING',
    'HOUR_SLICE_FACILITY_OPERATING',
    'MONTHLY_DAY_SLICES',
    'classify_day',
    'classify_hour',
    'default_day_slice_for_granularity',
    'default_hour_slice_for_granularity',
    'facility_operating_hour_bounds',
    'hour_slices_for_daily_rollup',
    'day_slices_for_weekly_monthly_rollup',
    'filter_rollups_by_day_slice',
    'hour_matches_daily_rollup_boundary',
    'parse_occupied_window_label',
    'validate_day_slice',
    'validate_hour_slice',
)


HOUR_SLICE_ALL: Final[LiteralString] = 'all'
HOUR_SLICE_FACILITY_OPERATING: Final[LiteralString] = 'facility_operating'
HOUR_SLICE_FACILITY_NON_OPERATING: Final[LiteralString] = 'facility_non_operating'

DAY_SLICE_ALL: Final[LiteralString] = 'all'
DAY_SLICE_WEEKDAY: Final[LiteralString] = 'weekday'
DAY_SLICE_WEEKEND: Final[LiteralString] = 'weekend'
DAY_SLICE_HOLIDAY: Final[LiteralString] = 'holiday'
DAY_SLICE_NON_HOLIDAY: Final[LiteralString] = 'non_holiday'

_HOUR_SLICES: Final[frozenset[str]] = frozenset({
    HOUR_SLICE_ALL,
    HOUR_SLICE_FACILITY_OPERATING,
    HOUR_SLICE_FACILITY_NON_OPERATING,
})
_DAY_SLICES: Final[frozenset[str]] = frozenset({
    DAY_SLICE_ALL,
    DAY_SLICE_WEEKDAY,
    DAY_SLICE_WEEKEND,
    DAY_SLICE_HOLIDAY,
    DAY_SLICE_NON_HOLIDAY,
})

DAILY_HOUR_SLICES: Final[tuple[str, ...]] = (
    HOUR_SLICE_ALL,
    HOUR_SLICE_FACILITY_OPERATING,
    HOUR_SLICE_FACILITY_NON_OPERATING,
)
MONTHLY_DAY_SLICES: Final[tuple[str, ...]] = (
    DAY_SLICE_ALL,
    DAY_SLICE_WEEKDAY,
    DAY_SLICE_WEEKEND,
    DAY_SLICE_HOLIDAY,
    DAY_SLICE_NON_HOLIDAY,
)


def validate_hour_slice(hour_slice: str) -> str:
    if hour_slice not in _HOUR_SLICES:
        raise ValueError(f'hour_slice must be one of {sorted(_HOUR_SLICES)}; got {hour_slice!r}')
    return hour_slice


def validate_day_slice(day_slice: str) -> str:
    if day_slice not in _DAY_SLICES:
        raise ValueError(f'day_slice must be one of {sorted(_DAY_SLICES)}; got {day_slice!r}')
    return day_slice


def default_hour_slice_for_granularity(time_granularity: str) -> str:
    if time_granularity == TimeGranularity.HOURLY:
        return HOUR_SLICE_ALL
    return HOUR_SLICE_ALL


def default_day_slice_for_granularity(time_granularity: str) -> str:
    return DAY_SLICE_ALL


def hour_slices_for_daily_rollup() -> tuple[str, ...]:
    return DAILY_HOUR_SLICES


def day_slices_for_weekly_monthly_rollup() -> tuple[str, ...]:
    return MONTHLY_DAY_SLICES


def parse_occupied_window_label(occupied_window_label: str) -> tuple[int, int]:
    """Return whole-hour bounds ``[start_hour_inclusive, end_hour_exclusive)`` from a label like ``06:00-17:30``."""
    start_label, end_label = occupied_window_label.split('-', maxsplit=1)
    start_hour = int(start_label.split(':', maxsplit=1)[0])
    end_parts = end_label.split(':', maxsplit=1)
    end_hour = int(end_parts[0])
    end_minute = int(end_parts[1]) if len(end_parts) > 1 else 0
    end_hour_exclusive = end_hour + (1 if end_minute > 0 else 0)
    if end_hour_exclusive <= start_hour:
        end_hour_exclusive = min(24, start_hour + 1)
    return start_hour, end_hour_exclusive


def facility_operating_hour_bounds(
    *,
    occupied_window_label: str = '06:00-17:30',
) -> tuple[int, int]:
    return parse_occupied_window_label(occupied_window_label)


def classify_hour(
    local_dt: datetime,
    *,
    hour_slice: str,
    start_hour_inclusive: int,
    end_hour_exclusive: int,
) -> bool:
    hour_slice = validate_hour_slice(hour_slice)
    if hour_slice == HOUR_SLICE_ALL:
        return True
    hour = local_dt.hour
    is_operating = start_hour_inclusive <= hour < end_hour_exclusive
    if hour_slice == HOUR_SLICE_FACILITY_OPERATING:
        return is_operating
    return not is_operating


def classify_day(
    local_date: date,
    *,
    day_slice: str,
    holidays_iso_dates: set[str],
) -> bool:
    day_slice = validate_day_slice(day_slice)
    if day_slice == DAY_SLICE_ALL:
        return True
    iso = local_date.isoformat()
    is_holiday = iso in holidays_iso_dates
    weekday = local_date.weekday()
    if day_slice == DAY_SLICE_HOLIDAY:
        return is_holiday
    if day_slice == DAY_SLICE_NON_HOLIDAY:
        return not is_holiday
    if day_slice == DAY_SLICE_WEEKEND:
        return weekday >= 5
    if day_slice == DAY_SLICE_WEEKDAY:
        return weekday < 5 and not is_holiday
    return False


def filter_rollups_by_day_slice(
    rollups: list[dict[str, Any]],
    *,
    day_slice: str,
    holidays_iso_dates: set[str],
    parse_local_period_start: Any,
) -> list[dict[str, Any]]:
    """Keep daily (or finer) rollup dicts whose ``local_period_start`` matches ``day_slice``."""
    day_slice = validate_day_slice(day_slice)
    if day_slice == DAY_SLICE_ALL:
        return rollups
    return [
        rollup
        for rollup in rollups
        if classify_day(
            parse_local_period_start(rollup['local_period_start']).date(),
            day_slice=day_slice,
            holidays_iso_dates=holidays_iso_dates,
        )
    ]


def hour_matches_daily_rollup_boundary(
    local_hour_start: datetime,
    day_class: str,
    *,
    holidays_iso_dates: set[str],
) -> bool:
    """Map compat hour-of-day profile ``day_class`` to ``classify_day`` rules."""
    if day_class == 'all':
        return True
    if day_class == 'weekday':
        return classify_day(local_hour_start.date(), day_slice=DAY_SLICE_WEEKDAY, holidays_iso_dates=holidays_iso_dates)
    if day_class == 'weekend':
        return classify_day(local_hour_start.date(), day_slice=DAY_SLICE_WEEKEND, holidays_iso_dates=holidays_iso_dates)
    if day_class == 'holiday':
        return classify_day(local_hour_start.date(), day_slice=DAY_SLICE_HOLIDAY, holidays_iso_dates=holidays_iso_dates)
    if day_class == 'non_holiday':
        return classify_day(local_hour_start.date(), day_slice=DAY_SLICE_NON_HOLIDAY, holidays_iso_dates=holidays_iso_dates)
    raise ValueError(
        'day_class must be one of all, weekday, weekend, holiday, non_holiday',
    )
