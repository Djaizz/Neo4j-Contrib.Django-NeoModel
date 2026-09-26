"""Coordinates: the address space of the algebra.

A coordinate names one analytical cell: a scope, a subject at some level (its kind), a
period at some granularity, and zero or more classifications. It is hashable, so it can
key a :class:`~agent_neo.a3.algebra.Carrier`; it carries no value and no coverage — those
belong to the carrier, and coverage is derived there rather than stored here.

``Absent`` is the algebra's answer for "no value": distinct from zero, distinct from an
empty collection, and never the output of any fold that had nothing to fold.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Iterable, Mapping, Self

__all__ = (
    'ABSENT',
    'Absent',
    'Classifications',
    'Coordinate',
    'CoverageState',
    'Dimension',
    'freeze_classifications',
)



class Absent:
    """The value of a coordinate that has none — distinct from zero and from an empty
    collection, and the only value a fold over nothing produces. A singleton: ``Absent()``
    is ``ABSENT``."""

    __slots__ = ()
    _instance: Absent | None = None

    def __new__(cls) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return 'Absent'

    def __bool__(self) -> bool:
        return False


ABSENT: Absent = Absent()


class CoverageState(StrEnum):
    """What a coverage report says about one coordinate."""

    KNOWN = 'known'
    MISSING = 'missing'


Classifications = tuple[tuple[str, str], ...]


def freeze_classifications(classifications: Mapping[str, str] | Iterable[tuple[str, str]]) -> Classifications:
    """Canonical, hashable form of a classification set: name-sorted ``(name, value)`` pairs.

    A coordinate must be usable as a dict key and as a member of a frozenset, so its
    classifications cannot be a dict. Sorting by name also fixes the serialization order
    the cache key relies on.
    """
    items = classifications.items() if isinstance(classifications, Mapping) else classifications
    pairs = tuple(sorted((str(name), str(value)) for name, value in items))
    names = [name for name, _ in pairs]
    if len(names) != len(set(names)):
        raise ValueError(f'duplicate classification names in {pairs!r}')
    return pairs


class Dimension(StrEnum):
    """The two rollable dimensions of a coordinate.

    Each is a ``(level, key)`` pair whose *level* is already a coordinate field — the
    subject's kind, the period's granularity — which is what lets one :class:`Lattice`
    protocol serve both: rolling up is moving to a coarser level along one dimension.
    Classifications are the third axis; they are sliced, never rolled.
    """

    SUBJECT = 'subject'
    PERIOD = 'period'


@dataclass(frozen=True, slots=True)
class Coordinate:
    """Logical address of one analytical cell — hashable, so it can key a carrier.

    Dimensions are open: domain packs bind concrete subject kinds, granularities and
    classification vocabularies. The algebra only needs the shape.
    """

    scope_name: str
    subject_kind: str
    subject_key: str
    temporal_granularity: str
    period_anchor: str
    classifications: Classifications = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, 'classifications', freeze_classifications(self.classifications))

    @property
    def subject(self) -> tuple[str, str]:
        """``(level, key)`` along :attr:`Dimension.SUBJECT`."""
        return (self.subject_kind, self.subject_key)

    @property
    def period(self) -> tuple[str, str]:
        """``(level, key)`` along :attr:`Dimension.PERIOD`."""
        return (self.temporal_granularity, self.period_anchor)

    def along(self, dimension: Dimension) -> tuple[str, str]:
        return self.subject if dimension is Dimension.SUBJECT else self.period

    def moved(self, dimension: Dimension, level: str, key: str) -> Coordinate:
        """The same coordinate at another ``(level, key)`` along one dimension."""
        if dimension is Dimension.SUBJECT:
            return replace(self, subject_kind=level, subject_key=key)
        return replace(self, temporal_granularity=level, period_anchor=key)

    def classification(self, name: str, default: str | None = None) -> str | None:
        for key, value in self.classifications:
            if key == name:
                return value
        return default

    def with_classifications(self, **updates: str) -> Coordinate:
        merged = dict(self.classifications)
        merged.update(updates)
        return replace(self, classifications=freeze_classifications(merged))
