"""Tests for facility-local hour/day classification."""


from __future__ import annotations

from datetime import date, datetime

from agent_neo.analytical_product.time_classification import (
    classify_day,
    classify_hour,
    facility_operating_hour_bounds,
    hour_matches_daily_rollup_boundary,
    parse_occupied_window_label,
)


def test_parse_occupied_window_label_whole_hours() -> None:
    assert parse_occupied_window_label('06:00-17:30') == (6, 18)
    assert parse_occupied_window_label('09:00-09:00') == (9, 10)


def test_classify_hour_operating() -> None:
    start, end = facility_operating_hour_bounds(occupied_window_label='06:00-17:30')
    assert classify_hour(datetime(2026, 5, 20, 8, 0), hour_slice='facility_operating', start_hour_inclusive=start, end_hour_exclusive=end)
    assert not classify_hour(datetime(2026, 5, 20, 18, 0), hour_slice='facility_operating', start_hour_inclusive=start, end_hour_exclusive=end)
    assert classify_hour(datetime(2026, 5, 20, 5, 0), hour_slice='facility_non_operating', start_hour_inclusive=start, end_hour_exclusive=end)


def test_classify_day_weekday_holiday() -> None:
    holidays = {'2026-05-20'}
    wednesday = date(2026, 5, 20)
    assert classify_day(wednesday, day_slice='holiday', holidays_iso_dates=holidays)
    assert not classify_day(wednesday, day_slice='weekday', holidays_iso_dates=holidays)
    saturday = date(2026, 5, 23)
    assert classify_day(saturday, day_slice='weekend', holidays_iso_dates=holidays)


def test_hour_matches_daily_rollup_boundary_holiday() -> None:
    holidays = {'2026-01-01'}
    dt = datetime(2026, 1, 1, 12, 0)
    assert hour_matches_daily_rollup_boundary(dt, 'holiday', holidays_iso_dates=holidays)
    assert not hour_matches_daily_rollup_boundary(dt, 'non_holiday', holidays_iso_dates=holidays)
