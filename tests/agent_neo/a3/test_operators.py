"""Operator laws, checked by seeded random search — no engine required for these."""


from __future__ import annotations

import random

import pytest

from agent_neo.a3 import (
    ABSENT,
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


def _fold(operator, values):
    acc = operator.lift(values[0])
    for v in values[1:]:
        acc = operator.combine(acc, operator.lift(v))
    return acc


@pytest.mark.parametrize('operator', ALL, ids=lambda o: type(o).__name__)
def test_every_operator_satisfies_the_protocol_and_declares_itself(operator: object) -> None:
    assert isinstance(operator, Operator)
    assert isinstance(operator.exact, bool) and isinstance(operator.partial_ok, bool) and operator.mergeable and operator.columns


def test_which_operators_may_fold_partially_and_which_are_exact() -> None:
    assert not Sum().partial_ok and not Count().partial_ok  # an undercount
    assert all(op.partial_ok for op in (Min(), Max(), Mean(), WeightedMean(), Proportion(), Percentile(0.5, ExactSketch)))  # an estimate
    assert all(op.exact for op in (Sum(), Min(), Max()))
    assert not any(op.exact for op in (Count(), Mean(), WeightedMean(), Proportion(), Percentile(0.5, ExactSketch)))


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


@pytest.mark.parametrize('operator', ALL, ids=lambda o: type(o).__name__)
def test_law_exact_operator_is_exactly_the_ones_whose_report_re_enters_as_the_accumulator(operator) -> None:
    rng = random.Random(5)
    values = _values(rng, operator, 6)
    left, right = _fold(operator, values[:2]), _fold(operator, values[2:])  # unequal groups: a mean of means is not the mean
    direct = operator.lower(operator.combine(left, right))
    if isinstance(operator, (WeightedMean, Proportion)):
        assert not operator.exact and not isinstance(operator.lower(left), operator.value_type)  # a ratio's report is not even a value it lifts
        return
    reentered = operator.lower(operator.combine(operator.lift(operator.lower(left)), operator.lift(operator.lower(right))))
    if operator.exact:
        assert reentered == pytest.approx(direct)
    elif isinstance(operator, Count):
        assert reentered == 2 and direct == 6  # a count of two counts counts two things
    else:
        assert not _close(reentered, direct)  # a mean of means; a median of two medians


@pytest.mark.parametrize('operator', ALL, ids=lambda o: type(o).__name__)
def test_law_bridge_round_trip_encode_decode_through_the_declared_columns(operator) -> None:
    rng = random.Random(6)
    acc = _fold(operator, _values(rng, operator, 5))
    encoded = operator.encode(acc)
    assert len(encoded) == len(operator.columns)
    assert _close(operator.lower(operator.decode(*encoded)), operator.lower(acc))
    if isinstance(operator, (Mean, WeightedMean)):
        assert encoded[0] == pytest.approx(operator.lower(acc))  # stored as (report, denominator): what stores already hold
        assert _close(operator.decode(*encoded), acc)


def test_count_and_ratios_lower_as_they_should() -> None:
    assert Count().lower(Count().lift(object())) == 1
    assert WeightedMean().lower(WeightedMean().lift((4.0, 2.0))) == pytest.approx(4.0)
    assert Proportion().lower(Proportion().lift((1.0, 4.0))) == pytest.approx(0.25)


def test_mean_of_a_fold_is_the_mean_of_all_leaves_not_the_mean_of_means() -> None:
    op = Mean()
    cheap, expensive = [1.0, 1.0, 1.0, 1.0], [9.0]
    mean_of_means = op.combine(op.lift(sum(cheap) / len(cheap)), op.lift(expensive[0]))
    assert op.lower(mean_of_means) == pytest.approx(5.0)  # what a naive re-average would report ...
    assert op.lower(_fold(op, cheap + expensive)) == pytest.approx(2.6)  # ... and the truth the fold over leaves gives


def test_law_empty_fold_is_absent_an_undefined_report_lowers_to_absent_not_zero() -> None:
    assert Mean().lower(RatioAccumulator(0.0, 0.0)) is ABSENT
    assert WeightedMean().lower(WeightedMean().lift((5.0, 0.0))) is ABSENT  # a zero-weight child is a data condition, not an error
    assert Mean().decode(None, 0.0) == RatioAccumulator(0.0, 0.0) and Mean().encode(RatioAccumulator(0.0, 0.0)) == (None, 0.0)


def test_percentile_without_an_accumulator_is_not_mergeable_and_refuses_direct_use() -> None:
    bare = Percentile(0.95)
    assert not bare.mergeable and not bare.exact
    with pytest.raises(IllegalOperatorUse):
        bare.lift(1.0)
    with pytest.raises(IllegalOperatorUse):
        bare.combine(object(), object())


def test_percentile_with_an_exact_multiset_rolls_up_and_agrees_with_the_direct_quantile() -> None:
    op = Percentile(0.5, ExactSketch)
    rng = random.Random(4)
    values = [rng.uniform(0, 100) for _ in range(51)]
    half = len(values) // 2
    assert op.lower(op.combine(_fold(op, values[:half]), _fold(op, values[half:]))) == ExactSketch(tuple(values)).quantile(0.5)


def test_registry_accepts_conforming_operators_and_refuses_the_rest() -> None:
    registry = OperatorRegistry()
    rng = random.Random(7)
    for name, op in (('sum', Sum()), ('count', Count()), ('mean', Mean()), ('wmean', WeightedMean()), ('share', Proportion()), ('p50', Percentile(0.5, ExactSketch))):
        registry.register(name, op, samples=_values(rng, op, 5))  # the laws run at registration
    assert registry.names() == ('count', 'mean', 'p50', 'share', 'sum', 'wmean') and 'sum' in registry and registry.get('sum') == Sum()
    assert registry.name_of(Mean()) == 'mean' and registry.name_of(Max()) is None
    with pytest.raises(IllegalOperatorUse, match='holistic'):
        registry.register('p95', Percentile(0.95))
    with pytest.raises(IllegalOperatorUse, match='already registered'):
        registry.register('sum', Sum())
    with pytest.raises(IllegalOperatorUse, match='factorization'):
        registry.register('bad', object())

    class _Undeclared:
        mergeable = True
        exact = True
        partial_ok = True
        value_type = float

        def lift(self, v): return v
        def combine(self, a, b): return a
        def lower(self, a): return a
        def encode(self, a): return (a,)
        def decode(self, a): return a

    with pytest.raises(IllegalOperatorUse, match='columns'):
        registry.register('undeclared', _Undeclared())

    class _LeftBiased(_Undeclared):  # combine(a, b) == a: associative, not commutative
        columns = ('value',)

    with pytest.raises(IllegalOperatorUse, match='commutative'):
        registry.register('left', _LeftBiased(), samples=[1.0, 2.0, 3.0])

    class _FalselyExact(Mean):  # a mean that claims its report is its accumulator
        exact = True

    with pytest.raises(IllegalOperatorUse, match='exact'):
        registry.register('liar', _FalselyExact(), samples=[1.0, 2.0, 9.0])
    with pytest.raises(KeyError):
        registry.get('nope')
