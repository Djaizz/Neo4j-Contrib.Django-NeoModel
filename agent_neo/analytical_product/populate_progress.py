"""Progress reporting for analytical populate (day lines + compact tqdm, or verbose lines)."""


from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Final, LiteralString, Protocol, TypeVar
import logging
import os
import re
import sys
import threading
import time


_NEO_LABEL_PREFIXES: Final[tuple[str, ...]] = ('ForgeODB_Analytical_',)


def _env_value(name: str, *, default: str = '') -> str:
    """Read ``AGENT_NEO_<name>`` with legacy ``FORGE_ODB_<name>`` fallback."""
    agent_value = os.environ.get(f'AGENT_NEO_{name}', '').strip()
    if agent_value:
        return agent_value
    legacy_value = os.environ.get(f'FORGE_ODB_{name}', '').strip()
    if legacy_value:
        return legacy_value
    return default


__all__: tuple[LiteralString, ...] = (
    'PopulateProgress',
    'format_explicit_half_open_time_window',
    'format_progress_count',
    'format_local_hour_window_label',
    'format_newest_first_half_open_range',
    'format_newest_first_inclusive_hour_window_range',
    'format_newest_first_inclusive_range',
    'format_newest_first_scope_range',
    'plain_populate_progress_enabled',
    'populate_day_only_progress_enabled',
    'populate_line_progress_enabled',
    'populate_verbose_progress_enabled',
)


_T = TypeVar('_T')
_log = logging.getLogger(__name__)
_tqdm_terminal_ready = False


class _PeriodBar(Protocol):
    def update(self, increment: int = 1) -> None: ...

    def set_postfix_str(self, postfix: str, *, refresh: bool = True) -> None: ...

    def set_description(self, description: str) -> None: ...


class _NullPeriodBar:
    def update(self, increment: int = 1) -> None:
        return None

    def set_postfix_str(self, postfix: str, *, refresh: bool = True) -> None:
        return None

    def set_description(self, description: str) -> None:
        return None


class _RefreshingPeriodBar:
    """Period bar wrapper that keeps the active meter bar visible underneath."""

    def __init__(self, bar: Any, populate_progress: 'PopulateProgress') -> None:
        self._bar = bar
        self._populate_progress = populate_progress

    def update(self, increment: int = 1) -> None:
        self._bar.update(increment)
        self._bar.refresh()
        self._populate_progress._refresh_active_meter_bar()

    def set_postfix_str(self, postfix: str, *, refresh: bool = True) -> None:
        self._bar.set_postfix_str(postfix, refresh=refresh)
        self._bar.refresh()
        self._populate_progress._refresh_active_meter_bar()

    def set_description(self, description: str) -> None:
        self._bar.set_description(description)
        self._populate_progress._refresh_active_meter_bar()


def _ensure_tqdm_terminal_ready() -> None:
    global _tqdm_terminal_ready
    if _tqdm_terminal_ready:
        return
    if sys.platform == 'win32':
        os.environ.setdefault('TERM', 'xterm-256color')
        try:
            import colorama

            colorama.init(strip=False)
        except ImportError:
            pass
    _tqdm_terminal_ready = True


def _tqdm_kwargs(*, position: int, leave: bool) -> dict[str, Any]:
    _ensure_tqdm_terminal_ready()
    kwargs: dict[str, Any] = {
        'position': position,
        'leave': leave,
        'file': sys.stderr,
        'mininterval': 0.1,
        'maxinterval': 30.0,
        'miniters': 1,
        'bar_format': (
            '{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} '
            '[{elapsed}<{remaining}, {rate_fmt}]{postfix}'
        ),
    }
    if sys.platform == 'win32':
        kwargs['dynamic_ncols'] = False
        kwargs['ncols'] = 120
    else:
        kwargs['dynamic_ncols'] = True
    return kwargs


_CommaSeparatedTqdm: type[Any] | None = None
_COUNT_PAIR_PATTERN = re.compile(r'\| (\d+)/(\d+) \[')


def _comma_format_tqdm_count_pair(message: str) -> str:
    def _replace_count_pair(match: re.Match[str]) -> str:
        current_count = int(match.group(1))
        total_count = int(match.group(2))
        return f'| {current_count:,}/{total_count:,} ['

    return _COUNT_PAIR_PATTERN.sub(_replace_count_pair, message, count=1)


def format_progress_count(count: int) -> str:
    """Render progress counts with grouped thousands for human-readable logs."""
    return f'{int(count):,}'


def format_explicit_half_open_time_window(
    from_datetime: datetime,
    to_datetime: datetime,
) -> str:
    """Render an operator-facing half-open local window as ``from=... to<...``."""
    return (
        f'from={from_datetime.isoformat(timespec="minutes")} '
        f'to<{to_datetime.isoformat(timespec="minutes")}'
    )


def _comma_separated_tqdm(*args: Any, **kwargs: Any) -> Any:
    """tqdm with thousands separators in ``n_fmt`` / ``total_fmt`` (e.g. 1,216/3,610)."""
    global _CommaSeparatedTqdm
    if _CommaSeparatedTqdm is None:
        from tqdm import tqdm as _StdTqdm

        class _CommaSeparatedTqdmImpl(_StdTqdm):
            def display(self, msg: str | None = None, pos: int | None = None) -> bool:
                if msg is None:
                    msg = _comma_format_tqdm_count_pair(str(self))
                else:
                    msg = _comma_format_tqdm_count_pair(msg)
                return super().display(msg, pos)

        _CommaSeparatedTqdm = _CommaSeparatedTqdmImpl
    return _CommaSeparatedTqdm(*args, **kwargs)


def _tqdm_write(line: str) -> None:
    _ensure_tqdm_terminal_ready()
    from tqdm import tqdm

    tqdm.write(line, file=sys.stderr)


def plain_populate_progress_enabled() -> bool:
    """When false, nested loops run without tqdm (compat tqdm-off populate)."""
    return _env_value('POPULATE_PLAIN_PROGRESS', default='1').lower() not in (
        '0',
        'false',
        'no',
        'off',
    )


def populate_day_only_progress_enabled() -> bool:
    """When true, only calendar-day lines (no tqdm, no per-phase lines)."""
    return _env_value('POPULATE_DAY_ONLY_PROGRESS', default='0').lower() in (
        '1',
        'true',
        'yes',
        'on',
    )


def populate_line_progress_enabled() -> bool:
    """When true, keep step lines but disable tqdm redraws."""
    return _env_value('POPULATE_LINE_PROGRESS', default='0').lower() in (
        '1',
        'true',
        'yes',
        'on',
    )


def populate_verbose_progress_enabled() -> bool:
    """When true, emit richer context lines while keeping tqdm where available."""
    return _env_value('POPULATE_VERBOSE_PROGRESS', default='0').lower() in (
        '1',
        'true',
        'yes',
        'on',
    )


def _heartbeat_interval_sec() -> float:
    raw = _env_value('POPULATE_HEARTBEAT_SEC', default='90')
    return max(15.0, float(raw))


def _stall_warn_sec() -> float:
    raw = _env_value('POPULATE_STALL_WARN_SEC', default='180')
    return max(60.0, float(raw))


def _log_cache_collisions() -> bool:
    """When true, log collision counts at DEBUG (never stderr)."""
    return _env_value('POPULATE_LOG_CACHE_COLLISIONS', default='0').lower() in (
        '1',
        'true',
        'yes',
        'on',
    )


def format_newest_first_scope_range(earliest: str, latest: str) -> str:
    """Scope tag with newest bound first (matches newest-first compute order)."""
    return f'{latest}..{earliest}'


def format_newest_first_inclusive_range(earliest: str, latest: str) -> str:
    """Bracketed inclusive range with newest bound first."""
    return f'[{latest}, {earliest}]'


def format_newest_first_half_open_range(earliest: str, latest_exclusive: str) -> str:
    """Bracketed half-open range with newest exclusive end first."""
    return f'[{latest_exclusive}, {earliest})'


def _local_datetime_tz_suffix(local_datetime: datetime) -> str:
    local_datetime_iso = local_datetime.isoformat(timespec='minutes')
    timezone_separator_index = max(local_datetime_iso.rfind('+'), local_datetime_iso.rfind('-', 10))
    if timezone_separator_index > 10:
        return local_datetime_iso[timezone_separator_index:]
    return ''


def format_local_hour_window_label(hour_start: datetime, hour_end: datetime) -> str:
    """Finished local hour as ``2026-05-31T09:00-10:00+05:30`` (start–end, not a single instant)."""
    timezone_suffix = _local_datetime_tz_suffix(hour_start)
    if hour_end.date() == hour_start.date():
        return (
            f'{hour_start.strftime("%Y-%m-%dT%H:%M")}-'
            f'{hour_end.strftime("%H:%M")}{timezone_suffix}'
        )
    return (
        f'{hour_start.strftime("%Y-%m-%dT%H:%M")}-'
        f'{hour_end.strftime("%Y-%m-%dT%H:%M")}{timezone_suffix}'
    )


def format_newest_first_inclusive_hour_window_range(
    earliest_hour_start: datetime,
    earliest_hour_end: datetime,
    latest_hour_start: datetime,
    latest_hour_end: datetime,
) -> str:
    """Bracketed inclusive hour-window range with newest finished hour first."""
    return (
        f'[{format_local_hour_window_label(latest_hour_start, latest_hour_end)}, '
        f'{format_local_hour_window_label(earliest_hour_start, earliest_hour_end)}]'
    )


class PopulateProgress:
    """Day-level milestones, compact tqdm, and heartbeat lines when work goes quiet."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        day_only: bool | None = None,
        line_mode: bool | None = None,
        verbose: bool | None = None,
        label: str = 'populate',
    ) -> None:
        self.enabled = plain_populate_progress_enabled() if enabled is None else enabled
        self.day_only = populate_day_only_progress_enabled() if day_only is None else day_only
        self.line_mode = populate_line_progress_enabled() if line_mode is None else line_mode
        self.verbose = populate_verbose_progress_enabled() if verbose is None else verbose
        self._label = label.strip() or 'populate'
        self._phase_started_at: float | None = None
        self._day_started_at: float | None = None
        self._scope_label: str | None = None
        self._month_label: str | None = None
        self._day_iso: str | None = None
        self._activity_label = self._label
        self._last_activity_at = time.monotonic()
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_interval_sec = _heartbeat_interval_sec()
        self._stall_warn_sec = _stall_warn_sec()
        self._cache_collision_counts: dict[str, int] = {}
        self._step_once_keys: set[str] = set()
        self._tqdm_depth: int = 0
        self._active_meter_bar: Any | None = None

    def _refresh_active_meter_bar(self) -> None:
        if self._active_meter_bar is not None:
            self._active_meter_bar.refresh()

    @property
    def use_tqdm(self) -> bool:
        return self.enabled and not self.day_only and not self.line_mode

    def set_scope(
        self,
        *,
        scope: str | None = None,
        month: str | None = None,
        day: date | str | None = None,
        clear_day: bool = False,
    ) -> None:
        """Set month/day context prefixed on tqdm bars and stderr lines."""
        if scope is not None:
            self._scope_label = scope or None
        if month is not None:
            self._month_label = month or None
        if clear_day:
            self._day_iso = None
        elif day is not None:
            self._day_iso = day.isoformat() if isinstance(day, date) else (day or None)

    def set_chronological_scope_newest_first(
        self,
        *,
        earliest: str,
        latest: str,
        clear_day: bool = False,
    ) -> None:
        """Set scope tag ``latest..earliest`` for newest-first populate / ensure-on-read."""
        self.set_scope(
            scope=format_newest_first_scope_range(earliest, latest),
            clear_day=clear_day,
        )

    def scope_tag(self) -> str:
        if self._scope_label:
            return self._scope_label
        # Day work: date only (month is redundant on daily lines / tqdm).
        if self._day_iso:
            return self._day_iso
        if self._month_label:
            return self._month_label
        return ''

    def _emit_stderr_line(self, line: str) -> None:
        if self._tqdm_depth > 0:
            _tqdm_write(line)
        else:
            print(line, file=sys.stderr, flush=True)

    def _line(self, body: str) -> str:
        tag = self.scope_tag()
        if tag:
            return f'[{self._label}] [{tag}] {body}'
        return f'[{self._label}] {body}'

    def _scoped_desc(self, desc: str) -> str:
        tag = self.scope_tag()
        if not tag or desc.startswith(tag):
            return desc
        return f'{tag} {desc}'

    def touch(self, label: str | None = None) -> None:
        """Record activity so heartbeat / stall detection know work is progressing."""
        if label is not None:
            scoped = self._scoped_desc(label) if label else label
            self._activity_label = scoped
        self._last_activity_at = time.monotonic()

    def say(self, message: str, *, activity: bool = True) -> None:
        if not self.enabled:
            return
        body = message[len('[populate]'):].lstrip() if message.startswith('[populate]') else message
        self._emit_stderr_line(self._line(body))
        if activity:
            self.touch(body)

    def step(self, message: str) -> None:
        """Plain line before a long step that may not advance tqdm for a while."""
        self.touch(message)
        if self.enabled and not self.day_only:
            self._emit_stderr_line(self._line(f'→ {message}'))

    def step_once(self, key: str, message: str) -> None:
        """Emit a step line only the first time a nested flow reaches the same milestone."""
        normalized_key = str(key).strip()
        if not normalized_key or normalized_key in self._step_once_keys:
            return
        self._step_once_keys.add(normalized_key)
        self.step(message)

    @staticmethod
    def _short_neo_label(label: str) -> str:
        for prefix in _NEO_LABEL_PREFIXES:
            if label.startswith(prefix):
                return label[len(prefix):]
        return label

    def note_cache_collision(self, *, neo_label: str, cache_key_tail: str) -> None:
        """Recover from parallel-populate cache_key races (silent; optional DEBUG log)."""
        if not _log_cache_collisions():
            return
        short_label = self._short_neo_label(neo_label)
        self._cache_collision_counts[short_label] = (
            self._cache_collision_counts.get(short_label, 0) + 1
        )
        _log.debug(
            'populate cache collision recovered: %s …%s',
            short_label,
            cache_key_tail,
        )

    def flush_cache_collision_summary(self) -> None:
        """Drop collision counters; never emit populate progress lines for races."""
        if self._cache_collision_counts and _log_cache_collisions():
            total = sum(self._cache_collision_counts.values())
            by_type = ', '.join(
                f'{name}={count}'
                for name, count in sorted(self._cache_collision_counts.items())
            )
            _log.debug('populate cache collisions in phase: %s (%s)', total, by_type)
        self._cache_collision_counts.clear()

    def start_heartbeat(self) -> None:
        """Background thread: periodic lines when idle (non-tqdm populate only)."""
        if not self.enabled or self.day_only or self.use_tqdm:
            return
        if self._heartbeat_thread is not None:
            return
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name='populate-heartbeat',
            daemon=True,
        )
        self._heartbeat_thread.start()

    def stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=3.0)
            self._heartbeat_thread = None

    def _emit_heartbeat_if_idle(self) -> bool:
        """Emit a status line when no real progress recently; returns whether printed."""
        if self.use_tqdm:
            return False
        idle = time.monotonic() - self._last_activity_at
        if idle < self._heartbeat_interval_sec:
            return False
        message = (
            f'still working: {self._activity_label} (no progress line for {idle:.0f}s)'
        )
        if idle >= self._stall_warn_sec:
            message += ' — possible stall (IoT/Neo4j contention?)'
        self.say(message, activity=False)
        return True

    def _heartbeat_loop(self) -> None:
        poll = min(30.0, self._heartbeat_interval_sec / 3.0)
        while not self._heartbeat_stop.wait(poll):
            self._emit_heartbeat_if_idle()

    def phase(self, message: str) -> None:
        if self.day_only:
            return
        if self._phase_started_at is not None and self.enabled:
            self.flush_cache_collision_summary()
            elapsed = time.monotonic() - self._phase_started_at
            self.say(f'done ({elapsed:.1f}s)')
        self._phase_started_at = time.monotonic()
        self.touch(message)
        self.say(f'→ {message}')

    def day_begin(self, message: str) -> None:
        """Start a calendar-day block (closes any open phase/day timer first)."""
        self.finish()
        self._day_started_at = time.monotonic()
        self.touch(f'day {message}')
        self.say(f'day {message}')

    def day_done(self) -> None:
        """Close the current calendar-day block."""
        self.flush_cache_collision_summary()
        if self._day_started_at is not None and self.enabled:
            elapsed = time.monotonic() - self._day_started_at
            self.say(f'day done ({elapsed:.1f}s)')
        self._day_started_at = None
        self.touch('between days')

    def assets(self, asset_names: list[str], *, desc: str) -> Iterator[str]:
        """tqdm over asset names (nested under a family step)."""
        return self.iterate(
            asset_names,
            desc=desc,
            unit='asset',
            total=len(asset_names),
            leave=False,
            scope_desc=False,
        )

    def meter_bar(
        self,
        meter_names: list[str],
        *,
        desc: str,
        unit: str = 'meter',
    ) -> Iterator[tuple[int, str]]:
        """Outer meter tqdm (line 1) paired with ``period_bar`` (line 2) for each meter."""
        if not self.use_tqdm:
            for meter_index, meter_asset_name in enumerate(meter_names, start=1):
                self.touch(desc)
                yield meter_index, meter_asset_name
            return

        scoped_desc = self._scoped_desc(desc)
        self.touch(scoped_desc)
        _ensure_tqdm_terminal_ready()
        meter_bar = _comma_separated_tqdm(
            total=len(meter_names),
            desc=scoped_desc,
            unit=unit,
            **_tqdm_kwargs(position=0, leave=False),
        )
        self._active_meter_bar = meter_bar
        self._tqdm_depth = 1
        try:
            for meter_index, meter_asset_name in enumerate(meter_names, start=1):
                yield meter_index, meter_asset_name
                meter_bar.update(1)
                meter_bar.refresh()
        finally:
            meter_bar.close()
            self._active_meter_bar = None
            self._tqdm_depth = 0

    @contextmanager
    def period_bar(
        self,
        *,
        desc: str,
        total: int,
        unit: str = 'it',
        scope_desc: bool = False,
    ) -> Iterator[_PeriodBar]:
        """Manual nested period bar (days/hours) under the meter bar.

        Inner bars omit the scope prefix by default so nested lines stay short on Windows.
        """
        scoped_desc = self._scoped_desc(desc) if scope_desc else desc
        self.touch(scoped_desc)
        if not self.use_tqdm:
            yield _NullPeriodBar()
            return

        position = 1 if self._active_meter_bar is not None else self._tqdm_depth
        self._tqdm_depth += 1
        bar = _comma_separated_tqdm(
            total=total,
            desc=scoped_desc,
            unit=unit,
            **_tqdm_kwargs(position=position, leave=False),
        )
        period_progress: _PeriodBar = _RefreshingPeriodBar(bar, self)
        try:
            yield period_progress
        finally:
            bar.close()
            self._tqdm_depth -= 1
            self._refresh_active_meter_bar()

    def iterate(
        self,
        iterable: Iterable[_T],
        *,
        desc: str,
        unit: str = 'it',
        total: int | None = None,
        leave: bool = False,
        use_tqdm: bool | None = None,
        scope_desc: bool = True,
    ) -> Iterator[_T]:
        """Compact tqdm bar for inner loops; passthrough when verbose/minimal/disabled."""
        scoped_desc = self._scoped_desc(desc) if scope_desc else desc
        self.touch(scoped_desc)
        should_use_tqdm = self.use_tqdm if use_tqdm is None else (self.enabled and not self.day_only and use_tqdm)
        if not should_use_tqdm:
            for item in iterable:
                self.touch(scoped_desc)
                yield item
            return
        _ensure_tqdm_terminal_ready()
        position = self._tqdm_depth
        self._tqdm_depth += 1
        try:
            for item in _comma_separated_tqdm(
                iterable,
                desc=scoped_desc,
                unit=unit,
                total=total,
                **_tqdm_kwargs(position=position, leave=leave),
            ):
                self.touch(scoped_desc)
                yield item
        finally:
            self._tqdm_depth -= 1

    def tick(self, label: str, *, index: int, total: int, every: int = 25) -> None:
        if not self.enabled or not self.verbose or self.use_tqdm:
            return
        if index == 1 or index >= total or index % every == 0:
            self.say(f'  {label} {index}/{total}')

    def subphase(self, message: str) -> None:
        if self.enabled and self.verbose:
            self.say(f'    {message}')

    def iot_progress_desc(self, desc: str, *, multi_batch: bool = False) -> str | None:
        """Return a nested IoT tqdm label, or None when an outer bar already tracks work.

        In compact mode (``use_tqdm``), per-asset Find API lines are suppressed; only
        heartbeat labels refresh via ``touch``. Nested batch tqdm is kept when
        ``multi_batch`` (point count exceeds Find API chunk size).
        """
        if not self.enabled:
            return None
        if self.verbose:
            self.subphase(desc)
            return desc
        if self.use_tqdm and not multi_batch:
            self.touch(desc)
            return None
        self.touch(desc)
        return desc

    def asset(self, family: str, *, index: int, total: int, asset_name: str) -> None:
        if not self.enabled or not self.verbose:
            return
        every = 1 if total <= 20 else 5
        if index == 1 or index >= total or index % every == 0:
            self.say(f'    {family} {index}/{total}: {asset_name}')

    def finish(self) -> None:
        if self._phase_started_at is not None and self.enabled and not self.day_only:
            self.flush_cache_collision_summary()
            elapsed = time.monotonic() - self._phase_started_at
            self.say(f'done ({elapsed:.1f}s)')
        self._phase_started_at = None

    def print_plan(
        self,
        *,
        facility_name: str,
        facility_tz: Any,
        building_scope: str,
        from_date: date,
        to_date: date,
        days_newest_first: list[date],
    ) -> None:
        day_labels = ', '.join(day.isoformat() for day in days_newest_first)
        self.say(
            f'plan: {facility_name} building={building_scope} '
            f'tz={facility_tz} range={format_newest_first_scope_range(from_date.isoformat(), to_date.isoformat())} '
            f'({len(days_newest_first)} day(s), newest-first: {day_labels})',
        )
        if self.enabled and not self.day_only and not self.verbose:
            self.say(
                f'heartbeat every {self._heartbeat_interval_sec:.0f}s idle '
                f'(stall hint after {self._stall_warn_sec:.0f}s)',
            )

    def print_summary(self, summary: dict[str, Any]) -> None:
        self.flush_cache_collision_summary()
        self.say(
            f'finished in {summary.get("elapsed_seconds")}s — '
            f'work_units={summary.get("work_units_executed")}/{summary.get("work_units_total")}',
        )
        prepared = summary.get('prepared_counts') or {}
        if prepared:
            highlights = ', '.join(f'{key}={value}' for key, value in sorted(prepared.items()) if value)
            if highlights:
                self.say(f'counts: {highlights}')
