"""A toy world for the algebra laws: zones on floors in a building; hours in days in a month."""


from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Iterable

import pytest

from agent_neo.a3 import Ask, Carrier, Coordinate, Identity, Instance, MappingLattice

ZONES_BY_FLOOR = {'z1': 'f1', 'z2': 'f1', 'z3': 'f2'}
FLOORS_BY_BUILDING = {'f1': 'b1', 'f2': 'b1'}
HOURS_BY_DAY = {'h1': 'd1', 'h2': 'd1', 'h3': 'd2', 'h4': 'd2'}
DAYS_BY_MONTH = {'d1': 'm1', 'd2': 'm1'}

SUBJECTS = {'zone': tuple(ZONES_BY_FLOOR), 'floor': tuple(FLOORS_BY_BUILDING), 'building': ('b1',)}
ANCHORS = {'hourly': tuple(HOURS_BY_DAY), 'daily': tuple(DAYS_BY_MONTH), 'monthly': ('m1',)}


@pytest.fixture
def space() -> MappingLattice:
    return MappingLattice.from_parent_map('zone', 'floor', ZONES_BY_FLOOR) | MappingLattice.from_parent_map('floor', 'building', FLOORS_BY_BUILDING)


@pytest.fixture
def time() -> MappingLattice:
    return MappingLattice.from_parent_map('hourly', 'daily', HOURS_BY_DAY) | MappingLattice.from_parent_map('daily', 'monthly', DAYS_BY_MONTH)


@pytest.fixture
def overlapping_space() -> MappingLattice:
    """z2 sits on two floors: the hierarchy is not a partition."""
    return MappingLattice((
        (('zone', 'z1'), ('floor', 'f1')), (('zone', 'z2'), ('floor', 'f1')), (('zone', 'z2'), ('floor', 'f2')), (('zone', 'z3'), ('floor', 'f2')),
    ))


FAMILY = 'zone_temp'  # the family every toy leaf carrier is read from


def coord(zone: str, hour: str, **classifications: str) -> Coordinate:
    return Coordinate('site', 'zone', zone, 'hourly', hour, classifications)


def src(zone: str, hour: str, **classifications: str) -> Identity:
    """The stored leaf a toy cell came from: provenance is identities, not coordinates."""
    return Identity(FAMILY, coord(zone, hour, **classifications))


def leaves(seed: int = 0, *, zones=tuple(ZONES_BY_FLOOR), hours=tuple(HOURS_BY_DAY), shift: bool = False) -> Carrier[float]:
    """Every (zone, hour) cell with a seeded value; optionally a day/night shift assigned from the hour."""
    rng = random.Random(seed)
    cells = {}
    for z in zones:
        for h in hours:
            cls = {'shift': shift_of_hour(h)} if shift else {}
            cells[coord(z, h, **cls)] = round(rng.uniform(1, 100), 3)
    return Carrier.of(cells, family=FAMILY)


def shift_of_hour(hour: str) -> str:
    return 'day' if hour in ('h1', 'h3') else 'night'


@dataclass(frozen=True)
class ExactSketch:
    """A sketch that keeps everything: exact, mergeable, only sensible for tests."""

    values: tuple[float, ...] = field(default_factory=tuple)

    def add(self, value: float) -> ExactSketch:
        return ExactSketch((*self.values, value))

    def merge(self, other: ExactSketch) -> ExactSketch:
        return ExactSketch((*self.values, *other.values))

    def quantile(self, q: float) -> float:
        ordered = sorted(self.values)
        return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


class ToyResolver:
    """Every subject of the kind (or the one named) × every anchor of the granularity (or those
    between the bounds). A classified ask expects only the coordinates that *carry* that
    classification — the resolver consults the same classifiers a roll does; the ask's
    classification is a slice on the world, not a stamp on every coordinate."""

    def __init__(self, classifiers=None) -> None:
        self.classifiers = dict(classifiers or {})

    def resolve(self, ask: Ask) -> tuple[Identity, ...]:
        subjects = SUBJECTS[ask.subject_kind] if ask.subject_key is None else (ask.subject_key,)
        anchors = ANCHORS[ask.temporal_granularity]
        if ask.local_period_start is not None:
            lo, hi = anchors.index(str(ask.local_period_start)), anchors.index(str(ask.local_period_end or ask.local_period_start))
            anchors = anchors[lo:hi + 1]
        out = []
        for s in subjects:
            for a in anchors:
                c = Coordinate(ask.scope_name, ask.subject_kind, s, ask.temporal_granularity, a, ask.classifications)
                if all(self.classifiers[name](c) == value for name, value in ask.classifications if name in self.classifiers):
                    out.append(Identity(ask.product, c))
        return tuple(out)


class DictStore:
    def __init__(self, instances: Iterable[Instance] = ()) -> None:
        self.by_key = {i.identity.cache_key(): i for i in instances}

    def present(self, identities: Iterable[Identity]) -> frozenset[Identity]:
        return frozenset(i for i in identities if i.cache_key() in self.by_key)

    def fetch(self, identities: Iterable[Identity]) -> tuple[Instance, ...]:
        return tuple(self.by_key[i.cache_key()] for i in identities if i.cache_key() in self.by_key)
