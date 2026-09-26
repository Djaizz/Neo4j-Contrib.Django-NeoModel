from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from agent_neo.a3 import (
    Ask,
    Coordinate,
    GateOutcome,
    Identity,
    Instance,
    LifecycleStatus,
    LineageRef,
    RecomputeReason,
    RefuseReason,
    Verdict,
    freshness_gate,
    gate,
    is_mature,
    lineage_gate,
    maturity_gate,
)

NOW = datetime(2026, 5, 2, 10, 0, tzinfo=UTC)
END = datetime(2026, 5, 2, 0, 0, tzinfo=UTC)
LAG = timedelta(minutes=30)


def _instance(*, age: timedelta | None = timedelta(0), needs_redo: bool = False, lifecycle=LifecycleStatus.OFFICIAL, producing=LifecycleStatus.OFFICIAL, lineage=()) -> Instance:
    identity = Identity('P', Coordinate('site', 'zone', 'z1', 'daily', '2026-05-01'))
    return Instance(identity, {'v': 1.0}, computed_at=None if age is None else NOW - age, computed_by='P@r1', producing=producing,
                    lifecycle=lifecycle, needs_redo=needs_redo, lineage=tuple(lineage))


def _ask(**slots) -> Ask:
    return Ask('P', 'site', 'zone', 'z1', 'daily', **slots)


def test_maturity_is_lag_after_exclusive_end_and_none_disables_it() -> None:
    assert is_mature(exclusive_end=END, now=END + LAG, lag=LAG)
    assert not is_mature(exclusive_end=END, now=END + LAG - timedelta(seconds=1), lag=LAG)
    assert is_mature(exclusive_end=END, now=END - timedelta(days=1), lag=None)
    refusal = maturity_gate(exclusive_end=END, now=END, lag=LAG)
    assert refusal is not None and refusal.reason is RefuseReason.IMMATURE_WINDOW and refusal.context['mature_at'] == END + LAG


def test_freshness_and_lineage_answer_different_questions() -> None:
    fresh_but_flagged = _instance(age=timedelta(minutes=1), needs_redo=True)
    old_but_valid = _instance(age=timedelta(days=3))
    assert lineage_gate(fresh_but_flagged) is RecomputeReason.NEEDS_REDO
    assert freshness_gate(fresh_but_flagged, max_staleness=timedelta(hours=1), now=NOW) is None
    assert lineage_gate(old_but_valid) is None
    assert freshness_gate(old_but_valid, max_staleness=timedelta(hours=1), now=NOW) is RecomputeReason.STALE
    assert freshness_gate(old_but_valid, max_staleness=None, now=NOW) is None
    assert lineage_gate(_instance(lifecycle=LifecycleStatus.RETIRED)) is RecomputeReason.NOT_CURRENT
    assert freshness_gate(_instance(age=None), max_staleness=timedelta(hours=1), now=NOW) is RecomputeReason.STALE  # unknown age is stale
    assert freshness_gate(_instance(age=None), max_staleness=None, now=NOW) is None


def test_law_lineage_from_facts() -> None:
    fresh = _instance(age=timedelta(minutes=1))
    assert lineage_gate(replace(fresh, producing=None)) is RecomputeReason.NO_RECIPE
    assert lineage_gate(replace(fresh, producing=LifecycleStatus.RETIRED)) is RecomputeReason.RETIRED_RECIPE
    ok = LineageRef('leaf-1', updated_at=NOW - timedelta(hours=2))
    assert lineage_gate(replace(fresh, lineage=(ok,))) is None
    assert lineage_gate(replace(fresh, lineage=(ok, LineageRef('leaf-2', lifecycle=LifecycleStatus.RETIRED)))) is RecomputeReason.UPSTREAM_INVALID
    assert lineage_gate(replace(fresh, lineage=(ok, LineageRef('leaf-3', needs_redo=True)))) is RecomputeReason.UPSTREAM_INVALID
    assert lineage_gate(replace(fresh, lineage=(ok, LineageRef('leaf-4', updated_at=NOW)))) is RecomputeReason.INPUT_CHANGED  # changed after computed_at
    assert lineage_gate(replace(fresh, age=None) if False else replace(fresh, computed_at=None, lineage=(LineageRef('leaf-5', updated_at=NOW),))) is None  # unknown age: drift undecidable, left to freshness


def test_gate_order_immature_then_absent_then_lineage_then_freshness_then_serve() -> None:
    ask = _ask(max_staleness=timedelta(hours=1), maturity_lag=LAG)
    good = _instance(age=timedelta(minutes=5))
    immature = gate(good, ask, now=END + timedelta(minutes=10), exclusive_end=END)
    assert immature.verdict is Verdict.REFUSE and immature.refusal.reason is RefuseReason.IMMATURE_WINDOW
    assert gate(None, ask, now=NOW, exclusive_end=END) == GateOutcome.recompute(RecomputeReason.NEEDS_REDO)
    stale_and_flagged = _instance(age=timedelta(days=1), needs_redo=True)
    assert gate(stale_and_flagged, ask, now=NOW, exclusive_end=END).recompute_reason is RecomputeReason.NEEDS_REDO  # lineage before age
    assert gate(_instance(age=timedelta(days=1)), ask, now=NOW, exclusive_end=END).recompute_reason is RecomputeReason.STALE
    assert gate(good, ask, now=NOW, exclusive_end=END) == GateOutcome.serve()
    assert gate(good, _ask(), now=NOW) == GateOutcome.serve()  # no slots: nothing gated but presence and lineage
