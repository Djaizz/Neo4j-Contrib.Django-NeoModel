"""Pure energy window and kWh aggregation helpers (no I/O)."""


from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, LiteralString

from agent_neo.util.datetime import TimeGranularity, period_windows_for_range


__all__: tuple[LiteralString, ...] = (
    'aggregate_kwh_from_power_readings',
    'aggregate_kwh_from_register_readings',
    'fraction_of_window_occupied',
    'period_windows_newest_first',
)


def period_windows_newest_first(
    *,
    from_datetime: datetime,
    to_datetime: datetime,
    time_granularity: str,
) -> list[tuple[datetime, datetime]]:
    """Same windows as :func:`period_windows_for_range`, newest period first."""
    return list(reversed(period_windows_for_range(
        from_datetime=from_datetime,
        to_datetime=to_datetime,
        time_granularity=time_granularity,
    )))


def fraction_of_window_occupied(
    *,
    local_period_start: datetime,
    local_period_end: datetime,
    occupied_start_hour: float,
    occupied_end_hour: float,
    holidays_iso_dates: set[str],
    weekend_weekday_indices_0_mon: set[int],
) -> tuple[float, float]:
    """Hour-count split of a window into occupied vs unoccupied."""
    occupied_hours = 0.0
    unoccupied_hours = 0.0
    cursor = local_period_start
    while cursor < local_period_end:
        next_cursor = min(cursor + timedelta(hours=1), local_period_end)
        hour_length = (next_cursor - cursor).total_seconds() / 3600.0
        is_holiday = cursor.date().isoformat() in holidays_iso_dates
        is_weekend = cursor.weekday() in weekend_weekday_indices_0_mon
        if is_holiday or is_weekend:
            unoccupied_hours += hour_length
        else:
            local_hour = cursor.hour + cursor.minute / 60.0
            if occupied_start_hour <= local_hour < occupied_end_hour:
                occupied_hours += hour_length
            else:
                unoccupied_hours += hour_length
        cursor = next_cursor
    return occupied_hours, unoccupied_hours


def aggregate_kwh_from_register_readings(
    register_readings: list[tuple[str, Any]],
) -> tuple[float, str | None]:
    """Cumulative-register kWh from ``(timestamp_iso, register_value)`` pairs."""
    numeric_readings = [
        (timestamp_iso, float(register_value))
        for timestamp_iso, register_value in register_readings
        if isinstance(register_value, int | float) and not isinstance(register_value, bool)
    ]
    if len(numeric_readings) < 2:
        return 0.0, None
    numeric_readings.sort(key=lambda reading: reading[0])
    cumulative_kwh = 0.0
    previous_value = numeric_readings[0][1]
    for _, current_value in numeric_readings[1:]:
        delta = current_value - previous_value
        if delta < 0:
            cumulative_kwh += current_value
        else:
            cumulative_kwh += delta
        previous_value = current_value
    return cumulative_kwh, 'cumulative_register_delta'


def aggregate_kwh_from_power_readings(
    power_readings: list[tuple[str, Any]],
) -> tuple[float, str | None]:
    """Power-integral kWh from ``(timestamp_iso, kW_value)`` pairs."""
    numeric_readings: list[tuple[datetime, float]] = []
    for timestamp_iso, power_value in power_readings:
        if not isinstance(power_value, int | float) or isinstance(power_value, bool):
            continue
        try:
            timestamp = datetime.fromisoformat(timestamp_iso)
        except ValueError:
            continue
        numeric_readings.append((timestamp, float(power_value)))
    if len(numeric_readings) < 2:
        return 0.0, None
    numeric_readings.sort(key=lambda reading: reading[0])
    cumulative_kwh = 0.0
    for previous_index in range(len(numeric_readings) - 1):
        current_timestamp, current_power = numeric_readings[previous_index + 1]
        previous_timestamp, previous_power = numeric_readings[previous_index]
        delta_hours = (current_timestamp - previous_timestamp).total_seconds() / 3600.0
        if delta_hours <= 0 or delta_hours > 1.5:
            continue
        cumulative_kwh += 0.5 * (previous_power + current_power) * delta_hours
    return cumulative_kwh, 'power_integral_trapezoid'
