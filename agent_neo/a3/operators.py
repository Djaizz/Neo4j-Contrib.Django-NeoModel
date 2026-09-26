"""Aggregation operators as factored monoid actions: ``lift`` / ``combine`` / ``lower``.

An operator is not a callable over a list of values. It is three functions and two
declarations:

- ``lift(value) -> accumulator`` — enter the mergeable representation;
- ``combine(acc, acc) -> accumulator`` — an associative *and commutative* binary operation
  on accumulators. Both are preconditions, not options: a fold runs over an unordered set of
  children, so a non-commutative ``combine`` would make the result depend on iteration
  order. No unit is required: the algebra defines the fold of an empty set as ``Absent``,
  never as an operator's identity element. Floating-point associativity holds up to
  rounding, which is how the laws are tested; ``NaN`` is outside every operator's domain;
- ``lower(accumulator) -> value`` — leave the mergeable representation to report.
- ``kind`` — Gray et al.'s classification (distributive / algebraic / holistic), which is
  what tells a planner whether stored accumulators can be re-rolled, and what tells the
  registry that a holistic operator without a mergeable sketch may not be registered.
- ``value_type`` — the Python type(s) ``lift`` accepts. The algebra checks it, so a pair fed to
  ``Sum`` is refused as a plan-authoring error rather than concatenated in silence.
- ``partial_ok`` — whether folding only the children that are present is a meaningful
  estimate (a mean, a minimum, a quantile over 22 of 24 hours) or an undercount dressed as
  an answer (a sum, a count). The ``partial`` roll policy consults it.

The factorization is the whole point. Storing ``lower(acc)`` and later combining those
scalars is the mistake this design exists to make unconstructible: a mean of means, a
95th percentile of 95th percentiles. Accumulators combine; reported values do not.

Two failure channels, deliberately: :class:`Refuse` (a value, from :mod:`.algebra`) for
anything the algebra can decide about a plan or its data, and :class:`IllegalOperatorUse`
(an exception) only for calling an operator's methods directly in a way no lawful plan
produces — lowering an empty accumulator, lifting into a holistic operator that has no
sketch. The algebra checks ``kind``/``mergeable`` before it touches a value, so a plan
reaches a :class:`Refuse` first; the exception is the backstop for direct callers.
"""


from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar, Protocol, TypeVar, runtime_checkable

__all__ = (
    'AggregateKind',
    'Count',
    'IllegalOperatorUse',
    'Max',
    'Mean',
    'Min',
    'Operator',
    'OperatorRegistry',
    'Percentile',
    'Proportion',
    'RatioAccumulator',
    'Sketch',
    'SketchFactory',
    'Sum',
    'WeightedMean',
)


V = TypeVar('V')
A = TypeVar('A')


class IllegalOperatorUse(ValueError):
    """An operator was called directly in a way no lawful plan produces."""


class AggregateKind(StrEnum):
    """Gray, Chaudhuri, Bosworth et al. (1996): how an aggregate behaves under partitioning.

    - ``DISTRIBUTIVE``: the accumulator *is* the value (sum, count, min, max).
    - ``ALGEBRAIC``: a bounded-size accumulator exists but differs from the value
      (mean needs (sum, count)).
    - ``HOLISTIC``: no bounded accumulator exists (median, percentile, distinct count);
      only recompute-from-leaves or an approximate mergeable sketch can roll it up.
    """

    DISTRIBUTIVE = 'distributive'
    ALGEBRAIC = 'algebraic'
    HOLISTIC = 'holistic'


@runtime_checkable
class Operator(Protocol[V, A]):
    """The contract every aggregation operator declares.

    ``combine`` must be associative and commutative (:data:`~agent_neo.a3.laws.LAW_COMBINE_ASSOCIATIVE`,
    :data:`~agent_neo.a3.laws.LAW_COMBINE_COMMUTATIVE`); every shipped operator is tested for
    both. ``mergeable`` is ``False`` only for a holistic operator with no accumulator bound.
    """

    kind: ClassVar[AggregateKind]
    partial_ok: ClassVar[bool]
    value_type: ClassVar[type | tuple[type, ...]]

    @property
    def mergeable(self) -> bool: ...

    def lift(self, value: V) -> A: ...

    def combine(self, left: A, right: A) -> A: ...

    def lower(self, accumulator: A) -> V: ...


# ---------------------------------------------------------------------------
# Distributive operators: the accumulator is the value
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Sum:
    kind: ClassVar[AggregateKind] = AggregateKind.DISTRIBUTIVE
    partial_ok: ClassVar[bool] = False
    value_type: ClassVar[type | tuple[type, ...]] = (int, float)

    @property
    def mergeable(self) -> bool:
        return True

    def lift(self, value: float) -> float:
        return value

    def combine(self, left: float, right: float) -> float:
        return left + right

    def lower(self, accumulator: float) -> float:
        return accumulator


@dataclass(frozen=True, slots=True)
class Count:
    kind: ClassVar[AggregateKind] = AggregateKind.DISTRIBUTIVE
    partial_ok: ClassVar[bool] = False
    value_type: ClassVar[type | tuple[type, ...]] = object

    @property
    def mergeable(self) -> bool:
        return True

    def lift(self, value: object) -> int:
        return 1

    def combine(self, left: int, right: int) -> int:
        return left + right

    def lower(self, accumulator: int) -> int:
        return accumulator


@dataclass(frozen=True, slots=True)
class Min:
    kind: ClassVar[AggregateKind] = AggregateKind.DISTRIBUTIVE
    partial_ok: ClassVar[bool] = True
    value_type: ClassVar[type | tuple[type, ...]] = (int, float)

    @property
    def mergeable(self) -> bool:
        return True

    def lift(self, value: float) -> float:
        return value

    def combine(self, left: float, right: float) -> float:
        return min(left, right)

    def lower(self, accumulator: float) -> float:
        return accumulator


@dataclass(frozen=True, slots=True)
class Max:
    kind: ClassVar[AggregateKind] = AggregateKind.DISTRIBUTIVE
    partial_ok: ClassVar[bool] = True
    value_type: ClassVar[type | tuple[type, ...]] = (int, float)

    @property
    def mergeable(self) -> bool:
        return True

    def lift(self, value: float) -> float:
        return value

    def combine(self, left: float, right: float) -> float:
        return max(left, right)

    def lower(self, accumulator: float) -> float:
        return accumulator


# ---------------------------------------------------------------------------
# Algebraic operators: one accumulator shape — a ratio — three ways in
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RatioAccumulator:
    """``numerator / denominator``, kept apart until ``lower``.

    Shared by :class:`Mean` (Σv, n), :class:`WeightedMean` (Σw·v, Σw) and
    :class:`Proportion` (Σactive, Σtotal): the same mergeable shape entered from three
    different value types.
    """

    numerator: float
    denominator: float

    def merged(self, other: RatioAccumulator) -> RatioAccumulator:
        return RatioAccumulator(self.numerator + other.numerator, self.denominator + other.denominator)

    def ratio(self, *, what: str) -> float:
        if self.denominator == 0:
            raise IllegalOperatorUse(f'{what}.lower on an accumulator with zero denominator')
        return self.numerator / self.denominator


@dataclass(frozen=True, slots=True)
class Mean:
    """Arithmetic mean as (Σv, n). Lowered means never combine — that is the design."""

    kind: ClassVar[AggregateKind] = AggregateKind.ALGEBRAIC
    partial_ok: ClassVar[bool] = True
    value_type: ClassVar[type | tuple[type, ...]] = (int, float)

    @property
    def mergeable(self) -> bool:
        return True

    def lift(self, value: float) -> RatioAccumulator:
        return RatioAccumulator(numerator=value, denominator=1.0)

    def combine(self, left: RatioAccumulator, right: RatioAccumulator) -> RatioAccumulator:
        return left.merged(right)

    def lower(self, accumulator: RatioAccumulator) -> float:
        return accumulator.ratio(what='Mean')


@dataclass(frozen=True, slots=True)
class WeightedMean:
    """Weighted mean as (Σw·v, Σw); a value is a ``(value, weight)`` pair (e.g. duration-weighted)."""

    kind: ClassVar[AggregateKind] = AggregateKind.ALGEBRAIC
    partial_ok: ClassVar[bool] = True
    value_type: ClassVar[type | tuple[type, ...]] = tuple

    @property
    def mergeable(self) -> bool:
        return True

    def lift(self, value: tuple[float, float]) -> RatioAccumulator:
        measurement, weight = value
        return RatioAccumulator(numerator=measurement * weight, denominator=weight)

    def combine(self, left: RatioAccumulator, right: RatioAccumulator) -> RatioAccumulator:
        return left.merged(right)

    def lower(self, accumulator: RatioAccumulator) -> float:
        return accumulator.ratio(what='WeightedMean')


@dataclass(frozen=True, slots=True)
class Proportion:
    """Share of a total as (Σactive, Σtotal); a value is an ``(active, total)`` pair.

    Equivalent to a :class:`WeightedMean` of an indicator, kept as its own operator because
    its value type is the pair the source data naturally carries (e.g. active and total
    duration), not a rate to be re-weighted.
    """

    kind: ClassVar[AggregateKind] = AggregateKind.ALGEBRAIC
    partial_ok: ClassVar[bool] = True
    value_type: ClassVar[type | tuple[type, ...]] = tuple

    @property
    def mergeable(self) -> bool:
        return True

    def lift(self, value: tuple[float, float]) -> RatioAccumulator:
        active, total = value
        return RatioAccumulator(numerator=active, denominator=total)

    def combine(self, left: RatioAccumulator, right: RatioAccumulator) -> RatioAccumulator:
        return left.merged(right)

    def lower(self, accumulator: RatioAccumulator) -> float:
        return accumulator.ratio(what='Proportion')


# ---------------------------------------------------------------------------
# Holistic operators: no exact bounded accumulator exists
# ---------------------------------------------------------------------------


@runtime_checkable
class Sketch(Protocol):
    """A mergeable summary standing in for the distribution it was built from.

    ``merge`` must be associative and commutative for the sketch to serve as an
    accumulator. Bindings (t-digest, KLL, an exact multiset for tests) live in domain
    packs; the algebra needs only this surface.
    """

    def add(self, value: float) -> Sketch: ...

    def merge(self, other: Sketch) -> Sketch: ...

    def quantile(self, q: float) -> float: ...


class SketchFactory(Protocol):
    def __call__(self) -> Sketch: ...


@dataclass(frozen=True, slots=True)
class Percentile:
    """A quantile. Holistic: rollable only through a bound :class:`Sketch`.

    Any mergeable accumulator qualifies — an approximate digest, or an exact multiset that
    keeps every value (unbounded, but lawful). With none bound the operator is not
    mergeable, the registry refuses to register it, and the algebra refuses to lift into it.
    Calling its methods directly in that state raises: there is no *bounded exact*
    accumulator for a percentile, and pretending a lowered quantile is one is the
    "p95 of p95s" this design exists to prevent.
    """

    quantile: float
    sketch_factory: SketchFactory | None = None

    kind: ClassVar[AggregateKind] = AggregateKind.HOLISTIC
    partial_ok: ClassVar[bool] = True
    value_type: ClassVar[type | tuple[type, ...]] = (int, float)

    @property
    def mergeable(self) -> bool:
        return self.sketch_factory is not None

    def _require_sketch(self, what: str) -> SketchFactory:
        if self.sketch_factory is None:
            raise IllegalOperatorUse(
                f'Percentile.{what}: a quantile has no exact accumulator; bind a mergeable '
                'sketch (t-digest, KLL, ...) to roll it up',
            )
        return self.sketch_factory

    def lift(self, value: float) -> Sketch:
        return self._require_sketch('lift')().add(value)

    def combine(self, left: Sketch, right: Sketch) -> Sketch:
        self._require_sketch('combine')
        return left.merge(right)

    def lower(self, accumulator: Sketch) -> float:
        self._require_sketch('lower')
        return accumulator.quantile(self.quantile)


# ---------------------------------------------------------------------------
# Registry: the point at which "an operator without a factorization cannot be
# registered" becomes true rather than aspirational
# ---------------------------------------------------------------------------


class OperatorRegistry:
    """Named operators an algebra instance will accept in plans.

    Registration validates the contract: the three methods, the two declarations, and —
    for holistic operators — that a sketch is bound. A plan may then name operators
    rather than carry them, and a typechecker can answer "can this be rolled?" from the
    registry alone.
    """

    def __init__(self) -> None:
        self._operators: dict[str, Any] = {}

    def register(self, name: str, operator: Any) -> Any:
        if name in self._operators:
            raise IllegalOperatorUse(f'operator {name!r} is already registered')
        missing = [attr for attr in ('lift', 'combine', 'lower') if not callable(getattr(operator, attr, None))]
        if missing:
            raise IllegalOperatorUse(f'operator {name!r} lacks the factorization methods {missing}')
        kind = getattr(operator, 'kind', None)
        if not isinstance(kind, AggregateKind):
            raise IllegalOperatorUse(f'operator {name!r} does not declare its AggregateKind')
        if not isinstance(getattr(operator, 'value_type', None), (type, tuple)):
            raise IllegalOperatorUse(f'operator {name!r} does not declare the value_type its lift accepts')
        if not isinstance(getattr(operator, 'partial_ok', None), bool):
            raise IllegalOperatorUse(
                f'operator {name!r} does not declare partial_ok (is a fold over the present children alone an '
                'estimate, or an undercount?)',
            )
        if kind is AggregateKind.HOLISTIC and not operator.mergeable:
            raise IllegalOperatorUse(
                f'operator {name!r} is holistic and has no mergeable sketch bound; it cannot be rolled up',
            )
        self._operators[name] = operator
        return operator

    def get(self, name: str) -> Any:
        try:
            return self._operators[name]
        except KeyError:
            raise KeyError(f'no operator registered as {name!r}') from None

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._operators))

    def __contains__(self, name: object) -> bool:
        return name in self._operators
