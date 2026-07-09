"""Unit tests for agent_neo.util.datetime calendar helpers."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from agent_neo.util.datetime import (
    coerce_to_date,
    complete_calendar_month_windows_in_range,
    first_day_of_month,
    month_floor,
    next_month_first_day,
    shift_months,
    start_of_local_day,
    start_of_next_local_day,
)

IST = ZoneInfo('Asia/Kolkata')


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        (date(2026, 5, 22), date(2026, 5, 1)),
        (date(2026, 12, 31), date(2026, 12, 1)),
    ],
)
def test_first_day_of_month(value: date, expected: date) -> None:
    assert first_day_of_month(value) == expected


def test_next_month_first_day_december_rolls_year() -> None:
    assert next_month_first_day(date(2026, 12, 15)) == date(2027, 1, 1)
    assert next_month_first_day(date(2026, 5, 1)) == date(2026, 6, 1)


def test_shift_months() -> None:
    assert shift_months(date(2026, 5, 15), delta_months=1) == date(2026, 6, 1)
    assert shift_months(date(2026, 1, 1), delta_months=-1) == date(2025, 12, 1)


def test_month_floor() -> None:
    local_datetime = datetime(2026, 5, 22, 13, 45, tzinfo=IST)
    assert month_floor(local_datetime) == datetime(2026, 5, 1, 0, 0, tzinfo=IST)


def test_complete_calendar_month_windows_in_range_includes_may_excludes_partial_june() -> None:
    windows = complete_calendar_month_windows_in_range(
        date(2026, 1, 1),
        date(2026, 6, 5),
    )
    labels = [start.strftime('%Y-%m') for start, _ in windows]
    assert '2026-05' in labels
    assert '2026-06' not in labels
    assert labels[0] == '2026-01'


def test_complete_calendar_month_windows_skips_partial_start_month() -> None:
    windows = complete_calendar_month_windows_in_range(
        date(2026, 5, 15),
        date(2026, 7, 1),
    )
    labels = [start.strftime('%Y-%m') for start, _ in windows]
    assert labels == ['2026-06']


def test_start_of_local_day_and_next() -> None:
    local_date = date(2026, 5, 22)
    start = start_of_local_day(local_date, IST)
    end = start_of_next_local_day(local_date, IST)
    assert start == datetime(2026, 5, 22, 0, 0, tzinfo=IST)
    assert end == datetime(2026, 5, 23, 0, 0, tzinfo=IST)


def test_coerce_to_date() -> None:
    assert coerce_to_date(None) is None
    assert coerce_to_date(date(2026, 5, 1)) == date(2026, 5, 1)
    assert coerce_to_date(datetime(2026, 5, 1, 12, 0, tzinfo=IST)) == date(2026, 5, 1)
    assert coerce_to_date('2026-05-01') == date(2026, 5, 1)
    assert coerce_to_date('2026-05-01T00:00+05:30') == date(2026, 5, 1)
