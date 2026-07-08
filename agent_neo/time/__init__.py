"""Scope-local calendar dates and datetime ranges."""


from __future__ import annotations

from typing import LiteralString

from agent_neo.time.periods import (
    TELEMETRY_LAG_MATURITY_MINUTES,
    TimeGranularity,
    VALID_TIME_GRANULARITIES,
    coerce_to_local_tz,
    coerce_to_utc,
    coerce_to_utc_for_neo4j_datetime,
    epoch_seconds,
    iso_week_start_local_midnight,
    is_period_mature_for_production,
    latest_eligible_exclusive_period_end,
    latest_eligible_inclusive_daily_date,
    latest_eligible_inclusive_month_string,
    local_datetime_range_for_inclusive_dates,
    local_tz_identifier,
    next_month_start,
    normalize_to_hour_start,
    parse_local_datetime_from_iso,
    period_anchor,
    period_windows_for_range,
    prepare_hour_populate_window,
    require_timezone_aware,
    resolve_daily_get_date_range,
    resolve_hourly_get_datetime_range,
    resolve_monthly_get_month_range,
    resolve_populate_date_range,
    resolve_window_for_time_granularity,
    tz_offset_hours_from_tzinfo,
    tz_offset_key_segment,
)


__all__: tuple[LiteralString, ...] = (
    "TELEMETRY_LAG_MATURITY_MINUTES",
    "TimeGranularity",
    "VALID_TIME_GRANULARITIES",
    "coerce_to_local_tz",
    "coerce_to_utc",
    "coerce_to_utc_for_neo4j_datetime",
    "epoch_seconds",
    "iso_week_start_local_midnight",
    "is_period_mature_for_production",
    "latest_eligible_exclusive_period_end",
    "latest_eligible_inclusive_daily_date",
    "latest_eligible_inclusive_month_string",
    "local_datetime_range_for_inclusive_dates",
    "local_tz_identifier",
    "next_month_start",
    "normalize_to_hour_start",
    "parse_local_datetime_from_iso",
    "period_anchor",
    "period_windows_for_range",
    "prepare_hour_populate_window",
    "require_timezone_aware",
    "resolve_daily_get_date_range",
    "resolve_hourly_get_datetime_range",
    "resolve_monthly_get_month_range",
    "resolve_populate_date_range",
    "resolve_window_for_time_granularity",
    "tz_offset_hours_from_tzinfo",
    "tz_offset_key_segment",
)
