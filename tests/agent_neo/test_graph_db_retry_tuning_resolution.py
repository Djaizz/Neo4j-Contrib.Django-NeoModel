"""Tests that retry tuning is resolved at call time, not at ``def`` time.

This is a correctness contract, not a performance one. The documented way to tune
the cluster retry is to assign to the ``NEO4J_CLUSTER_LEADER_SWITCH_*`` module
globals — which is what a consumer's bootstrap does. While those values were bound
as parameter defaults, that assignment reached ``connect_db``'s log message and
nothing else: the retry loop kept using whatever the globals held at import. The
log announced a tuning that was not in force.
"""

from __future__ import annotations

import pytest

from agent_neo.graph_db._core import retry_neo4j_cluster_operation
import agent_neo.graph_db._core as graph_core


class _CountingTransientOperation:
    """Always fails transiently, and remembers how often it was asked."""

    def __init__(self) -> None:
        self.attempts = 0

    def __call__(self) -> None:
        self.attempts += 1
        raise OSError('no leader found')


def _reassign_globals(monkeypatch: pytest.MonkeyPatch, **tuning: float) -> None:
    """Reassign the module globals, the way a consumer's bootstrap does.

    Keyed by the parameter names the retry function exposes, so each test reads as
    "this knob, set this way, must be the one the loop uses".
    """
    for knob, value in tuning.items():
        monkeypatch.setattr(
            graph_core, f'NEO4J_CLUSTER_LEADER_SWITCH_{knob.upper()}', value,
        )


@pytest.fixture
def recorded_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Every delay the retry loop would have slept for, without sleeping."""
    sleeps: list[float] = []
    monkeypatch.setattr(graph_core.time, 'sleep', sleeps.append)
    return sleeps


def test_a_reassigned_max_attempts_global_reaches_the_retry_loop(
    monkeypatch: pytest.MonkeyPatch, recorded_sleeps: list[float],
) -> None:
    _reassign_globals(monkeypatch, max_attempts=7)
    operation = _CountingTransientOperation()

    with pytest.raises(OSError):
        retry_neo4j_cluster_operation(operation, description='tuning probe')

    assert operation.attempts == 7


def test_a_reassigned_delay_global_reaches_the_sleep(
    monkeypatch: pytest.MonkeyPatch, recorded_sleeps: list[float],
) -> None:
    _reassign_globals(monkeypatch, max_attempts=2, retry_delay_seconds=3.5)
    operation = _CountingTransientOperation()

    with pytest.raises(OSError):
        retry_neo4j_cluster_operation(operation, description='tuning probe')

    assert recorded_sleeps == [3.5]


def test_a_reassigned_backoff_and_ceiling_reach_the_delay_calculation(
    monkeypatch: pytest.MonkeyPatch, recorded_sleeps: list[float],
) -> None:
    _reassign_globals(
        monkeypatch,
        max_attempts=4,
        retry_delay_seconds=1.0,
        backoff_multiplier=10.0,
        max_retry_delay_seconds=25.0,
    )
    operation = _CountingTransientOperation()

    with pytest.raises(OSError):
        retry_neo4j_cluster_operation(operation, description='tuning probe')

    # 1.0, then 1.0 * 10 ** 1 = 10.0, then 1.0 * 10 ** 2 = 100.0 clamped to 25.0.
    assert recorded_sleeps == [1.0, 10.0, 25.0]


def test_an_explicit_argument_still_wins_over_the_global(
    monkeypatch: pytest.MonkeyPatch, recorded_sleeps: list[float],
) -> None:
    """Backward compatibility: a call site that passes tuning explicitly must keep
    getting exactly what it asked for."""
    _reassign_globals(monkeypatch, max_attempts=7, retry_delay_seconds=3.5)
    operation = _CountingTransientOperation()

    with pytest.raises(OSError):
        retry_neo4j_cluster_operation(
            operation,
            description='tuning probe',
            max_attempts=2,
            retry_delay_seconds=0.25,
        )

    assert operation.attempts == 2
    assert recorded_sleeps == [0.25]


def test_the_tuning_parameters_carry_no_bound_default() -> None:
    """A default other than ``None`` would be a value frozen at import.

    This is the pin: the bug was not a wrong number, it was reading the globals
    once, at ``def`` time. A future edit that restores a real default restores the
    bug silently, and every behavioural test above would still pass on a process
    that never reassigns the globals.
    """
    import inspect

    signature = inspect.signature(retry_neo4j_cluster_operation)
    for name in (
        'max_attempts',
        'retry_delay_seconds',
        'backoff_multiplier',
        'max_retry_delay_seconds',
    ):
        assert signature.parameters[name].default is None, name


def test_a_non_transient_error_is_not_retried_however_generous_the_tuning(
    monkeypatch: pytest.MonkeyPatch, recorded_sleeps: list[float],
) -> None:
    _reassign_globals(monkeypatch, max_attempts=7)
    calls = {'count': 0}

    def _fails_hard() -> None:
        calls['count'] += 1
        raise ValueError('bad cache key')

    with pytest.raises(ValueError):
        retry_neo4j_cluster_operation(_fails_hard, description='tuning probe')

    assert calls['count'] == 1
    assert recorded_sleeps == []
