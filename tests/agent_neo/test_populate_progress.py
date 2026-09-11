"""Tests for populate progress modes (compact tqdm, day-only, verbose)."""


from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from agent_neo.analytical_product.populate_progress import (
    PopulateProgress,
    format_local_hour_window_label,
    format_newest_first_inclusive_hour_window_range,
    format_newest_first_inclusive_range,
    format_newest_first_scope_range,
)


_MONOTONIC = 'agent_neo.analytical_product.populate_progress.time.monotonic'

# A half-hour-offset zone, so the formatters are exercised against an offset
# that is not a whole number of hours.
SCOPE_TZ = ZoneInfo('Asia/Kolkata')


def test_format_newest_first_scope_range() -> None:
    assert format_newest_first_scope_range('2025-01-01', '2026-05-30') == '2026-05-30..2025-01-01'


def test_format_newest_first_inclusive_range() -> None:
    assert format_newest_first_inclusive_range('2025-01-01', '2026-05-30') == '[2026-05-30, 2025-01-01]'


def test_format_local_hour_window_label() -> None:
    hour_start = datetime(2026, 5, 31, 9, 0, tzinfo=SCOPE_TZ)
    hour_end = datetime(2026, 5, 31, 10, 0, tzinfo=SCOPE_TZ)
    assert format_local_hour_window_label(hour_start, hour_end) == '2026-05-31T09:00-10:00+05:30'


def test_format_newest_first_inclusive_hour_window_range() -> None:
    earliest_start = datetime(2026, 1, 1, 0, 0, tzinfo=SCOPE_TZ)
    earliest_end = datetime(2026, 1, 1, 1, 0, tzinfo=SCOPE_TZ)
    latest_start = datetime(2026, 5, 31, 9, 0, tzinfo=SCOPE_TZ)
    latest_end = datetime(2026, 5, 31, 10, 0, tzinfo=SCOPE_TZ)
    assert format_newest_first_inclusive_hour_window_range(
        earliest_start,
        earliest_end,
        latest_start,
        latest_end,
    ) == '[2026-05-31T09:00-10:00+05:30, 2026-01-01T00:00-01:00+05:30]'


def test_set_chronological_scope_newest_first(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=False, verbose=False)
    progress.set_chronological_scope_newest_first(
        earliest='2025-01-01',
        latest='2026-05-30',
    )
    progress.step('daily kickoff')
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert '[2026-05-30..2025-01-01]' in captured.err


def test_day_only_suppresses_tick_subphase_and_phase(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=True)
    progress.phase('should not print')
    progress.tick('subjects', index=1, total=329, every=50)
    progress.subphase('fetch batch-1: 8 items x 1h')
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err == ''


def test_day_begin_and_day_done(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=True)
    with patch(_MONOTONIC, side_effect=[0.0, 0.0, 0.0, 12.5, 12.5, 12.5]):
        progress.day_begin('2026-05-23 (1/2 in 2026-05, newest-first)')
        progress.day_done()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert 'day 2026-05-23' in captured.err
    assert 'day done (12.5s)' in captured.err
    assert captured.err.startswith('[populate]')


def test_compact_default_suppresses_verbose_lines(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=False, verbose=False)
    assert progress.use_tqdm is True
    progress.tick('subjects', index=1, total=329, every=50)
    progress.subphase('fetch batch-1: 8 items x 1h')
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err == ''


def test_iterate_passthrough_when_progress_disabled(capsys: object) -> None:
    progress = PopulateProgress(enabled=False)
    assert list(progress.iterate(['a', 'b'], desc='hourly batch', total=2)) == ['a', 'b']
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err == ''


def test_verbose_emits_tick_and_subphase(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, verbose=True)
    assert progress.use_tqdm is True
    progress.tick('subjects', index=1, total=329, every=50)
    progress.subphase('fetch batch-1: 8 items x 1h')
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert 'subjects 1/329' not in captured.err
    assert 'fetch batch-1' in captured.err


def test_step_emits_tail_line(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=False, verbose=False)
    progress.set_scope(month='2026-05', day='2026-05-22')
    progress.step('hourly tail: derived-health')
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert '[2026-05-22]' in captured.err
    assert '2026-05 ·' not in captured.err
    assert 'tail: derived-health' in captured.err


def test_explicit_scope_overrides_day_prefix(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=False, verbose=False)
    progress.set_scope(scope='2026-05-22..2026-05-28', day='2026-05-22')
    progress.step('hourly kickoff')
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert '[2026-05-22..2026-05-28]' in captured.err
    assert '[2026-05-22] hourly' not in captured.err


def test_iterate_scopes_tqdm_desc(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=False, verbose=False)
    progress.set_scope(month='2026-04', day='2026-04-30')
    list(progress.iterate(['a'], desc='hourly batch', total=1))
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert '2026-04-30' in captured.err
    assert '2026-04 ·' not in captured.err
    assert 'hourly batch' in captured.err


def test_tqdm_uses_thousands_separators(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=False, verbose=False)
    with progress.period_bar(desc='subject hours', total=3610, unit='hour') as hour_bar:
        hour_bar.update(1216)
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert '1,216/3,610' in captured.err


def test_iterate_can_force_tqdm_in_verbose_mode(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, verbose=True)
    progress.set_scope(scope='2026-05-22..2026-05-28')
    list(progress.iterate(['a'], desc='subject hours', total=1, use_tqdm=True))
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert '2026-05-22..2026-05-28 subject hours' in captured.err
    assert '0/1' in captured.err or '1/1' in captured.err


def test_heartbeat_emits_when_idle(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=True, verbose=False)
    progress._heartbeat_interval_sec = 1.0
    progress._stall_warn_sec = 999.0
    with patch(_MONOTONIC, side_effect=[0.0, 120.0]):
        progress.touch('slow step')
        assert progress._emit_heartbeat_if_idle() is True
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert 'still working: slow step' in captured.err
    assert 'no progress line for 120s' in captured.err


def test_cache_collision_silent_on_stderr(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=False, verbose=False)
    for _ in range(5):
        progress.note_cache_collision(
            neo_label='ExampleApp_Analytical_DailyMetricSet',
            cache_key_tail='subject-1|daily|2026-05-01',
        )
    progress.flush_cache_collision_summary()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err == ''
    assert 'cache node already exists' not in captured.err
    assert 'parallel cache hits recovered' not in captured.err


def test_cache_collision_verbose_also_silent_on_stderr(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, verbose=True)
    progress.note_cache_collision(
        neo_label='ExampleApp_Analytical_DailyMetricSet',
        cache_key_tail='subject-1|daily',
    )
    progress.flush_cache_collision_summary()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err == ''
    assert 'cache node already exists' not in captured.err


def test_heartbeat_stall_hint(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=True, verbose=False)
    progress._heartbeat_interval_sec = 1.0
    progress._stall_warn_sec = 60.0
    with patch(_MONOTONIC, side_effect=[0.0, 200.0]):
        progress.touch('blocked')
        progress._emit_heartbeat_if_idle()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert 'possible stall' in captured.err


def test_heartbeat_suppressed_when_tqdm_active(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=False, verbose=False)
    assert progress.use_tqdm is True
    progress._heartbeat_interval_sec = 1.0
    with patch(_MONOTONIC, side_effect=[0.0, 200.0]):
        progress.touch('subjects')
        assert progress._emit_heartbeat_if_idle() is False
    progress.start_heartbeat()
    assert progress._heartbeat_thread is None
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err == ''


def test_verbose_heartbeat_emits_when_idle(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=True, verbose=True)
    progress._heartbeat_interval_sec = 1.0
    progress._stall_warn_sec = 999.0
    with patch(_MONOTONIC, side_effect=[0.0, 120.0]):
        progress.touch('subject fetch')
        assert progress._emit_heartbeat_if_idle() is True
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert 'still working: subject fetch' in captured.err
