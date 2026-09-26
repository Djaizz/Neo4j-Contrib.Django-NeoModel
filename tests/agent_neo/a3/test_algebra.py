"""The carrier laws in laws.py, executed."""


from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent_neo.a3 import (
    ABSENT,
    Carrier,
    Coordinate,
    Count,
    CoverageState,
    Dimension,
    Field,
    FieldRole,
    Identity,
    IllegalOperatorUse,
    Instance,
    KeyScheme,
    Max,
    Mean,
    Min,
    OnMissing,
    OperatorRegistry,
    Percentile,
    Refuse,
    RefuseReason,
    Sum,
    WeightedMean,
    carrier_from_instances,
    classify,
    diff,
    instances_from_carrier,
    join,
    lift,
    lower,
    map_cells,
    rank,
    rekey,
    restrict,
    roll,
    scale,
    shift,
    slice_cells,
    slice_refusal,
)
from tests.agent_neo.a3.conftest import (
    FAMILY,
    ExactSketch,
    coord,
    leaves,
    shift_of_hour,
    src,
)

REGISTRY = OperatorRegistry()
for _name, _op in (('sum', Sum()), ('count', Count()), ('min', Min()), ('max', Max()), ('mean', Mean()), ('wmean', WeightedMean()), ('p50', Percentile(0.5, ExactSketch))):
    REGISTRY.register(_name, _op)


def _ok(result):
    assert not isinstance(result, Refuse), result
    return result


def _acc(carrier: Carrier[float], operator) -> Carrier:
    return _ok(lift(carrier, operator))


def _same(a: Carrier, b: Carrier, *, provenance: bool = True) -> None:
    assert a.expected == b.expected and set(a.cells) == set(b.cells)
    for c in a.cells:
        x, y = a.cells[c], b.cells[c]
        if hasattr(x, 'numerator'):
            assert (x.numerator, x.denominator) == pytest.approx((y.numerator, y.denominator))
        elif isinstance(x, ExactSketch):
            assert sorted(x.values) == sorted(y.values)
        else:
            assert x == pytest.approx(y)
        assert not provenance or a.sources(c) == b.sources(c)


F1H1 = Coordinate('site', 'floor', 'f1', 'hourly', 'h1')
F2H1 = Coordinate('site', 'floor', 'f2', 'hourly', 'h1')
TOP = Coordinate('site', 'building', 'b1', 'monthly', 'm1')


# ---------------------------------------------------------------------------
# Carrier basics, tags, Absent
# ---------------------------------------------------------------------------


def test_carrier_refuses_cells_outside_its_expected_set() -> None:
    with pytest.raises(ValueError):
        Carrier({coord('z1', 'h1'): 1.0}, frozenset())


def test_absent_is_the_answer_for_a_missing_cell_and_coverage_is_derived() -> None:
    c = Carrier({coord('z1', 'h1'): 1.0}, frozenset({coord('z1', 'h1'), coord('z1', 'h2')}))
    assert c.get(coord('z1', 'h2')) is ABSENT and c.missing == {coord('z1', 'h2')} and not ABSENT
    assert c.coverage().state(coord('z1', 'h2')) is CoverageState.MISSING and c.coverage().state(coord('z1', 'h1')) is CoverageState.KNOWN
    assert not c.coverage().complete and leaves().coverage().complete and leaves().is_leaf


def test_law_tag_guards_fold(space) -> None:
    values = leaves()
    assert roll(values, dimension=Dimension.SUBJECT, to_level='floor', lattice=space).reason is RefuseReason.ILL_TYPED_ROLL
    acc = _acc(values, Sum())
    assert lift(acc, Mean()).reason is RefuseReason.ILL_TYPED_ROLL
    for refused in (map_cells(acc, lambda v: v), join(acc, values), scale(acc, 2.0), rank(acc), lower(values)):
        assert refused.reason is RefuseReason.UNSUPPORTED_COMPOSITION
    lowered = _ok(lower(acc))
    assert lowered.lowered_from == ('Sum',) and set(lowered.cells) == set(values.cells)
    assert all(lowered.cells[c] == pytest.approx(values.cells[c]) for c in values.cells)


def test_law_reported_reentry_refuses_a_mean_of_means(space) -> None:
    means = _ok(lower(_ok(roll(_acc(leaves(), Mean()), dimension=Dimension.SUBJECT, to_level='floor', lattice=space))))
    again = lift(means, Mean())  # a mean of means, refused at the type level
    assert again.reason is RefuseReason.ILL_TYPED_ROLL and 'a Mean over Mean reports is not a Mean' in again.detail
    assert _ok(lift(means, Sum())).lowered_from == ('Mean',)  # a sum of floor means is a different quantity, not a double application
    joined = _ok(join(_ok(scale(means, 2.0)), _ok(map_cells(means, abs))))
    assert joined.lowered_from == ('Sum',) or joined.lowered_from == ('Mean',)
    assert _ok(lift(joined, WeightedMean())).lowered_from == ('Mean',)  # weighting reported means is a new quantity; the history rides along


def test_law_holistic_needs_accumulator() -> None:
    assert lift(leaves(), Percentile(0.95)).reason is RefuseReason.NO_MERGEABLE_ACCUMULATOR
    assert not isinstance(lift(leaves(), Percentile(0.95, ExactSketch)), Refuse)


# ---------------------------------------------------------------------------
# Roll: partition, double count, empty, partial
# ---------------------------------------------------------------------------


def test_roll_folds_children_into_parents_with_provenance(space) -> None:
    floors = _ok(roll(_acc(leaves(), Sum()), dimension=Dimension.SUBJECT, to_level='floor', lattice=space))
    assert floors.cells[F1H1] == pytest.approx(leaves().cells[coord('z1', 'h1')] + leaves().cells[coord('z2', 'h1')])
    assert floors.sources(F1H1) == {src('z1', 'h1'), src('z2', 'h1')} and floors.coverage().complete and len(floors) == 8


def test_law_roll_requires_partition(space) -> None:
    partial = leaves(zones=('z1', 'z3'))  # z2 was never asked for: f1 is incomplete, f2 complete
    acc = _acc(partial, Sum())
    refused = roll(acc, dimension=Dimension.SUBJECT, to_level='floor', lattice=space)
    assert isinstance(refused, Refuse) and refused.reason is RefuseReason.INCOMPLETE_PARTITION
    assert refused.context['missing'] == {coord('z2', refused.context['parent'].period_anchor)}
    absent = _ok(roll(acc, dimension=Dimension.SUBJECT, to_level='floor', lattice=space, on_missing=OnMissing.ABSENT))
    assert F1H1 in absent.expected and F1H1 not in absent.cells and absent.gaps[F1H1] == {coord('z2', 'h1')} and F2H1 in absent.cells
    assert absent.coverage().state(F1H1) is CoverageState.MISSING


def test_law_partial_is_estimate(space) -> None:
    partial = leaves(zones=('z1', 'z3'))
    assert roll(_acc(partial, Sum()), dimension=Dimension.SUBJECT, to_level='floor', lattice=space, on_missing=OnMissing.PARTIAL).reason is RefuseReason.INCOMPLETE_PARTITION
    est = _ok(roll(_acc(partial, Mean()), dimension=Dimension.SUBJECT, to_level='floor', lattice=space, on_missing=OnMissing.PARTIAL))
    assert _ok(lower(est)).cells[F1H1] == pytest.approx(partial.cells[coord('z1', 'h1')])  # the one present zone
    assert est.gaps[F1H1] == {coord('z2', 'h1')} and est.sources(F1H1) == {src('z1', 'h1')}


def test_law_roll_refuses_double_count(overlapping_space) -> None:
    acc = _acc(leaves(), Sum())
    refused = roll(acc, dimension=Dimension.SUBJECT, to_level='floor', lattice=overlapping_space)
    assert isinstance(refused, Refuse) and refused.reason is RefuseReason.DOUBLE_COUNTED and refused.context['parents'] == {'f1', 'f2'}
    for policy in (OnMissing.ABSENT, OnMissing.PARTIAL):  # a lattice that is not a partition is not missing data: no policy folds it
        assert roll(_acc(leaves(), Mean()), dimension=Dimension.SUBJECT, to_level='floor', lattice=overlapping_space, on_missing=policy).reason is RefuseReason.DOUBLE_COUNTED


def test_law_empty_fold_is_absent_for_every_operator(space) -> None:
    every = leaves()
    only_z3_present = Carrier({c: v for c, v in every.cells.items() if c.subject_key == 'z3'}, every.expected)
    for op in (Sum(), Mean(), Min(), Max()):
        lenient = _ok(roll(_acc(only_z3_present, op), dimension=Dimension.SUBJECT, to_level='floor', lattice=space, on_missing=OnMissing.ABSENT))
        assert lenient.get(F1H1) is ABSENT and F1H1 in lenient.expected and lenient.gaps[F1H1] == {coord('z1', 'h1'), coord('z2', 'h1')}
    only_z3 = leaves(zones=('z3',))  # the ask was about z3 alone: f1 is not part of the question
    floors = _ok(roll(_acc(only_z3, Sum()), dimension=Dimension.SUBJECT, to_level='floor', lattice=space))
    assert {c.subject_key for c in floors.expected} == {'f2'} and floors.coverage().complete


def test_roll_refuses_mixed_levels_and_lattice_gaps(space) -> None:
    mixed = Carrier.of({coord('z1', 'h1'): 1.0, F1H1: 2.0})
    assert roll(_acc(mixed, Sum()), dimension=Dimension.SUBJECT, to_level='building', lattice=space).reason is RefuseReason.UNSUPPORTED_COMPOSITION
    assert roll(_acc(Carrier.of({coord('z9', 'h1'): 1.0}), Sum()), dimension=Dimension.SUBJECT, to_level='floor', lattice=space).reason is RefuseReason.UNSUPPORTED_COMPOSITION


# ---------------------------------------------------------------------------
# Commutation laws
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('op', [Sum(), Mean(), Min(), Max(), Percentile(0.5, ExactSketch)], ids=lambda o: type(o).__name__)
@pytest.mark.parametrize('policy', list(OnMissing), ids=lambda p: p.value)
@pytest.mark.parametrize('zones', [('z1', 'z2', 'z3'), ('z1', 'z3')], ids=['complete', 'z2-missing'])
def test_law_roll_dimension_commute(space, time, op, policy, zones) -> None:
    if policy is OnMissing.PARTIAL and not op.partial_ok:
        pytest.skip('partial folds are refused for this operator by law')
    acc = _acc(leaves(zones=zones), op)

    def both(first, second):
        out = roll(acc, dimension=first[0], to_level=first[1], lattice=first[2], on_missing=policy)
        return out if isinstance(out, Refuse) else roll(out, dimension=second[0], to_level=second[1], lattice=second[2], on_missing=policy)

    s, t = (Dimension.SUBJECT, 'building', space), (Dimension.PERIOD, 'monthly', time)
    a, b = both(s, t), both(t, s)
    if isinstance(a, Refuse) or isinstance(b, Refuse):
        assert isinstance(a, Refuse) and isinstance(b, Refuse) and a.reason is b.reason is RefuseReason.INCOMPLETE_PARTITION
        assert policy is OnMissing.REFUSE and zones != ('z1', 'z2', 'z3')
        return
    _same(a, b)
    if zones == ('z1', 'z2', 'z3'):
        assert a.sources(TOP) == {Identity(FAMILY, c) for c in leaves().cells} and _ok(lower(a)).cells[TOP] == pytest.approx(_ok(lower(b)).cells[TOP])
    elif policy is OnMissing.ABSENT:
        assert a.get(TOP) is ABSENT  # one missing leaf makes the top absent, whichever way you roll
    else:
        assert a.sources(TOP) == {Identity(FAMILY, c) for c in leaves(zones=zones).cells}  # a partial estimate over exactly the present leaves


def test_weighted_mean_rolls_as_a_true_weighted_mean(space) -> None:
    pairs = Carrier.of({coord('z1', 'h1'): (10.0, 1.0), coord('z2', 'h1'): (20.0, 3.0), coord('z3', 'h1'): (0.0, 1.0)})
    b = _ok(roll(_acc(pairs, WeightedMean()), dimension=Dimension.SUBJECT, to_level='building', lattice=space))
    assert _ok(lower(b)).cells[Coordinate('site', 'building', 'b1', 'hourly', 'h1')] == pytest.approx((10 + 60 + 0) / 5)


def test_law_slice_commutes_with_roll_when_the_classification_is_constant_within_each_parent(space) -> None:
    acc = _acc(leaves(shift=True), Sum())
    a = _ok(roll(slice_cells(acc, shift='day'), dimension=Dimension.SUBJECT, to_level='floor', lattice=space))
    b = slice_cells(_ok(roll(acc, dimension=Dimension.SUBJECT, to_level='floor', lattice=space)), shift='day')
    _same(a, b)
    assert all(c.classification('shift') == 'day' for c in a.cells) and len(a) == 4


def test_law_classify_is_key_when_the_classification_varies_across_a_parents_children(space) -> None:
    # z2 works the night shift at h1 while z1 and z3 work days: a per-shift floor total must not call z2 a gap
    assign = lambda c: 'night' if (c.subject_key, c.period_anchor) == ('z2', 'h1') else shift_of_hour(c.period_anchor)
    acc = _ok(classify(_acc(leaves(), Sum()), 'shift', assign))
    bound = {'shift': assign}
    floors = _ok(roll(acc, dimension=Dimension.SUBJECT, to_level='floor', lattice=space, classifiers=bound))  # REFUSE policy, and it succeeds
    day, night = F1H1.with_classifications(shift='day'), F1H1.with_classifications(shift='night')
    assert floors.cells[day] == pytest.approx(leaves().cells[coord('z1', 'h1')]) and floors.sources(day) == {src('z1', 'h1')}  # the stored leaf, unclassified
    assert floors.cells[night] == pytest.approx(leaves().cells[coord('z2', 'h1')])
    # without the classifier the roll cannot know that (z2, h1, day) does not exist: it refuses rather than guesses, in either order
    assert roll(acc, dimension=Dimension.SUBJECT, to_level='floor', lattice=space).reason is RefuseReason.INCOMPLETE_PARTITION
    assert roll(slice_cells(acc, shift='day'), dimension=Dimension.SUBJECT, to_level='floor', lattice=space).reason is RefuseReason.INCOMPLETE_PARTITION
    # with it, the denominator is intrinsic and slicing commutes with rolling
    _same(_ok(roll(slice_cells(acc, shift='day'), dimension=Dimension.SUBJECT, to_level='floor', lattice=space, classifiers=bound)), _ok(slice_cells(floors, shift='day')))
    assert classify(acc, 'shift', assign).reason is RefuseReason.UNSUPPORTED_COMPOSITION  # already classified
    # a coordinate that carries a value the classifier would not assign it folds into nothing
    mislabelled = _ok(classify(_acc(leaves(), Sum()), 'shift', lambda c: 'day'))
    refused = roll(mislabelled, dimension=Dimension.SUBJECT, to_level='floor', lattice=space, classifiers={'shift': lambda c: shift_of_hour(c.period_anchor)})
    assert refused.reason is RefuseReason.UNSUPPORTED_COMPOSITION and refused.context['classification'] == 'shift'


# ---------------------------------------------------------------------------
# Join, shift, and the derived vocabulary
# ---------------------------------------------------------------------------


def test_law_join_inner_cells_union_expected_and_derived_by_expansion() -> None:
    a, b = leaves(seed=1), leaves(seed=2, zones=('z1', 'z2'))
    j = _ok(join(a, b))
    assert set(j.cells) == set(b.cells) and all(j.cells[c] == (a.cells[c], b.cells[c]) for c in j.cells)
    assert j.expected == a.expected and j.missing == {c for c in a.cells if c.subject_key == 'z3'}  # b never had z3: a gap of the join, not a vanished coordinate
    _same(_ok(scale(a, 2.5)), _ok(map_cells(a, lambda v: v * 2.5)))
    _same(_ok(diff(a, b)), _ok(map_cells(j, lambda p: p[0] - p[1])))
    _same(slice_cells(leaves(shift=True), shift='day'), restrict(leaves(shift=True), lambda c: c.classification('shift') == 'day'))
    assert _ok(scale(a, {c: 0.5 for c in a.cells})).cells == {c: v * 0.5 for c, v in a.cells.items()}
    assert scale(a, {}).reason is RefuseReason.UNSUPPORTED_COMPOSITION  # no silent 1.0
    assert [v for _, v in _ok(rank(a))] == sorted(a.cells.values(), reverse=True)


def test_law_shift_aligns_a_baseline_for_period_over_period() -> None:
    this, last = leaves(seed=5), leaves(seed=6)
    nxt = {'h1': 'h2', 'h2': 'h3', 'h3': 'h4', 'h4': 'h5'}
    moved = _ok(shift(last, Dimension.PERIOD, nxt.__getitem__))
    d = _ok(diff(this, moved))
    assert d.cells[coord('z1', 'h2')] == pytest.approx(this.cells[coord('z1', 'h2')] - last.cells[coord('z1', 'h1')])
    assert {coord('z1', 'h1'), coord('z1', 'h5')} <= d.missing  # no baseline for h1, nothing to compare at h5: gaps of the join, still visible
    assert moved.sources(coord('z1', 'h2')) == {src('z1', 'h1')}  # provenance points at where the value really came from
    assert shift(last, Dimension.PERIOD, lambda k: 'h1').reason is RefuseReason.UNSUPPORTED_COMPOSITION  # not injective


def test_law_reported_reentry(space, time) -> None:
    def floors(op):
        return _ok(lower(_ok(roll(_acc(leaves(), op), dimension=Dimension.SUBJECT, to_level='floor', lattice=space))))

    # refused: an inexact operator over its own reports
    for op in (Mean(), Count(), Percentile(0.5, ExactSketch)):
        assert lift(floors(op), op).reason is RefuseReason.ILL_TYPED_ROLL, op
    # allowed and equal to rolling further: an exact operator over its own reports
    for op in (Sum(), Max(), Min()):
        via_reports = _ok(lower(_ok(roll(_ok(lift(floors(op), op)), dimension=Dimension.SUBJECT, to_level='building', lattice=space))))
        direct = _ok(lower(_ok(roll(_acc(leaves(), op), dimension=Dimension.SUBJECT, to_level='building', lattice=space))))
        _same(via_reports, direct)
        assert via_reports.lowered_from == (type(op).__name__, type(op).__name__)  # the history is kept, not cleared
    # allowed: a change of unit of analysis — the mean of daily totals, the maximum of daily means
    daily_totals = _ok(lower(_ok(roll(_acc(leaves(), Sum()), dimension=Dimension.PERIOD, to_level='daily', lattice=time))))
    mean_daily_total = _ok(lower(_ok(roll(_ok(lift(daily_totals, Mean())), dimension=Dimension.PERIOD, to_level='monthly', lattice=time))))
    z1m1 = Coordinate('site', 'zone', 'z1', 'monthly', 'm1')
    assert mean_daily_total.cells[z1m1] == pytest.approx(sum(leaves().cells[coord('z1', h)] for h in ('h1', 'h2', 'h3', 'h4')) / 2)
    assert mean_daily_total.lowered_from == ('Sum', 'Mean') and lift(mean_daily_total, Mean()).reason is RefuseReason.ILL_TYPED_ROLL
    assert isinstance(lift(floors(Mean()), Max()), Carrier)
    # allowed: the correct weighted reconstruction from a stored (mean, count) pair equals the mean over leaves
    means, counts = floors(Mean()), floors(Count())
    rebuilt = _ok(lower(_ok(roll(_ok(lift(_ok(join(means, counts)), WeightedMean())), dimension=Dimension.SUBJECT, to_level='building', lattice=space))))
    over_leaves = _ok(lower(_ok(roll(_acc(leaves(), Mean()), dimension=Dimension.SUBJECT, to_level='building', lattice=space))))
    _same(rebuilt, over_leaves)


def test_rekey_is_a_functor_and_lift_rejects_wrong_value_types(space) -> None:
    acc = _acc(leaves(), Sum())
    swapped = _ok(rekey(acc, lambda c: c.moved(Dimension.SUBJECT, 'zone', {'z1': 'z2', 'z2': 'z1', 'z3': 'z3'}[c.subject_key])))
    assert swapped.operator == Sum() and swapped.cells[coord('z1', 'h1')] == acc.cells[coord('z2', 'h1')] and swapped.sources(coord('z1', 'h1')) == {src('z2', 'h1')}
    assert rekey(acc, lambda c: coord('z1', 'h1')).reason is RefuseReason.UNSUPPORTED_COMPOSITION
    with pytest.raises(IllegalOperatorUse):
        lift(_ok(join(leaves(), leaves())), Sum())  # pairs into Sum: a plan-authoring error, raised, never a concatenation
    with pytest.raises(IllegalOperatorUse):
        lift(leaves(), WeightedMean())  # bare floats into a pair operator


def test_law_scale_roll_commute_only_for_a_constant_rate(space) -> None:
    usage = leaves(seed=8)
    constant = 0.25
    lhs = _ok(lower(_ok(roll(_acc(_ok(scale(usage, constant)), Sum()), dimension=Dimension.SUBJECT, to_level='floor', lattice=space))))
    rhs = _ok(scale(_ok(lower(_ok(roll(_acc(usage, Sum()), dimension=Dimension.SUBJECT, to_level='floor', lattice=space)))), constant))
    _same(lhs, rhs)
    varying = {c: (0.1 if c.subject_key == 'z1' else 0.9) for c in usage.cells}  # a rate that differs across a floor's zones
    lhs_v = _ok(lower(_ok(roll(_acc(_ok(scale(usage, varying)), Sum()), dimension=Dimension.SUBJECT, to_level='floor', lattice=space))))
    assert lhs_v.cells[F1H1] != pytest.approx(rhs.cells[F1H1] / constant * 0.1)  # no single rate reproduces it after the fold


# ---------------------------------------------------------------------------
# Bridge and provenance
# ---------------------------------------------------------------------------


def test_law_bridge_denominator_and_provenance_is_leaves(space) -> None:
    now = datetime(2026, 5, 2, tzinfo=UTC)
    expected = [Identity('usage', c) for c in leaves().cells]
    present = [Instance(Identity('usage', c), {'usage': v}, now, 'usage@r1') for c, v in leaves().cells.items() if c.subject_key != 'z2']
    present.append(Instance(Identity('usage', coord('z2', 'h4')), {'usage': None}, now, 'usage@r1'))  # a null payload is an absent cell
    c = carrier_from_instances(expected, present, field='usage', spec=Field(FieldRole.LEAF))
    assert c.missing == {i.coordinate for i in expected if i.coordinate.subject_key == 'z2'} and c.is_leaf
    with pytest.raises(ValueError):
        carrier_from_instances(expected[:1], present, field='usage', spec=Field(FieldRole.LEAF))
    floors = _ok(lower(_ok(roll(_acc(c, Sum()), dimension=Dimension.SUBJECT, to_level='floor', lattice=space, on_missing=OnMissing.ABSENT))))
    out = {i.identity.cache_key(): i for i in instances_from_carrier(floors, product='floor_usage', computed_at=now, computed_by='floor_usage@r1', field='usage', spec=Field(FieldRole.REPORTED, 'sum'), operators=REGISTRY)}
    f2h1 = out['floor_usage|site|floor=f2|hourly|h1']
    assert tuple(r.key for r in f2h1.lineage) == ('usage|site|zone=z3|hourly|h1',) and f2h1.payload == {'usage': leaves().cells[coord('z3', 'h1')]}
    assert 'floor_usage|site|floor=f1|hourly|h1' not in out  # incomplete: absent, never persisted as zero


def test_bridge_tags_stored_accumulators_and_marks_stored_reports(space) -> None:
    now = datetime(2026, 5, 2, tzinfo=UTC)
    acc_field = Field(FieldRole.ACCUMULATOR, 'mean', columns=('average_temperature', 'source_hour_count'))  # what a store already holds
    acc = _ok(roll(_acc(leaves(), Mean()), dimension=Dimension.SUBJECT, to_level='floor', lattice=space))
    stored = _ok(instances_from_carrier(acc, product='floor_temp', computed_at=now, computed_by='r1', field='acc', spec=acc_field, operators=REGISTRY))
    assert set(stored[0].payload) == {'average_temperature', 'source_hour_count'} and stored[0].payload['source_hour_count'] == 2.0
    back = carrier_from_instances([i.identity for i in stored], stored, field='acc', spec=acc_field, operators=REGISTRY)
    assert back.operator == Mean() and not back.is_values
    _same(back, acc, provenance=False)  # LAW_BRIDGE_ROUND_TRIP for an accumulator: the stored (mean, count) is the accumulator again; a re-read carrier's sources are the stored instances
    _same(_ok(roll(back, dimension=Dimension.SUBJECT, to_level='building', lattice=space)), _ok(roll(acc, dimension=Dimension.SUBJECT, to_level='building', lattice=space)), provenance=False)
    reported = _ok(instances_from_carrier(_ok(lower(acc)), product='floor_temp', computed_at=now, computed_by='r1', field='temp', spec=Field(FieldRole.REPORTED, 'mean'), operators=REGISTRY))
    back_reported = carrier_from_instances([i.identity for i in reported], reported, field='temp', spec=Field(FieldRole.REPORTED, 'mean'), operators=REGISTRY)
    assert back_reported.lowered_from == ('Mean',) and lift(back_reported, Mean()).reason is RefuseReason.ILL_TYPED_ROLL
    _same(back_reported, _ok(lower(acc)), provenance=False)
    plain = _ok(instances_from_carrier(leaves(), product='zone_temp', computed_at=now, computed_by='r1', field='temp', spec=Field(FieldRole.LEAF)))
    _same(carrier_from_instances([i.identity for i in plain], plain, field='temp', spec=Field(FieldRole.LEAF)), leaves())
    # the declaration the algebra will consult later may not lie about what was written
    assert instances_from_carrier(acc, product='p', computed_at=now, computed_by='r1', field='f', spec=Field(FieldRole.REPORTED, 'mean'), operators=REGISTRY).reason is RefuseReason.UNSUPPORTED_COMPOSITION
    assert instances_from_carrier(acc, product='p', computed_at=now, computed_by='r1', field='f', spec=Field(FieldRole.ACCUMULATOR, 'sum'), operators=REGISTRY).reason is RefuseReason.UNSUPPORTED_COMPOSITION
    assert instances_from_carrier(_ok(lower(acc)), product='p', computed_at=now, computed_by='r1', field='f', spec=Field(FieldRole.LEAF)).reason is RefuseReason.UNSUPPORTED_COMPOSITION
    assert instances_from_carrier(leaves(), product='p', computed_at=now, computed_by='r1', field='f', spec=Field(FieldRole.REPORTED, 'mean'), operators=REGISTRY).reason is RefuseReason.UNSUPPORTED_COMPOSITION
    with pytest.raises(ValueError):  # a registry is required to name what was stored
        carrier_from_instances([i.identity for i in stored], stored, field='acc', spec=acc_field)
    with pytest.raises(ValueError):  # a two-column operator needs its columns declared
        instances_from_carrier(acc, product='p', computed_at=now, computed_by='r1', field='acc', spec=Field(FieldRole.ACCUMULATOR, 'mean'), operators=REGISTRY)


# ---------------------------------------------------------------------------
# Closure over Carrier | Refuse; slice needs the key; provenance across families; canonical identity
# ---------------------------------------------------------------------------


def test_law_refuse_absorbs(space) -> None:
    r1, r2 = Refuse(RefuseReason.INCOMPLETE_PARTITION, 'first'), Refuse(RefuseReason.DOUBLE_COUNTED, 'second')
    unary = (
        lambda c: lift(c, Sum()), lower,
        lambda c: roll(c, dimension=Dimension.SUBJECT, to_level='floor', lattice=space),
        lambda c: restrict(c, lambda _: True), lambda c: slice_cells(c, shift='day'), lambda c: classify(c, 'k', lambda _: 'v'),
        lambda c: rekey(c, lambda x: x), lambda c: shift(c, Dimension.PERIOD, lambda k: k), lambda c: map_cells(c, lambda v: v),
        lambda c: scale(c, 2.0), lambda c: rank(c),
    )
    for primitive in unary:
        assert primitive(r1) is r1
    for binary in (join, diff):
        assert binary(r1, leaves()) is r1 and binary(leaves(), r1) is r1 and binary(r1, r2) is r1  # the left refusal wins
    # so a composition needs no check between steps: the first refusal is the result
    assert lower(roll(slice_cells(_acc(leaves(), Mean()), shift='day'), dimension=Dimension.SUBJECT, to_level='floor', lattice=space)).reason \
        is RefuseReason.UNSUPPORTED_COMPOSITION


def test_law_slice_on_an_uncarried_classification_is_refused_not_empty() -> None:
    refused = slice_cells(leaves(), shift='day')  # nothing here carries a shift
    assert refused.reason is RefuseReason.UNSUPPORTED_COMPOSITION and refused.context['classification'] == 'shift'
    assert slice_refusal(leaves().expected, ['shift']) is not None and slice_refusal(leaves(shift=True).expected, ['shift']) is None
    assert len(slice_cells(leaves(shift=True), shift='day')) == 6  # 3 zones × the 2 day hours
    assert len(slice_cells(leaves(shift=True), shift='dawn')) == 0  # a carried key with no such value: legitimately empty


def test_law_provenance_survives_join_and_classify_as_identities() -> None:
    now = datetime(2026, 5, 2, tzinfo=UTC)
    temps, areas = leaves(), Carrier.of({c: 10.0 for c in leaves().cells}, family='zone_area')
    per_area = _ok(map_cells(_ok(join(temps, areas)), lambda pair: pair[0] / pair[1]))
    z1h1 = coord('z1', 'h1')
    assert per_area.sources(z1h1) == {Identity('zone_temp', z1h1), Identity('zone_area', z1h1)}
    stored = {i.identity.coordinate: i for i in _ok(instances_from_carrier(per_area, product='temp_per_area', computed_at=now, computed_by='r1', field='v', spec=Field(FieldRole.LEAF)))}
    assert tuple(r.key for r in stored[z1h1].lineage) == ('zone_area|site|zone=z1|hourly|h1', 'zone_temp|site|zone=z1|hourly|h1')
    # classify moves the cell to a classified coordinate; its source is still the unclassified stored leaf
    shifted = _ok(classify(temps, 'shift', lambda c: shift_of_hour(c.period_anchor)))
    assert shifted.sources(coord('z1', 'h1', shift='day')) == {src('z1', 'h1')}
    assert Carrier.of({z1h1: 1.0}).sources(z1h1) == frozenset()  # no family, no provenance: nothing is known


def test_law_key_deversioned_canonical_identity_at_the_bridge() -> None:
    now = datetime(2026, 5, 2, tzinfo=UTC)
    scheme = KeyScheme(entries=(('day_classif', 'd', 'all'),))
    asked = [Identity('usage', c) for c in leaves().cells]
    written = [Instance(Identity('usage', c.with_classifications(day_classif='all')), {'usage': v}, now, 'r1') for c, v in leaves().cells.items()]
    c = carrier_from_instances(asked, written, field='usage', spec=Field(FieldRole.LEAF), scheme=scheme)
    assert c.coverage().complete and len(c) == 12 and c.family == 'usage'
    with pytest.raises(ValueError):  # under the plain scheme the explicit neutral pair is a different coordinate
        carrier_from_instances(asked, written, field='usage', spec=Field(FieldRole.LEAF))
    with pytest.raises(ValueError):  # one carrier, one family
        carrier_from_instances([*asked, Identity('other', coord('z1', 'h1'))], written, field='usage', spec=Field(FieldRole.LEAF), scheme=scheme)


# ---------------------------------------------------------------------------
# Path independence and gap propagation; undefined reports
# ---------------------------------------------------------------------------


@pytest.mark.parametrize('operator', [Sum(), Mean(), Min(), Percentile(0.5, ExactSketch)], ids=lambda o: type(o).__name__)
@pytest.mark.parametrize('policy', list(OnMissing))
@pytest.mark.parametrize('missing', [(), ('h2',)], ids=['complete', 'h2-missing'])
def test_law_roll_path_independent(time, operator, policy, missing) -> None:
    hours = tuple(h for h in ('h1', 'h2', 'h3', 'h4') if h not in missing)
    acc = _acc(Carrier(leaves(hours=hours).cells, leaves().expected, family='zone_temp'), operator)  # h2 expected but absent
    two_step = roll(roll(acc, dimension=Dimension.PERIOD, to_level='daily', lattice=time, on_missing=policy), dimension=Dimension.PERIOD, to_level='monthly', lattice=time, on_missing=policy)
    one_step = roll(acc, dimension=Dimension.PERIOD, to_level='monthly', lattice=time, on_missing=policy)
    if isinstance(one_step, Refuse):
        assert isinstance(two_step, Refuse) and two_step.reason is one_step.reason
        return
    _same(two_step, one_step)
    for c in one_step.expected:
        assert two_step.sources(c) == one_step.sources(c) and two_step.gaps.get(c) == one_step.gaps.get(c)
    z1m1 = Coordinate('site', 'zone', 'z1', 'monthly', 'm1')
    if missing:
        assert one_step.gaps[z1m1] == {coord('z1', 'h2')}  # the finest coordinate known to be missing, not the intermediate day
        assert (z1m1 in one_step.cells) == (policy is OnMissing.PARTIAL)
    else:
        assert z1m1 not in one_step.gaps and z1m1 in one_step.cells


def test_law_empty_fold_is_absent_an_undefined_report_is_a_missing_cell(space) -> None:
    weighted = Carrier.of({coord('z1', 'h1'): (5.0, 0.0), coord('z2', 'h1'): (7.0, 2.0)}, family='w')  # z1 carries no weight
    lowered = _ok(lower(_acc(weighted, WeightedMean())))
    assert lowered.get(coord('z1', 'h1')) is ABSENT and lowered.missing == {coord('z1', 'h1')} and lowered.cells[coord('z2', 'h1')] == 7.0
    absent_floor = _ok(roll(_acc(weighted, WeightedMean()), dimension=Dimension.SUBJECT, to_level='floor', lattice=space, on_missing=OnMissing.PARTIAL))
    assert _ok(lower(absent_floor)).cells[F1H1] == pytest.approx(7.0)  # the zero-weight child adds nothing, refuses nothing
