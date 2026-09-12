"""Value operators: lift / combine / lower so Roll is typed.

Playground stub — contracts only. Ill-typed rolls Refuse instead of inventing
callable cross-products.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar


__all__ = (
    'Accumulator',
    'Count',
    'IllegalOperatorUse',
    'Max',
    'Mean',
    'MeanAccumulator',
    'Min',
    'Operator',
    'Percentile',
    'Proportion',
    'ProportionAccumulator',
    'Sum',
)


V = TypeVar('V')
A = TypeVar('A')


class IllegalOperatorUse(ValueError):
    """Raised when a caller tries to combine lowered scalars or roll without a sketch."""


class Accumulator(Protocol):
    """Marker protocol: mergeable payload, not a reported scalar."""


class Operator(Protocol[V, A]):
    """Factorization every legal roll/aggregate must declare.

    ``combine`` must be associative (and commutative when independent-dimension
    ``Roll`` reorder is claimed). Callers must not ``combine(lower(x), …)``.
    """

    def lift(self, value: V) -> A:
        ...

    def combine(self, left: A, right: A) -> A:
        ...

    def lower(self, accumulator: A) -> V:
        ...


@dataclass(frozen=True, slots=True)
class Sum:
    """Monoid under addition."""

    def lift(self, value: float) -> float:
        return value

    def combine(self, left: float, right: float) -> float:
        return left + right

    def lower(self, accumulator: float) -> float:
        return accumulator


@dataclass(frozen=True, slots=True)
class Count:
    """Count of lifted observations."""

    def lift(self, value: object) -> int:
        return 1

    def combine(self, left: int, right: int) -> int:
        return left + right

    def lower(self, accumulator: int) -> int:
        return accumulator


@dataclass(frozen=True, slots=True)
class MeanAccumulator:
    total: float
    count: int


@dataclass(frozen=True, slots=True)
class Mean:
    """Mean as (sum, count); never average-of-averages."""

    def lift(self, value: float) -> MeanAccumulator:
        return MeanAccumulator(total=value, count=1)

    def combine(self, left: MeanAccumulator, right: MeanAccumulator) -> MeanAccumulator:
        return MeanAccumulator(
            total=left.total + right.total,
            count=left.count + right.count,
        )

    def lower(self, accumulator: MeanAccumulator) -> float:
        if accumulator.count == 0:
            raise IllegalOperatorUse('Mean.lower on empty accumulator')
        return accumulator.total / accumulator.count


@dataclass(frozen=True, slots=True)
class Min:
    def lift(self, value: float) -> float:
        return value

    def combine(self, left: float, right: float) -> float:
        return left if left <= right else right

    def lower(self, accumulator: float) -> float:
        return accumulator


@dataclass(frozen=True, slots=True)
class Max:
    def lift(self, value: float) -> float:
        return value

    def combine(self, left: float, right: float) -> float:
        return left if left >= right else right

    def lower(self, accumulator: float) -> float:
        return accumulator


@dataclass(frozen=True, slots=True)
class ProportionAccumulator:
    active: float
    total: float


@dataclass(frozen=True, slots=True)
class Proportion:
    def lift(self, value: tuple[float, float]) -> ProportionAccumulator:
        active, total = value
        return ProportionAccumulator(active=active, total=total)

    def combine(
        self,
        left: ProportionAccumulator,
        right: ProportionAccumulator,
    ) -> ProportionAccumulator:
        return ProportionAccumulator(
            active=left.active + right.active,
            total=left.total + right.total,
        )

    def lower(self, accumulator: ProportionAccumulator) -> float:
        if accumulator.total == 0:
            raise IllegalOperatorUse('Proportion.lower on zero total')
        return accumulator.active / accumulator.total


@dataclass(frozen=True, slots=True)
class Percentile:
    """Quantile op — legal only when a mergeable sketch is supplied.

    Without a sketch, ``lift`` / ``combine`` refuse. Domain packs may bind a
    t-digest / KLL implementation later; this stub encodes the law.
    """

    quantile: float
    sketch_factory: object | None = None

    def lift(self, value: float) -> object:
        if self.sketch_factory is None:
            raise IllegalOperatorUse(
                'Percentile requires a mergeable sketch; cannot lift a bare scalar',
            )
        raise NotImplementedError('sketch-backed Percentile not wired in playground')

    def combine(self, left: object, right: object) -> object:
        if self.sketch_factory is None:
            raise IllegalOperatorUse(
                'Percentile requires a mergeable sketch; cannot combine lowered quantiles',
            )
        raise NotImplementedError('sketch-backed Percentile not wired in playground')

    def lower(self, accumulator: object) -> float:
        if self.sketch_factory is None:
            raise IllegalOperatorUse('Percentile.lower without sketch')
        raise NotImplementedError('sketch-backed Percentile not wired in playground')
