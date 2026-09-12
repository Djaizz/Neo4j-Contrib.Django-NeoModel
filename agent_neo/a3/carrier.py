"""Carrier: sparse coordinates with coverage for analytical values.

Playground stub — contracts only. No storage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, Hashable, Iterator, Mapping, TypeVar


__all__ = (
    'Absent',
    'Carrier',
    'Coordinate',
    'Coverage',
    'CoverageState',
)


T = TypeVar('T')


class Absent:
    """Sentinel for a coordinate with no value (distinct from zero / empty)."""

    __slots__ = ()

    def __repr__(self) -> str:
        return 'Absent'


ABSENT: Absent = Absent()


class CoverageState(StrEnum):
    """How much we know about a coordinate relative to its parent partition."""

    KNOWN = 'known'
    MISSING = 'missing'
    DOUBLE_COUNTED = 'double_counted'


@dataclass(frozen=True, slots=True)
class Coordinate:
    """Logical address of one analytical cell.

    Dimensions are open at the sketch level; domain packs bind concrete
    subject kinds, granularities, and classification vocabularies.
    """

    scope_name: str
    subject_kind: str
    subject_key: str
    temporal_granularity: str
    period_anchor: str
    classifications: Mapping[str, str] = field(default_factory=dict)

    def with_classifications(self, **updates: str) -> Coordinate:
        merged = dict(self.classifications)
        merged.update(updates)
        return Coordinate(
            scope_name=self.scope_name,
            subject_kind=self.subject_kind,
            subject_key=self.subject_key,
            temporal_granularity=self.temporal_granularity,
            period_anchor=self.period_anchor,
            classifications=merged,
        )


@dataclass(frozen=True, slots=True)
class Coverage:
    """Partition awareness for a set of child coordinates under a parent.

    ``Roll`` to a parent is legal only when children *partition* the parent:
    no ``MISSING`` gaps and no ``DOUBLE_COUNTED`` overlap.
    """

    states: Mapping[Hashable, CoverageState]

    def partitions_parent(self) -> bool:
        """True when every tracked child is ``KNOWN`` (sketch: no holes/overlaps)."""
        if not self.states:
            return False
        return all(state is CoverageState.KNOWN for state in self.states.values())


@dataclass(slots=True)
class Carrier(Generic[T]):
    """Sparse map from coordinates to values, with optional coverage mask.

    This is the uniform carrier the product ops act on — not a DB relation and
    not a Cypher result set.
    """

    cells: dict[Coordinate, T | Absent] = field(default_factory=dict)
    coverage: Coverage | None = None

    def get(self, coordinate: Coordinate) -> T | Absent:
        return self.cells.get(coordinate, ABSENT)

    def set(self, coordinate: Coordinate, value: T | Absent) -> None:
        self.cells[coordinate] = value

    def coordinates(self) -> Iterator[Coordinate]:
        return iter(self.cells)

    def __len__(self) -> int:
        return len(self.cells)
