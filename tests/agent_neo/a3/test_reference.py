"""The interpreter contracts, executed against the reference interpreter.

A storage-bound interpreter conforms when these pass against its store.
"""


from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from agent_neo.a3 import (
    Ask,
    AskFrom,
    Concept,
    Dimension,
    Ensure,
    Env,
    Field,
    FieldRole,
    Identity,
    Instance,
    Layer,
    LifecycleStatus,
    Lift,
    Lower,
    MemoryStore,
    OperatorRegistry,
    ReferenceInterpreter,
    Refuse,
    RefuseReason,
    Roll,
    Sum,
)
from tests.agent_neo.a3.conftest import ToyResolver, coord, leaves

T0 = datetime(2026, 5, 2, 12, tzinfo=UTC)
HOUR_ENDS = {'h1': T0 - timedelta(hours=3), 'h2': T0 - timedelta(hours=2), 'h3': T0 - timedelta(hours=1), 'h4': T0}

ZONE = Concept('zone_usage', 'zone_usage@r1', Layer.FACT, fields={'usage': Field(FieldRole.LEAF)})  # observed, no recipe
FLOOR = Concept('floor_usage', 'floor_usage@r1', Layer.METRIC, fields={'acc': Field(FieldRole.ACCUMULATOR, 'sum')},
                term=Roll(Lift(Ensure(AskFrom('zone_usage', 'zones_of'), 'usage'), 'sum'), Dimension.SUBJECT, 'floor', 'space'))
BUILDING = Concept('building_usage', 'building_usage@r1', Layer.VIEW, fields={'usage': Field(FieldRole.REPORTED, 'sum')},
                   term=Lower(Roll(Ensure(AskFrom('floor_usage', 'floors_of'), 'acc'), Dimension.SUBJECT, 'building', 'space')))
CONCEPTS = {c.family: c for c in (ZONE, FLOOR, BUILDING)}


def _below(kind: str):
    return lambda ask: Ask(f'{kind}_usage', ask.scope_name, kind, None, ask.temporal_granularity, ask.local_period_start, ask.local_period_end)


class Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def tick(self, **delta) -> datetime:
        self.now += timedelta(**delta)
        return self.now


@pytest.fixture
def world(space, time):
    observed = [Instance(Identity('zone_usage', c), {'usage': v}, T0 - timedelta(hours=4), 'zone_usage@r1') for c, v in leaves(seed=3).cells.items()]
    store = MemoryStore(observed, recipe_status={c.revision: c.lifecycle for c in CONCEPTS.values()})
    registry = OperatorRegistry()
    registry.register('sum', Sum())
    env = Env(operators=registry, lattices={'space': space, 'time': time}, resolver=ToyResolver(), store=store, concepts=CONCEPTS,
              functions={'zones_of': _below('zone'), 'floors_of': _below('floor')}, exclusive_end=lambda _, anchor: HOUR_ENDS[anchor])
    clock = Clock()
    return ReferenceInterpreter(env, clock), clock


B1H1 = Ask('building_usage', 'site', 'building', 'b1', 'hourly', 'h1', 'h1')
F1H1 = Identity('floor_usage', coord('z1', 'h1').moved(Dimension.SUBJECT, 'floor', 'f1'))
F2H1 = Identity('floor_usage', coord('z1', 'h1').moved(Dimension.SUBJECT, 'floor', 'f2'))
Z1H1 = Identity('zone_usage', coord('z1', 'h1'))
B1H1_ID = Identity('building_usage', coord('z1', 'h1').moved(Dimension.SUBJECT, 'building', 'b1'))


def _histories(store: MemoryStore) -> dict[str, tuple[Instance, ...]]:
    return {key: tuple(rows) for key, rows in store._history.items()}


def test_law_ensure_recursive_asking_for_the_view_produces_everything_under_it(world) -> None:
    interpreter, _ = world
    (b1,), store = interpreter.ensure(B1H1), interpreter.store
    assert isinstance(b1, Instance) and b1.payload == {'usage': pytest.approx(sum(leaves(seed=3).cells[coord(z, 'h1')] for z in ('z1', 'z2', 'z3')))}
    assert store.current(F1H1) is not None and store.current(F2H1) is not None  # the floors were ensured on the way, not merely read
    assert tuple(r.key for r in b1.lineage) == (store.key(F1H1), store.key(F2H1))  # lineage is what was read
    assert store.current(F1H1).lineage[0].key == store.key(Z1H1) and b1.computed_by == 'building_usage@r1' and b1.producing is LifecycleStatus.OFFICIAL


def test_law_ensure_idempotent(world) -> None:
    interpreter, _ = world
    first = interpreter.ensure(B1H1)
    before = _histories(interpreter.store)
    assert interpreter.ensure(B1H1) == first and _histories(interpreter.store) == before  # nothing minted, nothing flipped


def test_law_retire_not_mutate_and_redo_derived_from_a_changed_input(world) -> None:
    interpreter, clock = world
    (b1,) = interpreter.ensure(B1H1)
    store = interpreter.store
    old_f1 = store.current(F1H1)
    # a source is re-observed: nobody flags anything downstream
    store.retire(store.current(Z1H1), Instance(Z1H1, {'usage': 1000.0}, clock.tick(minutes=5), 'zone_usage@r1'))
    (b1_new,) = interpreter.ensure(B1H1)
    assert b1_new.computed_at > b1.computed_at and b1_new.payload['usage'] == pytest.approx(b1.payload['usage'] - leaves(seed=3).cells[coord('z1', 'h1')] + 1000.0)
    assert store.history(F1H1) == (replace(old_f1, lifecycle=LifecycleStatus.RETIRED), store.current(F1H1))  # flipped, payload intact
    assert store.history(F1H1)[0].payload == old_f1.payload and len(store.history(F2H1)) == 1  # f2 read nothing that changed
    assert len(store.history(b1.identity)) == 2 and store.history(b1.identity)[0].lifecycle is LifecycleStatus.RETIRED


def test_law_redo_derived_invalidation_reaches_dependents_without_a_cascade(world) -> None:
    interpreter, clock = world
    interpreter.ensure(B1H1)
    store = interpreter.store
    store.invalidate(Z1H1, cascade=False)  # only the source is flagged
    (refused,) = interpreter.ensure(B1H1)
    # the source has no recipe, so nothing can be recomputed: the refusal is honest and the stale instances are flagged, not served
    assert isinstance(refused, Refuse) and refused.reason is RefuseReason.INCOMPLETE_PARTITION
    assert store.current(F1H1).needs_redo and store.current(B1H1_ID).needs_redo and not store.current(F2H1).needs_redo
    # the source is observed again: everything flagged recomputes on the next ensure, nothing else does
    store.retire(store.current(Z1H1), Instance(Z1H1, {'usage': 5.0}, clock.tick(minutes=1), 'zone_usage@r1'))
    (b1,) = interpreter.ensure(B1H1)
    assert isinstance(b1, Instance) and not b1.needs_redo and not store.current(F1H1).needs_redo and len(store.history(F2H1)) == 1


def test_observed_products_are_refused_when_invalid_and_immature_windows_before_anything_runs(world) -> None:
    interpreter, _ = world
    interpreter.store.invalidate(Identity('zone_usage', coord('z3', 'h1')), cascade=False)
    (z3,) = interpreter.ensure(Ask('zone_usage', 'site', 'zone', 'z3', 'hourly', 'h1', 'h1'))
    assert isinstance(z3, Refuse) and z3.reason is RefuseReason.NO_RECIPE  # observed, not computed: nothing can recompute it
    immature = Ask('building_usage', 'site', 'building', 'b1', 'hourly', 'h4', 'h4', maturity_lag=timedelta(minutes=30))
    (refused,) = interpreter.ensure(immature)
    assert isinstance(refused, Refuse) and refused.reason is RefuseReason.IMMATURE_WINDOW
    assert interpreter.store.current(Identity('building_usage', coord('z1', 'h4').moved(Dimension.SUBJECT, 'building', 'b1'))) is None  # nothing was computed


def test_a_recipe_that_does_not_produce_the_asked_coordinate_is_refused(world) -> None:
    interpreter, _ = world
    (refused,) = interpreter.ensure(Ask('floor_usage', 'site', 'building', 'b1', 'hourly', 'h1', 'h1'))  # floors' recipe, asked for a building
    assert isinstance(refused, Refuse) and refused.reason is RefuseReason.UNSUPPORTED_COMPOSITION
