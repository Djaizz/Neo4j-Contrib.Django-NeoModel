"""Sealed unit tests for electricity daily spike baseline helpers."""


from __future__ import annotations

from datetime import date

import pytest

from agent_neo.analytical_product.daily_spike_statistics import (
    build_contextual_baseline_by_day,
    leave_one_out_weekday_weekend_mean_baseline,
    mean_of_floats,
    spike_baseline_day_class,
    summarize_baseline_by_day_class,
)


@pytest.mark.unit
def test_spike_baseline_day_class_weekday_and_weekend() -> None:
    holidays: set[str] = set()
    assert spike_baseline_day_class(date(2026, 5, 20), holidays_iso_dates=holidays) == "weekday"
    assert spike_baseline_day_class(date(2026, 5, 23), holidays_iso_dates=holidays) == "weekend"


@pytest.mark.unit
def test_spike_baseline_day_class_excludes_holidays() -> None:
    holiday = date(2026, 5, 20)
    holidays = {holiday.isoformat()}
    assert spike_baseline_day_class(holiday, holidays_iso_dates=holidays) is None


@pytest.mark.unit
def test_leave_one_out_weekday_weekend_mean_baseline() -> None:
    calendar_day_to_kwh = {
        date(2026, 5, 19): 100.0,
        date(2026, 5, 20): 150.0,
        date(2026, 5, 21): 110.0,
        date(2026, 5, 23): 80.0,
        date(2026, 5, 24): 90.0,
    }
    baseline, peers, day_class = leave_one_out_weekday_weekend_mean_baseline(
        calendar_day_to_kwh,
        date(2026, 5, 20),
        holidays_iso_dates=set(),
    )
    assert day_class == "weekday"
    assert peers == [100.0, 110.0]
    assert baseline == pytest.approx(105.0)


@pytest.mark.unit
def test_leave_one_out_weekday_weekend_mean_baseline_weekend_pool() -> None:
    calendar_day_to_kwh = {
        date(2026, 5, 23): 120.0,
        date(2026, 5, 24): 100.0,
    }
    baseline, peers, day_class = leave_one_out_weekday_weekend_mean_baseline(
        calendar_day_to_kwh,
        date(2026, 5, 23),
        holidays_iso_dates=set(),
    )
    assert day_class == "weekend"
    assert peers == [100.0]
    assert baseline == pytest.approx(100.0)


@pytest.mark.unit
def test_leave_one_out_weekday_weekend_mean_baseline_no_peers() -> None:
    calendar_day_to_kwh = {date(2026, 5, 23): 120.0}
    baseline, peers, day_class = leave_one_out_weekday_weekend_mean_baseline(
        calendar_day_to_kwh,
        date(2026, 5, 23),
        holidays_iso_dates=set(),
    )
    assert day_class == "weekend"
    assert peers == []
    assert baseline is None


@pytest.mark.unit
def test_mean_of_floats() -> None:
    assert mean_of_floats([100.0, 110.0, 120.0]) == pytest.approx(110.0)


@pytest.mark.unit
def test_build_contextual_baseline_by_day() -> None:
    calendar_day_to_kwh = {
        date(2026, 5, 19): 100.0,
        date(2026, 5, 20): 150.0,
        date(2026, 5, 21): 110.0,
        date(2026, 5, 23): 120.0,
        date(2026, 5, 24): 100.0,
    }
    baseline_by_day = build_contextual_baseline_by_day(
        calendar_day_to_kwh,
        holidays_iso_dates=set(),
    )
    assert baseline_by_day[date(2026, 5, 20)]['baseline_day_class'] == 'weekday'
    assert baseline_by_day[date(2026, 5, 20)]['baseline_kwh'] == pytest.approx(105.0)
    assert baseline_by_day[date(2026, 5, 20)]['extra_kwh'] == pytest.approx(45.0)
    assert baseline_by_day[date(2026, 5, 23)]['baseline_day_class'] == 'weekend'
    assert baseline_by_day[date(2026, 5, 23)]['baseline_kwh'] == pytest.approx(100.0)


@pytest.mark.unit
def test_build_contextual_baseline_by_day_holiday_nulls() -> None:
    holiday = date(2026, 5, 20)
    calendar_day_to_kwh = {
        date(2026, 5, 19): 100.0,
        holiday: 150.0,
        date(2026, 5, 21): 110.0,
    }
    baseline_by_day = build_contextual_baseline_by_day(
        calendar_day_to_kwh,
        holidays_iso_dates={holiday.isoformat()},
    )
    assert baseline_by_day[holiday]['baseline_kwh'] is None
    assert baseline_by_day[holiday]['baseline_day_class'] is None


@pytest.mark.unit
def test_summarize_baseline_by_day_class() -> None:
    calendar_day_to_kwh = {
        date(2026, 5, 19): 100.0,
        date(2026, 5, 20): 150.0,
        date(2026, 5, 23): 120.0,
        date(2026, 5, 24): 100.0,
    }
    baseline_by_day = build_contextual_baseline_by_day(
        calendar_day_to_kwh,
        holidays_iso_dates=set(),
    )
    summaries = summarize_baseline_by_day_class(calendar_day_to_kwh, baseline_by_day)
    by_class = {row['day_class']: row for row in summaries}
    assert by_class['weekday']['day_count'] == 2
    assert by_class['weekend']['day_count'] == 2
    assert by_class['weekday']['avg_observed_kwh'] == pytest.approx(125.0)
