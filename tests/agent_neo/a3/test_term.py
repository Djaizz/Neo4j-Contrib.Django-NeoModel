"""Terms: what an agent writes; shapes: what is decided before any value is touched."""


from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from agent_neo.a3 import (
    Ask,
    Carrier,
    Classify,
    Concept,
    Coordinate,
    Dimension,
    Ensure,
    Env,
    Field,
    FieldRole,
    Identity,
    Instance,
    Join,
    Layer,
    Lift,
    Lower,
    Map,
    Mean,
    OnMissing,
    OperatorRegistry,
    Refuse,
    RefuseReason,
    Rekey,
    Relift,
    Restrict,
    Roll,
    Shape,
    Shift,
    Slice,
    Sum,
    TermLike,
    check_layers,
    evaluate,
    instances_from_carrier,
    products_read,
    servable,
    shape,
)
from tests.agent_neo.a3.conftest import (
    DictStore,
    ToyResolver,
    coord,
    leaves,
    shift_of_hour,
)

NOW = datetime(2026, 5, 2, 12, tzinfo=UTC)


def _registry() -> OperatorRegistry:
    r = OperatorRegistry()
    r.register('sum', Sum())
    r.register('mean', Mean())
    return r


@pytest.fixture
def world(space, time):
    temps = leaves(seed=7)
    instances = [Instance(Identity('zone_temp', c), {'temp': v}, NOW, 'zone_temp@r1') for c, v in temps.cells.items()]
    concepts = {'zone_temp': Concept('zone_temp', 'r1', Layer.FACT, fields={'temp': Field(FieldRole.LEAF)})}
    env = Env(
        operators=_registry(), lattices={'space': space, 'time': time}, resolver=ToyResolver(), store=DictStore(instances),
        concepts=concepts, functions={'shift_of_hour': lambda c: shift_of_hour(c.period_anchor), 'is_z1': lambda c: c.subject_key == 'z1',
                                       'next_hour': {'h1': 'h2', 'h2': 'h3', 'h3': 'h4', 'h4': 'h5'}.__getitem__, 'half': lambda v: v / 2,
                                       'to_h1': lambda k: 'h1', 'swap_z1_z2': lambda c: c.moved(Dimension.SUBJECT, 'zone', {'z1': 'z2', 'z2': 'z1'}.get(c.subject_key, c.subject_key))},
    )
    return temps, env


ASK_ALL_ZONES_HOURLY = Ask('zone_temp', 'site', 'zone', None, 'hourly')

CLASSIFIED = Classify(Lift(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), 'mean'), 'shift', 'shift_of_hour')
ROLLED = Roll(Roll(CLASSIFIED, Dimension.SUBJECT, 'floor', 'space'), Dimension.PERIOD, 'daily', 'time')
HEADLINE = Lower(Slice(ROLLED, (('shift', 'day'),)))  # roll first, slice after: LAW_SLICE_COMMUTES_WITH_ROLL's hypothesis
NAIVE = Lower(Roll(Roll(Slice(CLASSIFIED, (('shift', 'day'),)), Dimension.SUBJECT, 'floor', 'space'), Dimension.PERIOD, 'daily', 'time'))


def _agree(term, env) -> tuple[Shape | Refuse, Carrier | Refuse]:
    """LAW_SHAPE_SOUND, applied."""
    s, e = shape(term, env), evaluate(term, env)
    if isinstance(s, Refuse) or isinstance(e, Refuse):
        assert isinstance(s, Refuse) and isinstance(e, Refuse) and s.reason is e.reason, (s, e)
    else:
        assert s.expected == e.expected and s.present == frozenset(e.cells) and s.operator == e.operator and s.lowered_from == e.lowered_from
    return s, e


def test_headline_mean_temperature_per_floor_per_day_day_shift(world) -> None:
    temps, env = world
    # Slicing the shift away before rolling along the hour makes h2 (a night hour) look like a gap in d1:
    naive, _ = _agree(NAIVE, env)
    assert isinstance(naive, Refuse) and naive.reason is RefuseReason.INCOMPLETE_PARTITION and naive.context['parent'].period_anchor == 'd1'
    _, result = _agree(HEADLINE, env)
    assert isinstance(result, Carrier)
    f1d1 = Coordinate('site', 'floor', 'f1', 'daily', 'd1', {'shift': 'day'})
    assert result.cells[f1d1] == pytest.approx((temps.cells[coord('z1', 'h1')] + temps.cells[coord('z2', 'h1')]) / 2)  # h1 is d1's only day hour
    assert result.sources(f1d1) == {coord('z1', 'h1', shift='day'), coord('z2', 'h1', shift='day')}
    assert result.lowered_from == ('Mean',) and len(result) == 4  # 2 floors × 2 days, day shift


def test_law_depends_on_derived_and_layers_checked(world) -> None:
    _, env = world
    assert isinstance(HEADLINE, TermLike) and products_read(HEADLINE) == {'zone_temp'}
    floor_temp = Concept('floor_temp', 'r1', Layer.METRIC, fields={'temp': Field(FieldRole.REPORTED, 'mean')}, term=HEADLINE)
    assert floor_temp.depends_on == {'zone_temp'} and check_layers(floor_temp, env) is None
    too_low = Concept('bad', 'r1', Layer.SOURCE, term=HEADLINE)  # a source cannot be computed from a fact
    assert check_layers(too_low, env).reason is RefuseReason.LAYER_VIOLATION
    unknown = Concept('bad2', 'r1', Layer.VIEW, term=Ensure(Ask('nope', 'site', 'zone', None, 'hourly'), 'x'))
    assert check_layers(unknown, env).reason is RefuseReason.LAYER_VIOLATION


def test_a_stored_report_cannot_be_re_averaged_but_a_stored_accumulator_can_be_rolled_further(world, space) -> None:
    _, env = world
    per_floor_acc = evaluate(Roll(Lift(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), 'mean'), Dimension.SUBJECT, 'floor', 'space'), env)
    stored_acc = instances_from_carrier(per_floor_acc, product='floor_acc', computed_at=NOW, computed_by='r1', field='acc', source_product='zone_temp')
    stored_rep = instances_from_carrier(evaluate(Lower(Roll(Lift(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), 'mean'), Dimension.SUBJECT, 'floor', 'space')), env),
                                        product='floor_temp', computed_at=NOW, computed_by='r1', field='temp', source_product='zone_temp')
    env2 = replace(env, store=DictStore(stored_acc + stored_rep), concepts={
        **env.concepts,
        'floor_acc': Concept('floor_acc', 'r1', Layer.METRIC, fields={'acc': Field(FieldRole.ACCUMULATOR, 'mean')}),
        'floor_temp': Concept('floor_temp', 'r1', Layer.METRIC, fields={'temp': Field(FieldRole.REPORTED, 'mean')}),
    })
    floors = Ask('floor_temp', 'site', 'floor', None, 'hourly')
    s, _ = _agree(Lift(Ensure(floors, 'temp'), 'mean'), env2)
    assert isinstance(s, Refuse) and s.reason is RefuseReason.ILL_TYPED_ROLL  # mean of stored means: refused before any payload is read
    building_from_stored = evaluate(Lower(Roll(Ensure(Ask('floor_acc', 'site', 'floor', None, 'hourly'), 'acc'), Dimension.SUBJECT, 'building', 'space')), env2)
    building_from_leaves = evaluate(Lower(Roll(Lift(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), 'mean'), Dimension.SUBJECT, 'building', 'space')), env)
    b1h1 = Coordinate('site', 'building', 'b1', 'hourly', 'h1')
    assert building_from_stored.cells[b1h1] == pytest.approx(building_from_leaves.cells[b1h1])  # exact, because accumulators were stored


@pytest.mark.parametrize('name, term, reason', [
    ('roll values', Roll(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), Dimension.SUBJECT, 'floor', 'space'), RefuseReason.ILL_TYPED_ROLL),
    ('lower values', Lower(Ensure(ASK_ALL_ZONES_HOURLY, 'temp')), RefuseReason.UNSUPPORTED_COMPOSITION),
    ('map accumulators', Map(Lift(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), 'mean'), 'half'), RefuseReason.UNSUPPORTED_COMPOSITION),
    ('join accumulators', Join(Lift(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), 'mean'), Ensure(ASK_ALL_ZONES_HOURLY, 'temp')), RefuseReason.UNSUPPORTED_COMPOSITION),
    ('lift lowered', Lift(Lower(Lift(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), 'mean')), 'sum'), RefuseReason.ILL_TYPED_ROLL),
    ('partial sum', Roll(Lift(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), 'sum'), Dimension.SUBJECT, 'floor', 'space', OnMissing.PARTIAL), RefuseReason.INCOMPLETE_PARTITION),
    ('mixed levels', Roll(Roll(Lift(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), 'sum'), Dimension.SUBJECT, 'floor', 'space'), Dimension.SUBJECT, 'campus', 'space'), RefuseReason.UNSUPPORTED_COMPOSITION),
    ('classify twice', Classify(Classify(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), 'shift', 'shift_of_hour'), 'shift', 'shift_of_hour'), RefuseReason.UNSUPPORTED_COMPOSITION),
    ('non-injective shift', Shift(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), Dimension.PERIOD, 'to_h1'), RefuseReason.UNSUPPORTED_COMPOSITION),
    ('relift a mean', Relift(Lower(Lift(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), 'mean')), 'mean'), RefuseReason.ILL_TYPED_ROLL),
    ('relift leaves', Relift(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), 'sum'), RefuseReason.ILL_TYPED_ROLL),
])
def test_law_shape_sound_every_refusal_is_decided_without_a_payload(world, name, term, reason) -> None:
    _, env = world
    s, _ = _agree(term, env)
    assert isinstance(s, Refuse) and s.reason is reason, name


def test_law_shape_sound_on_lawful_terms(world) -> None:
    _, env = world
    lawful = [
        Ensure(ASK_ALL_ZONES_HOURLY, 'temp'),
        Restrict(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), 'is_z1'),
        Map(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), 'half'),
        Join(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), Shift(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), Dimension.PERIOD, 'next_hour')),
        Roll(Lift(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), 'sum'), Dimension.PERIOD, 'monthly', 'time'),
        HEADLINE,
    ]
    for term in lawful:
        s, e = _agree(term, env)
        assert isinstance(s, Shape) and isinstance(e, Carrier)


def test_law_distributive_relift_a_stored_sum_of_sums_is_a_sum(world, space) -> None:
    _, env = world
    floor_sums = evaluate(Lower(Roll(Lift(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), 'sum'), Dimension.SUBJECT, 'floor', 'space')), env)
    stored = instances_from_carrier(floor_sums, product='floor_sum', computed_at=NOW, computed_by='r1', field='total', source_product='zone_temp')
    env2 = replace(env, store=DictStore(stored), concepts={**env.concepts, 'floor_sum': Concept('floor_sum', 'r1', Layer.METRIC, fields={'total': Field(FieldRole.REPORTED, 'sum')})})
    from_stored = Lower(Roll(Relift(Ensure(Ask('floor_sum', 'site', 'floor', None, 'hourly'), 'total'), 'sum'), Dimension.SUBJECT, 'building', 'space'))
    s, e = _agree(from_stored, env2)
    assert isinstance(s, Shape)
    from_leaves = evaluate(Lower(Roll(Lift(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), 'sum'), Dimension.SUBJECT, 'building', 'space')), env)
    b1h1 = Coordinate('site', 'building', 'b1', 'hourly', 'h1')
    assert e.cells[b1h1] == pytest.approx(from_leaves.cells[b1h1])
    assert isinstance(_agree(Lift(Ensure(Ask('floor_sum', 'site', 'floor', None, 'hourly'), 'total'), 'sum'), env2)[0], Refuse)  # plain lift still refuses


def test_rekey_moves_accumulators_too_and_join_keeps_one_sided_gaps(world) -> None:
    _, env = world
    swapped = Rekey(Lift(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), 'sum'), 'swap_z1_z2')  # a relabeling is a functor: the tag survives it
    s, e = _agree(Roll(swapped, Dimension.SUBJECT, 'floor', 'space'), env)
    plain = evaluate(Roll(Lift(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), 'sum'), Dimension.SUBJECT, 'floor', 'space'), env)
    assert isinstance(s, Shape) and e.cells == plain.cells  # z1 and z2 share a floor, so the floor totals are unchanged by the swap
    this = Ensure(ASK_ALL_ZONES_HOURLY, 'temp')
    last = Shift(Ensure(Ask('zone_temp', 'site', 'zone', None, 'hourly', 'h1', 'h3'), 'temp'), Dimension.PERIOD, 'next_hour')
    s2, e2 = _agree(Join(this, last), env)
    assert isinstance(s2, Shape) and {c.period_anchor for c in e2.cells} == {'h2', 'h3', 'h4'} and s2.missing == frozenset({c for c in s2.expected if c.period_anchor == 'h1'})


def test_servable_is_the_serving_boundary() -> None:
    assert servable(Concept('v', 'r1', Layer.VIEW)) is None
    for layer in (Layer.SOURCE, Layer.FACT, Layer.METRIC, Layer.INTERPRETATION):
        assert servable(Concept('m', 'r1', layer)).reason is RefuseReason.NOT_SERVABLE


def test_missing_data_is_decided_by_shape_before_any_payload_is_read(world) -> None:
    _, env = world
    without_z2 = DictStore(i for i in env.store.by_key.values() if i.identity.coordinate.subject_key != 'z2')
    env2 = replace(env, store=without_z2)
    strict = Roll(Lift(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), 'mean'), Dimension.SUBJECT, 'floor', 'space')
    s, _ = _agree(strict, env2)
    assert isinstance(s, Refuse) and s.reason is RefuseReason.INCOMPLETE_PARTITION and s.context['parent'].subject_key == 'f1'
    estimate = replace(strict, on_missing=OnMissing.PARTIAL)
    s2, e2 = _agree(estimate, env2)
    assert isinstance(s2, Shape) and s2.missing == frozenset() and len(e2.gaps) == 4  # f1 estimated from z1 alone at every hour
    assert e2.gaps[Coordinate('site', 'floor', 'f1', 'hourly', 'h1')] == {coord('z2', 'h1')}


def test_a_classifier_lets_a_stored_sliced_product_roll_up_without_its_siblings(world, space, time) -> None:
    """The interpreter stores 'weekday' daily slots and asks for them by classification; the weekend days are
    never in the expected set. Rolling to monthly-weekday must not call them gaps."""
    _, env = world
    weekday = lambda c: 'weekday' if c.period_anchor == 'd1' else 'weekend'
    daily = [Instance(Identity('daily_usage', Coordinate('site', 'floor', f, 'daily', 'd1', {'day': 'weekday'})), {'usage': 10.0}, NOW, 'r1') for f in ('f1', 'f2')]
    env2 = replace(env, store=DictStore(daily), classifiers={'day': 'weekday_of'}, resolver=ToyResolver({'day': weekday}),
                   functions={**env.functions, 'weekday_of': weekday},
                   concepts={**env.concepts, 'daily_usage': Concept('daily_usage', 'r1', Layer.METRIC, fields={'usage': Field(FieldRole.LEAF)})})
    ask = Ask('daily_usage', 'site', 'floor', None, 'daily', classifications={'day': 'weekday'})
    monthly = Roll(Lift(Ensure(ask, 'usage'), 'sum'), Dimension.PERIOD, 'monthly', 'time')
    without_classifier = replace(env2, classifiers={})
    s0, _ = _agree(monthly, without_classifier)
    assert isinstance(s0, Refuse) and s0.reason is RefuseReason.INCOMPLETE_PARTITION  # without the classifier, d2 looks like a missing weekday
    s1, e1 = _agree(monthly, env2)
    assert isinstance(s1, Shape) and e1.cells[Coordinate('site', 'floor', 'f1', 'monthly', 'm1', {'day': 'weekday'})] == pytest.approx(10.0)


def test_rolled_parents_are_gated_for_maturity_in_shape_and_evaluation(world) -> None:
    _, env = world
    ends = {('daily', 'd1'): datetime(2026, 5, 2, 0, tzinfo=UTC), ('daily', 'd2'): datetime(2026, 5, 3, 0, tzinfo=UTC), ('monthly', 'm1'): datetime(2026, 6, 1, tzinfo=UTC)}
    gated = replace(env, now=NOW, maturity_lag=timedelta(minutes=30), exclusive_end=lambda level, key: ends[(level, key)])
    daily = Roll(Lift(Ensure(ASK_ALL_ZONES_HOURLY, 'temp'), 'sum'), Dimension.PERIOD, 'daily', 'time')
    s, _ = _agree(daily, gated)
    assert isinstance(s, Refuse) and s.reason is RefuseReason.IMMATURE_WINDOW and s.context['coordinate'].period_anchor == 'd2'
    only_d1 = Roll(Lift(Ensure(Ask('zone_temp', 'site', 'zone', None, 'hourly', 'h1', 'h2'), 'temp'), 'sum'), Dimension.PERIOD, 'daily', 'time')
    s1, e1 = _agree(only_d1, gated)
    assert isinstance(s1, Shape) and {c.period_anchor for c in e1.cells} == {'d1'}
