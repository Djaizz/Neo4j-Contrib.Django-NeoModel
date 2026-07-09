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


def test_format_newest_first_scope_range() -> None:
    assert format_newest_first_scope_range('2025-01-01', '2026-05-30') == '2026-05-30..2025-01-01'


def test_format_newest_first_inclusive_range() -> None:
    assert format_newest_first_inclusive_range('2025-01-01', '2026-05-30') == '[2026-05-30, 2025-01-01]'


def test_format_local_hour_window_label() -> None:
    facility_tz = ZoneInfo('Asia/Kolkata')
    hour_start = datetime(2026, 5, 31, 9, 0, tzinfo=facility_tz)
    hour_end = datetime(2026, 5, 31, 10, 0, tzinfo=facility_tz)
    assert format_local_hour_window_label(hour_start, hour_end) == '2026-05-31T09:00-10:00+05:30'


def test_format_newest_first_inclusive_hour_window_range() -> None:
    facility_tz = ZoneInfo('Asia/Kolkata')
    earliest_start = datetime(2026, 1, 1, 0, 0, tzinfo=facility_tz)
    earliest_end = datetime(2026, 1, 1, 1, 0, tzinfo=facility_tz)
    latest_start = datetime(2026, 5, 31, 9, 0, tzinfo=facility_tz)
    latest_end = datetime(2026, 5, 31, 10, 0, tzinfo=facility_tz)
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
    progress.step('daily electricity kickoff')
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert '[2026-05-30..2025-01-01]' in captured.err


def test_iterate_nested_tqdm_depth() -> None:
    progress = PopulateProgress(enabled=True, day_only=False, verbose=False)
    assert progress._tqdm_depth == 0
    outer = progress.iterate(['m1', 'm2'], desc='electricity meters', unit='meter', total=2, leave=False)
    next(outer)
    assert progress._tqdm_depth == 1
    inner = progress.iterate(['2026-05-30', '2026-05-29'], desc='m1 days', unit='day', total=2, leave=False)
    next(inner)
    assert progress._tqdm_depth == 2
    list(inner)
    assert progress._tqdm_depth == 1
    list(outer)
    assert progress._tqdm_depth == 0


def test_period_bar_nested_under_meter_iterate() -> None:
    progress = PopulateProgress(enabled=True, day_only=False, verbose=False)
    progress.set_chronological_scope_newest_first(earliest='2025-01-01', latest='2026-05-30')
    for _meter_index, _meter_name in progress.meter_bar(['M1'], desc='electricity meters'):
        assert progress._tqdm_depth == 1
        with progress.period_bar(desc='M1 hours', total=3, unit='hour') as hour_bar:
            assert progress._tqdm_depth == 2
            hour_bar.update(1)
            hour_bar.set_postfix_str('2026-05-31T09:00-10:00')
    assert progress._tqdm_depth == 0


def test_day_only_suppresses_tick_subphase_and_phase(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=True)
    progress.phase('should not print')
    progress.tick('meters', index=1, total=329, every=50)
    progress.subphase('IoT AHU1: 8 points × 1h')
    progress.asset('HVAC hourly equipment', index=1, total=10, asset_name='9A_AHU1')
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err == ''


def test_day_begin_and_day_done(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=True)
    with patch(
        'forge_odb.analytical._engine.populate_progress.time.monotonic',
        side_effect=[0.0, 0.0, 0.0, 12.5, 12.5, 12.5],
    ):
        progress.day_begin('2026-05-23 (1/2 in 2026-05, newest-first)')
        progress.day_done()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert 'day 2026-05-23' in captured.err
    assert 'day done (12.5s)' in captured.err
    assert captured.err.startswith('[populate]')
    assert 'energy hourly' not in captured.err


def test_compact_default_suppresses_verbose_lines(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=False, verbose=False)
    assert progress.use_tqdm is True
    progress.tick('meters', index=1, total=329, every=50)
    progress.subphase('IoT AHU1: 8 points × 1h')
    progress.asset('HVAC hourly equipment', index=1, total=10, asset_name='9A_AHU1')
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err == ''


def test_iterate_passthrough_when_progress_disabled(capsys: object) -> None:
    progress = PopulateProgress(enabled=False)
    assert list(progress.iterate(['a', 'b'], desc='energy hourly', total=2)) == ['a', 'b']
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err == ''


def test_verbose_emits_tick_and_subphase(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, verbose=True)
    assert progress.use_tqdm is True
    progress.tick('meters', index=1, total=329, every=50)
    progress.subphase('IoT AHU1: 8 points × 1h')
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert 'meters 1/329' not in captured.err
    assert 'IoT AHU1' in captured.err


def test_step_emits_tail_line(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=False, verbose=False)
    progress.set_scope(month='2026-05', day='2026-05-22')
    progress.step('HVAC hourly tail: chiller_health')
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert '[2026-05-22]' in captured.err
    assert '2026-05 ·' not in captured.err
    assert 'tail: chiller_health' in captured.err


def test_explicit_scope_overrides_day_prefix(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=False, verbose=False)
    progress.set_scope(scope='2026-05-22..2026-05-28', day='2026-05-22')
    progress.step('hourly electricity kickoff')
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert '[2026-05-22..2026-05-28]' in captured.err
    assert '[2026-05-22] hourly' not in captured.err


def test_iterate_scopes_tqdm_desc(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=False, verbose=False)
    progress.set_scope(month='2026-04', day='2026-04-30')
    list(progress.iterate(['a'], desc='energy hourly', total=1))
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert '2026-04-30' in captured.err
    assert '2026-04 ·' not in captured.err
    assert 'energy hourly' in captured.err


def test_tqdm_uses_thousands_separators(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=False, verbose=False)
    with progress.period_bar(desc='meter hours', total=3610, unit='hour') as hour_bar:
        hour_bar.update(1216)
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert '1,216/3,610' in captured.err


def test_iterate_can_force_tqdm_in_verbose_mode(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, verbose=True)
    progress.set_scope(scope='2026-05-22..2026-05-28')
    list(progress.iterate(['a'], desc='meter hours', total=1, use_tqdm=True))
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert '2026-05-22..2026-05-28 meter hours' in captured.err
    assert '0/1' in captured.err or '1/1' in captured.err


def test_iot_progress_desc_compact_mode_suppresses_nested_desc(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=False, verbose=False)
    assert progress.iot_progress_desc('IoT 9A_3F_VAV07: 2 pts × 1h (60 min)') is None
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err == ''


def test_iot_progress_desc_compact_mode_allows_multi_batch(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=False, verbose=False)
    desc = progress.iot_progress_desc(
        '2026-05-19 energy IoT (329 pts)',
        multi_batch=True,
    )
    assert desc == '2026-05-19 energy IoT (329 pts)'
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err == ''


def test_iot_progress_desc_verbose_emits_subphase(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, verbose=True)
    desc = progress.iot_progress_desc('IoT 9A_AHU1: 8 pts × 24h (1440 min)')
    assert desc == 'IoT 9A_AHU1: 8 pts × 24h (1440 min)'
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert 'IoT 9A_AHU1' in captured.err


def test_heartbeat_emits_when_idle(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=True, verbose=False)
    progress._heartbeat_interval_sec = 1.0
    progress._stall_warn_sec = 999.0
    with patch('forge_odb.analytical._engine.populate_progress.time.monotonic', side_effect=[0.0, 120.0]):
        progress.touch('slow step')
        assert progress._emit_heartbeat_if_idle() is True
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert 'still working: slow step' in captured.err
    assert 'no progress line for 120s' in captured.err


def test_cache_collision_silent_on_stderr(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=False, verbose=False)
    for _ in range(5):
        progress.note_cache_collision(
            neo_label='ForgeODB_Analytical_HVACEquipmentOperationPeriodRollup',
            cache_key_tail='9A_AHU1|daily|2026-05-01',
        )
    progress.flush_cache_collision_summary()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err == ''
    assert 'cache node already exists' not in captured.err
    assert 'parallel cache hits recovered' not in captured.err


def test_cache_collision_verbose_also_silent_on_stderr(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, verbose=True)
    progress.note_cache_collision(
        neo_label='ForgeODB_Analytical_HVACEquipmentOperationPeriodRollup',
        cache_key_tail='9A_AHU1|daily',
    )
    progress.flush_cache_collision_summary()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err == ''
    assert 'cache node already exists' not in captured.err


def test_heartbeat_stall_hint(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=True, verbose=False)
    progress._heartbeat_interval_sec = 1.0
    progress._stall_warn_sec = 60.0
    with patch('forge_odb.analytical._engine.populate_progress.time.monotonic', side_effect=[0.0, 200.0]):
        progress.touch('blocked')
        progress._emit_heartbeat_if_idle()
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert 'possible stall' in captured.err


def test_heartbeat_suppressed_when_tqdm_active(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=False, verbose=False)
    assert progress.use_tqdm is True
    progress._heartbeat_interval_sec = 1.0
    with patch('forge_odb.analytical._engine.populate_progress.time.monotonic', side_effect=[0.0, 200.0]):
        progress.touch('electricity meters')
        assert progress._emit_heartbeat_if_idle() is False
    progress.start_heartbeat()
    assert progress._heartbeat_thread is None
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.err == ''


def test_verbose_heartbeat_emits_when_idle(capsys: object) -> None:
    progress = PopulateProgress(enabled=True, day_only=True, verbose=True)
    progress._heartbeat_interval_sec = 1.0
    progress._stall_warn_sec = 999.0
    with patch('forge_odb.analytical._engine.populate_progress.time.monotonic', side_effect=[0.0, 120.0]):
        progress.touch('meter fetch')
        assert progress._emit_heartbeat_if_idle() is True
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert 'still working: meter fetch' in captured.err
