"""Scope-local calendar dates and datetime ranges for populate and rollups."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, tzinfo
from enum import StrEnum
from typing import Final, LiteralString
from zoneinfo import ZoneInfo

__all__: tuple[LiteralString, ...] = (
    'TimeGranularity',
    'VALID_TIME_GRANULARITIES',
    'TELEMETRY_LAG_MATURITY_MINUTES',
    'epoch_seconds',
    'coerce_to_local_tz',
    'coerce_to_utc',
    'coerce_to_utc_for_neo4j_datetime',
    'local_tz_identifier',
    'iso_week_start_local_midnight',
    'is_period_mature_for_production',
    'latest_eligible_exclusive_period_end',
    'latest_eligible_inclusive_daily_date',
    'latest_eligible_inclusive_month_string',
    'local_datetime_range_for_inclusive_dates',
    'next_month_start',
    'normalize_to_hour_start',
    'parse_local_datetime_from_iso',
    'period_anchor',
    'period_windows_for_range',
    'prepare_hour_populate_window',
    'require_timezone_aware',
    'resolve_daily_get_date_range',
    'resolve_hourly_get_datetime_range',
    'resolve_monthly_get_month_range',
    'resolve_populate_date_range',
    'resolve_window_for_time_granularity',
    'tz_offset_hours_from_tzinfo',
    'tz_offset_key_segment',
)


# Minutes after a local period ends before ensure-on-read ``.get()`` treats it as complete.
TELEMETRY_LAG_MATURITY_MINUTES: int = 30


class TimeGranularity(StrEnum):
    """Canonical time time_granularities for period windows and analytical products."""

    HOURLY = 'hourly'
    DAILY = 'daily'
    WEEKLY = 'weekly'
    MONTHLY = 'monthly'


VALID_TIME_GRANULARITIES: Final[frozenset[str]] = frozenset(
    time_granularity.value for time_granularity in TimeGranularity
)


def tz_offset_hours_from_tzinfo(tz: tzinfo) -> float:
    """Hours east of UTC for a fixed-offset or DST-aware ``tzinfo`` (evaluated at UTC now)."""
    offset = datetime.now(UTC).astimezone(tz).utcoffset()
    if offset is None:
        return 0.0
    return offset.total_seconds() / 3600.0


def resolve_populate_date_range(
    from_date: date | None,
    to_date: date | None,
    *,
    local_tz_offset_hours: float | None = None,
    tz: tzinfo | None = None,
) -> tuple[date, date]:
    """Resolve inclusive calendar ``from_date`` .. ``to_date`` for populate-style jobs.

    When ``to_date`` is omitted, uses facility-local today from ``tz`` if given, otherwise
    approximates local civil time via ``local_tz_offset_hours`` added to UTC now.
    When ``from_date`` is omitted, defaults to ``to_date`` (single-day window).
    """
    if to_date is None:
        if tz is not None:
            to_date = datetime.now(tz).date()
        elif local_tz_offset_hours is not None:
            local_now = datetime.now(UTC) + timedelta(hours=local_tz_offset_hours)
            to_date = local_now.date()
        else:
            raise ValueError('resolve_populate_date_range requires tz or local_tz_offset_hours when to_date is omitted')
    if from_date is None:
        from_date = to_date
    if from_date > to_date:
        raise ValueError(f'from_date {from_date!r} must be on or before to_date {to_date!r}')
    return from_date, to_date


def local_datetime_range_for_inclusive_dates(
    from_date: date,
    to_date: date,
    *,
    tz: tzinfo,
) -> tuple[datetime, datetime]:
    """Facility-local ``[start, end)`` datetimes covering inclusive calendar dates."""
    local_start = datetime.combine(from_date, time.min, tzinfo=tz)
    local_end = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=tz)
    return local_start, local_end


def parse_local_datetime_from_iso(raw_period_start: str, *, tz: tzinfo) -> datetime:
    """Parse ISO period start; attach ``tz`` when naive, else convert to facility local."""
    local_period_start = datetime.fromisoformat(raw_period_start)
    if local_period_start.tzinfo is None:
        return local_period_start.replace(tzinfo=tz)
    return local_period_start.astimezone(tz)


def tz_offset_key_segment(local_tz_offset_hours: float) -> str:
    """Compact signed offset for cache keys, e.g. ``+5.5``, ``-8``."""
    return f'{local_tz_offset_hours:+g}'


def require_timezone_aware(dt: datetime, *, name: str) -> datetime:
    """Reject naive datetimes (including ``tzinfo=timezone.utc`` without ``astimezone`` usage)."""
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f'{name} must be a timezone-aware local datetime')
    return dt


def coerce_to_utc(value: datetime | None) -> datetime | None:
    """Return ``value`` as UTC; attach UTC to naive datetimes."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def epoch_seconds(moment: datetime | None = None) -> float:
    """Epoch seconds in the same representation as ``DateTimeProperty`` values."""
    return coerce_to_utc(moment or datetime.now(tz=UTC)).timestamp()


def local_tz_identifier(local_tz: tzinfo) -> str:
    """Return the IANA timezone name used in hourly consumption external keys."""
    if isinstance(local_tz, ZoneInfo):
        return local_tz.key
    raise ValueError(
        'facility timezone must be zoneinfo.ZoneInfo (IANA identifier from ontology)',
    )


def coerce_to_local_tz(dt: datetime, local_tz: tzinfo, *, name: str = 'datetime') -> datetime:
    """Convert to facility-local civil time with canonical ``local_tz``."""
    facility_local_datetime = require_timezone_aware(dt, name=name).astimezone(local_tz)
    normalized_time = facility_local_datetime.time().replace(microsecond=0)
    return datetime.combine(
        facility_local_datetime.date(),
        normalized_time,
        tzinfo=local_tz,
    )


def coerce_to_utc_for_neo4j_datetime(
    dt: datetime,
    local_tz: tzinfo,
    *,
    name: str = 'datetime',
) -> datetime:
    """Facility-local instant as UTC for ```DateTimeNeo4jFormatProperty``` (Bolt dehydrate-safe)."""
    return coerce_to_local_tz(dt, local_tz, name=name).astimezone(UTC)


def normalize_to_hour_start(dt: datetime) -> datetime:
    """Truncate to the containing calendar hour in the same tz offset."""
    return dt.replace(minute=0, second=0, microsecond=0)


def prepare_hour_populate_window(
    from_datetime: datetime,
    to_datetime: datetime,
    *,
    tz: tzinfo,
) -> tuple[datetime, datetime]:
    """Return hour-aligned facility-local ``[start, end)`` for hourly populate."""
    local_start = normalize_to_hour_start(
        require_timezone_aware(from_datetime, name='from_datetime').astimezone(tz),
    )
    local_end = normalize_to_hour_start(
        require_timezone_aware(to_datetime, name='to_datetime').astimezone(tz),
    )
    if local_start >= local_end:
        raise ValueError(
            f'from_datetime {from_datetime!r} must be strictly before to_datetime {to_datetime!r} '
            f'(hour-aligned window [{local_start!r}, {local_end!r}) is empty)',
        )
    return local_start, local_end


# ============================================================================
# Period calendar helpers
# ============================================================================


def next_month_start(local_month_start: datetime) -> datetime:
    """Return ``YYYY-(MM+1)-01 00:00`` (rolling year forward in December)."""
    if local_month_start.month == 12:
        return local_month_start.replace(year=local_month_start.year + 1, month=1)
    return local_month_start.replace(month=local_month_start.month + 1)


def iso_week_start_local_midnight(local_datetime: datetime) -> datetime:
    """Snap a datetime down to local midnight Monday (ISO week start)."""
    midnight = local_datetime.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(days=midnight.weekday())


def period_anchor(*, time_granularity: str, local_period_start: datetime) -> str:
    """Canonical, collision-free string anchoring a period at a given time_granularity.

    The anchor is derived **only** from the aligned period start, so two requests that resolve
    to the same period produce the same key regardless of how their bounds were expressed
    (``concretized/IDENTITY-CACHE-KEY.md`` — period-bound canonicalization).
    """
    if time_granularity == TimeGranularity.HOURLY:
        return local_period_start.strftime('%Y-%m-%dT%H:00')
    if time_granularity == TimeGranularity.DAILY:
        return local_period_start.strftime('%Y-%m-%d')
    if time_granularity == TimeGranularity.WEEKLY:
        # ISO year + ISO week number; unambiguous across year boundaries.
        return local_period_start.strftime('%G-W%V')
    if time_granularity == TimeGranularity.MONTHLY:
        return local_period_start.strftime('%Y-%m')
    raise ValueError(
        f'time_granularity must be one of {[member.value for member in TimeGranularity]}; got {time_granularity!r}',
    )


def period_windows_for_range(
    *,
    from_datetime: datetime,
    to_datetime: datetime,
    time_granularity: str,
) -> list[tuple[datetime, datetime]]:
    """Aligned hourly / daily / weekly / monthly ``[start, end)`` windows covering ``[from, to)``."""
    if time_granularity == TimeGranularity.HOURLY:
        period_start = from_datetime.replace(minute=0, second=0, microsecond=0)
        period_delta: timedelta | None = timedelta(hours=1)
    elif time_granularity == TimeGranularity.DAILY:
        period_start = from_datetime.replace(hour=0, minute=0, second=0, microsecond=0)
        period_delta = timedelta(days=1)
    elif time_granularity == TimeGranularity.WEEKLY:
        period_start = iso_week_start_local_midnight(from_datetime)
        period_delta = timedelta(weeks=1)
    elif time_granularity == TimeGranularity.MONTHLY:
        period_start = from_datetime.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        period_delta = None
    else:
        raise ValueError(f"unsupported time_granularity {time_granularity!r}")

    period_windows: list[tuple[datetime, datetime]] = []
    while period_start < to_datetime:
        period_end = next_month_start(period_start) if period_delta is None else period_start + period_delta
        period_windows.append((period_start, period_end))
        period_start = period_end
    return period_windows


def _facility_local_now(*, local_tz: tzinfo, now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(tz=local_tz)
    return coerce_to_local_tz(now, local_tz, name='now')


def _period_maturity_deadline(*, exclusive_period_end: datetime, maturity_minutes: int) -> datetime:
    return exclusive_period_end + timedelta(minutes=maturity_minutes)


def _step_exclusive_period_end_back(
    *,
    exclusive_period_end: datetime,
    time_granularity: str,
) -> datetime:
    if time_granularity == TimeGranularity.HOURLY:
        return exclusive_period_end - timedelta(hours=1)
    if time_granularity == TimeGranularity.DAILY:
        return exclusive_period_end - timedelta(days=1)
    if time_granularity == TimeGranularity.WEEKLY:
        return exclusive_period_end - timedelta(weeks=1)
    if time_granularity == TimeGranularity.MONTHLY:
        month_start = exclusive_period_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if month_start.month == 1:
            return month_start.replace(year=month_start.year - 1, month=12)
        return month_start.replace(month=month_start.month - 1)
    raise ValueError(
        f'time_granularity must be one of {[g.value for g in TimeGranularity]}; got {time_granularity!r}',
    )


def _initial_exclusive_period_end(*, local_now: datetime, time_granularity: str) -> datetime:
    if time_granularity == TimeGranularity.HOURLY:
        return local_now.replace(minute=0, second=0, microsecond=0)
    if time_granularity == TimeGranularity.DAILY:
        midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        return midnight + timedelta(days=1)
    if time_granularity == TimeGranularity.WEEKLY:
        week_start = iso_week_start_local_midnight(local_now)
        return week_start + timedelta(weeks=1)
    if time_granularity == TimeGranularity.MONTHLY:
        month_start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return next_month_start(month_start)
    raise ValueError(
        f'time_granularity must be one of {[g.value for g in TimeGranularity]}; got {time_granularity!r}',
    )


# ============================================================================
# Maturity-aware ensure-on-read window resolution
# ============================================================================


def latest_eligible_exclusive_period_end(
    *,
    time_granularity: str,
    local_tz: tzinfo,
    now: datetime | None = None,
    maturity_minutes: int = TELEMETRY_LAG_MATURITY_MINUTES,
) -> datetime:
    """Exclusive end of the latest finished local period eligible for ensure-on-read ``.get()``."""
    local_now = _facility_local_now(local_tz=local_tz, now=now)
    candidate_exclusive_end = _initial_exclusive_period_end(
        local_now=local_now,
        time_granularity=time_granularity,
    )
    while local_now < _period_maturity_deadline(
        exclusive_period_end=candidate_exclusive_end,
        maturity_minutes=maturity_minutes,
    ):
        candidate_exclusive_end = _step_exclusive_period_end_back(
            exclusive_period_end=candidate_exclusive_end,
            time_granularity=time_granularity,
        )
    return candidate_exclusive_end


def latest_eligible_inclusive_daily_date(
    *,
    local_tz: tzinfo,
    now: datetime | None = None,
    maturity_minutes: int = TELEMETRY_LAG_MATURITY_MINUTES,
) -> date:
    """Latest facility-local calendar day eligible for daily ensure-on-read ``.get()``."""
    local_to_exclusive = latest_eligible_exclusive_period_end(
        time_granularity=TimeGranularity.DAILY,
        local_tz=local_tz,
        now=now,
        maturity_minutes=maturity_minutes,
    )
    return local_to_exclusive.date() - timedelta(days=1)


def latest_eligible_inclusive_month_string(
    *,
    local_tz: tzinfo,
    now: datetime | None = None,
    maturity_minutes: int = TELEMETRY_LAG_MATURITY_MINUTES,
) -> str:
    """Latest ``YYYY-MM`` month eligible for monthly ensure-on-read ``.get()``."""
    local_to_exclusive = latest_eligible_exclusive_period_end(
        time_granularity=TimeGranularity.MONTHLY,
        local_tz=local_tz,
        now=now,
        maturity_minutes=maturity_minutes,
    )
    month_start = local_to_exclusive.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start.month == 1:
        resolved_to_month_start = month_start.replace(year=month_start.year - 1, month=12)
    else:
        resolved_to_month_start = month_start.replace(month=month_start.month - 1)
    return resolved_to_month_start.strftime('%Y-%m')


def resolve_hourly_get_datetime_range(
    from_datetime: datetime | None,
    to_datetime: datetime | None,
    *,
    local_tz: tzinfo,
    now: datetime | None = None,
    maturity_minutes: int = TELEMETRY_LAG_MATURITY_MINUTES,
) -> tuple[datetime, datetime]:
    """Resolve facility-local ``[from, to)`` for hourly ensure-on-read ``.get()``."""
    eligible_to_exclusive = latest_eligible_exclusive_period_end(
        time_granularity=TimeGranularity.HOURLY,
        local_tz=local_tz,
        now=now,
        maturity_minutes=maturity_minutes,
    )
    if to_datetime is None:
        local_to_exclusive = eligible_to_exclusive
    else:
        requested_to_exclusive = coerce_to_local_tz(
            to_datetime,
            local_tz,
            name='to_datetime',
        ).replace(minute=0, second=0, microsecond=0)
        local_to_exclusive = min(requested_to_exclusive, eligible_to_exclusive)

    if from_datetime is None:
        local_from = local_to_exclusive - timedelta(hours=1)
    else:
        local_from = coerce_to_local_tz(
            from_datetime,
            local_tz,
            name='from_datetime',
        ).replace(minute=0, second=0, microsecond=0)

    if local_from >= local_to_exclusive:
        raise ValueError(
            f'from_datetime {local_from!r} must be strictly before to_datetime {local_to_exclusive!r}',
        )
    return local_from, local_to_exclusive


def resolve_daily_get_date_range(
    from_date: date | None,
    to_date: date | None,
    *,
    local_tz: tzinfo,
    now: datetime | None = None,
    maturity_minutes: int = TELEMETRY_LAG_MATURITY_MINUTES,
) -> tuple[date, date]:
    """Resolve inclusive calendar ``from_date`` .. ``to_date`` for daily ensure-on-read ``.get()``."""
    eligible_to_date = latest_eligible_inclusive_daily_date(
        local_tz=local_tz,
        now=now,
        maturity_minutes=maturity_minutes,
    )
    if to_date is None:
        resolved_to_date = eligible_to_date
    else:
        resolved_to_date = min(to_date, eligible_to_date)

    if from_date is None:
        resolved_from_date = resolved_to_date
    else:
        resolved_from_date = from_date

    if resolved_from_date > resolved_to_date:
        raise ValueError(
            f'from_date {resolved_from_date!r} must be on or before to_date {resolved_to_date!r}',
        )
    return resolved_from_date, resolved_to_date


def resolve_monthly_get_month_range(
    from_month: str | None,
    to_month: str | None,
    *,
    local_tz: tzinfo,
    now: datetime | None = None,
    maturity_minutes: int = TELEMETRY_LAG_MATURITY_MINUTES,
) -> tuple[str, str]:
    """Resolve inclusive ``YYYY-MM`` range for monthly ensure-on-read ``.get()``."""
    eligible_to_month = latest_eligible_inclusive_month_string(
        local_tz=local_tz,
        now=now,
        maturity_minutes=maturity_minutes,
    )
    if to_month is None:
        resolved_to_month = eligible_to_month
    else:
        resolved_to_month = min(to_month, eligible_to_month)

    if from_month is None:
        resolved_from_month = resolved_to_month
    else:
        resolved_from_month = from_month

    if resolved_from_month > resolved_to_month:
        raise ValueError(
            f'from_month {resolved_from_month!r} must be on or before to_month {resolved_to_month!r}',
        )
    return resolved_from_month, resolved_to_month


def resolve_window_for_time_granularity(
    from_bound: datetime | str | None,
    to_bound: datetime | str | None,
    *,
    time_granularity: str,
    local_tz: tzinfo,
    now: datetime | None = None,
    maturity_minutes: int = TELEMETRY_LAG_MATURITY_MINUTES,
) -> tuple[datetime, datetime]:
    """Resolve facility-local ``[from, to)`` for any time_granularity, clamping ``to`` to latest mature.

    Granularity-agnostic generalization of compat electricity get-range helpers: the maturity
    clamp lives here and applies identically to every product family.
    """
    if time_granularity == TimeGranularity.MONTHLY:
        from_month = None if from_bound is None else _month_string_from_bound(from_bound)
        to_month = None if to_bound is None else _month_string_from_bound(to_bound)
        resolved_from_month, resolved_to_month = resolve_monthly_get_month_range(
            from_month,
            to_month,
            local_tz=local_tz,
            now=now,
            maturity_minutes=maturity_minutes,
        )
        from_month_start = datetime.combine(
            date.fromisoformat(f'{resolved_from_month}-01'), datetime.min.time(), tzinfo=local_tz,
        )
        to_month_start = datetime.combine(
            date.fromisoformat(f'{resolved_to_month}-01'), datetime.min.time(), tzinfo=local_tz,
        )
        return from_month_start, next_month_start(to_month_start)

    parsed_from = None if from_bound is None else _parse_bound_datetime(from_bound, local_tz=local_tz)
    parsed_to = None if to_bound is None else _parse_bound_datetime(to_bound, local_tz=local_tz)

    if time_granularity == TimeGranularity.HOURLY:
        return resolve_hourly_get_datetime_range(
            parsed_from, parsed_to, local_tz=local_tz, now=now, maturity_minutes=maturity_minutes,
        )

    if time_granularity == TimeGranularity.DAILY:
        from_date = None if parsed_from is None else parsed_from.date()
        to_date = None if parsed_to is None else parsed_to.date()
        resolved_from_date, resolved_to_date = resolve_daily_get_date_range(
            from_date, to_date, local_tz=local_tz, now=now, maturity_minutes=maturity_minutes,
        )
        local_start = datetime.combine(resolved_from_date, datetime.min.time(), tzinfo=local_tz)
        local_end = datetime.combine(resolved_to_date + timedelta(days=1), datetime.min.time(), tzinfo=local_tz)
        return local_start, local_end

    if time_granularity == TimeGranularity.WEEKLY:
        if parsed_to is None:
            local_to_exclusive = latest_eligible_exclusive_period_end(
                time_granularity=TimeGranularity.WEEKLY, local_tz=local_tz, now=now, maturity_minutes=maturity_minutes,
            )
        else:
            local_to_exclusive = iso_week_start_local_midnight(parsed_to) + timedelta(weeks=1)
        local_from = (
            local_to_exclusive - timedelta(weeks=1)
            if parsed_from is None
            else iso_week_start_local_midnight(parsed_from)
        )
        if local_from >= local_to_exclusive:
            raise ValueError(f'from {local_from!r} must be strictly before to {local_to_exclusive!r}')
        return local_from, local_to_exclusive

    raise ValueError(f"unsupported time_granularity {time_granularity!r}")


def is_period_mature_for_production(
    *,
    local_period_end: datetime,
    time_granularity: str,
    local_tz: tzinfo,
    now: datetime | None = None,
    maturity_minutes: int = TELEMETRY_LAG_MATURITY_MINUTES,
) -> bool:
    """Populate-side maturity gate: may this finished period be persisted as settled?

    A period is mature for production iff its exclusive end is at or before the latest eligible
    (mature) period end for its time_granularity.
    """
    require_timezone_aware(local_period_end, name='local_period_end')
    eligible_to_exclusive = latest_eligible_exclusive_period_end(
        time_granularity=time_granularity, local_tz=local_tz, now=now, maturity_minutes=maturity_minutes,
    )
    return local_period_end.astimezone(local_tz) <= eligible_to_exclusive


def _parse_bound_datetime(bound: datetime | str, *, local_tz: tzinfo) -> datetime:
    if isinstance(bound, datetime):
        local_datetime = bound
    else:
        text = bound.strip()
        partial = _parse_partial_local_start_datetime(text)
        local_datetime = partial if partial is not None else datetime.fromisoformat(text)
    if local_datetime.tzinfo is None:
        return local_datetime.replace(tzinfo=local_tz)
    return coerce_to_local_tz(local_datetime, local_tz)


def _parse_partial_local_start_datetime(text: str) -> datetime | None:
    if len(text) == 4 and text.isdigit():
        return datetime.combine(date.fromisoformat(f'{text}-01-01'), datetime.min.time())
    if len(text) == 7 and text[4] == '-':
        return datetime.combine(date.fromisoformat(f'{text}-01'), datetime.min.time())
    return None


def _month_string_from_bound(bound: datetime | str) -> str:
    if isinstance(bound, datetime):
        return bound.strftime('%Y-%m')
    text = bound.strip()
    if len(text) == 4 and text.isdigit():
        return f'{text}-01'
    if len(text) == 7 and text[4] == '-':
        return text
    return datetime.fromisoformat(text).strftime('%Y-%m')
