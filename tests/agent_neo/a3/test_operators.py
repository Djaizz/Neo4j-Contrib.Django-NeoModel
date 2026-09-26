"""Operator laws, checked by seeded random search — no engine required for these."""


from __future__ import annotations

import random

import pytest

from agent_neo.a3 import (
    AggregateKind,
    Count,
    IllegalOperatorUse,
    Max,
    Mean,
    Min,
    Operator,
    OperatorRegistry,
    Percentile,
    Proportion,
    RatioAccumulator,
    Sum,
    WeightedMean,
)
from tests.agent_neo.a3.conftest import ExactSketch

SCALAR_OPERATORS = [Sum(), Count(), Min(), Max(), Mean(), Percentile(0.5, ExactSketch)]
PAIR_OPERATORS = [WeightedMean(), Proportion()]
ALL = SCALAR_OPERATORS + PAIR_OPERATORS


def _values(rng: random.Random, operator: object, n: int) -> list:
    if isinstance(operator, (WeightedMean, Proportion)):
        return [(rng.uniform(-50, 50), rng.uniform(0.1, 10)) for _ in range(n)]
    return [rng.uniform(-100, 100) for _ in range(n)]


def _close(a: object, b: object) -> bool:
    if isinstance(a, RatioAccumulator) and isinstance(b, RatioAccumulator):
        return _close(a.numerator, b.numerator) and _close(a.denominator, b.denominator)
    if isinstance(a, ExactSketch) and isinstance(b, ExactSketch):
        return sorted(a.values) == sorted(b.values)
    return a == pytest.approx(b, rel=1e-9, abs=1e-9)


@pytest.mark.parametrize('operator', ALL, ids=lambda o: type(o).__name__)
def test_every_operator_satisfies_the_protocol_and_declares_itself(operator: object) -> None:
    assert isinstance(operator, Operator)
    assert isinstance(operator.kind, AggregateKind) and isinstance(operator.partial_ok, bool) and operator.mergeable


def test_which_operators_may_fold_partially() -> None:
    assert not Sum().partial_ok and not Count().partial_ok  # an undercount
    assert all(op.partial_ok for op in (Min(), Max(), Mean(), WeightedMean(), Proportion(), Percentile(0.5, ExactSketch)))  # an estimate


@pytest.mark.parametrize('operator', ALL, ids=lambda o: type(o).__name__)
def test_law_combine_is_associative(operator) -> None:
    rng = random.Random(1)
    for _ in range(200):
        a, b, c = (operator.lift(v) for v in _values(rng, operator, 3))
        assert _close(operator.combine(a, operator.combine(b, c)), operator.combine(operator.combine(a, b), c))


@pytest.mark.parametrize('operator', ALL, ids=lambda o: type(o).__name__)
def test_law_combine_is_commutative(operator) -> None:
    rng = random.Random(2)
    for _ in range(200):
        a, b = (operator.lift(v) for v in _values(rng, operator, 2))
        assert _close(operator.combine(a, b), operator.combine(b, a))


@pytest.mark.parametrize('operator', [Sum(), Min(), Max(), Mean(), Percentile(0.5, ExactSketch)], ids=lambda o: type(o).__name__)
def test_law_lower_after_lift_is_the_identity_on_singletons(operator) -> None:
    rng = random.Random(3)
    for _ in range(100):
        v = rng.uniform(-100, 100)
        assert operator.lower(operator.lift(v)) == pytest.approx(v)


def test_count_and_ratios_lower_as_they_should() -> None:
    assert Count().lower(Count().lift(object())) == 1
    assert WeightedMean().lower(WeightedMean().lift((4.0, 2.0))) == pytest.approx(4.0)
    assert Proportion().lower(Proportion().lift((1.0, 4.0))) == pytest.approx(0.25)


def test_mean_of_a_fold_is_the_mean_of_all_leaves_not_the_mean_of_means() -> None:
    op = Mean()
    cheap, expensive = [1.0, 1.0, 1.0, 1.0], [9.0]
    mean_of_means = op.combine(op.lift(sum(cheap) / len(cheap)), op.lift(expensive[0]))
    assert op.lower(mean_of_means) == pytest.approx(5.0)  # what a naive re-average would report ...
    acc = op.lift(cheap[0])
    for v in cheap[1:] + expensive:
        acc = op.combine(acc, op.lift(v))
    assert op.lower(acc) == pytest.approx(2.6)  # ... and the truth the fold over leaves gives


def test_lowering_an_empty_ratio_is_illegal_use_not_zero() -> None:
    with pytest.raises(IllegalOperatorUse):
        Mean().lower(RatioAccumulator(0.0, 0.0))


def test_percentile_without_an_accumulator_is_not_mergeable_and_refuses_direct_use() -> None:
    bare = Percentile(0.95)
    assert bare.kind is AggregateKind.HOLISTIC and not bare.mergeable
    with pytest.raises(IllegalOperatorUse):
        bare.lift(1.0)
    with pytest.raises(IllegalOperatorUse):
        bare.combine(object(), object())


def test_percentile_with_an_exact_multiset_rolls_up_and_agrees_with_the_direct_quantile() -> None:
    op = Percentile(0.5, ExactSketch)
    rng = random.Random(4)
    values = [rng.uniform(0, 100) for _ in range(51)]
    half = len(values) // 2
    left = op.lift(values[0])
    for v in values[1:half]:
        left = op.combine(left, op.lift(v))
    right = op.lift(values[half])
    for v in values[half + 1:]:
        right = op.combine(right, op.lift(v))
    assert op.lower(op.combine(left, right)) == ExactSketch(tuple(values)).quantile(0.5)


def test_registry_accepts_conforming_operators_and_refuses_the_rest() -> None:
    registry = OperatorRegistry()
    registry.register('sum', Sum())
    registry.register('p50', Percentile(0.5, ExactSketch))
    assert registry.names() == ('p50', 'sum') and 'sum' in registry and registry.get('sum') == Sum()
    with pytest.raises(IllegalOperatorUse, match='holistic'):
        registry.register('p95', Percentile(0.95))
    with pytest.raises(IllegalOperatorUse, match='already registered'):
        registry.register('sum', Sum())
    with pytest.raises(IllegalOperatorUse, match='factorization'):
        registry.register('bad', object())

    class _Undeclared:
        mergeable = True

        def lift(self, v): return v
        def combine(self, a, b): return a
        def lower(self, a): return a

    with pytest.raises(IllegalOperatorUse, match='AggregateKind'):
        registry.register('undeclared', _Undeclared())
    with pytest.raises(KeyError):
        registry.get('nope')
