"""Aggregation operators as factored monoid actions: ``lift`` / ``combine`` / ``lower``.

An operator is not a callable over a list of values. It is three functions and four
declarations:

- ``lift(value) -> accumulator`` — enter the mergeable representation;
- ``combine(acc, acc) -> accumulator`` — an associative *and commutative* binary operation
  on accumulators. Both are preconditions, not options: a fold runs over an unordered set of
  children, so a non-commutative ``combine`` would make the result depend on iteration
  order. No unit is required: the algebra defines the fold of an empty set as ``Absent``,
  never as an operator's identity element. Floating-point associativity holds up to
  rounding, which is how the laws are tested; ``NaN`` is outside every operator's domain;
- ``lower(accumulator) -> value | Absent`` — leave the mergeable representation to report.
  An accumulator with no defined report (a ratio over nothing) lowers to ``ABSENT``: a data
  condition, not an error.
- ``exact`` — whether the reported value *is* the accumulator: ``lift(lower(a)) == a`` for
  every accumulator ``a``. True for sum, min, max; false for count, every ratio, every
  quantile. It is the one property the algebra consults when a reported value asks to
  re-enter the operator that produced it: a sum of sums is a sum; a mean of means is not a
  mean (:data:`~agent_neo.a3.laws.LAW_REPORTED_REENTRY`). Gray et al.'s distributive /
  algebraic / holistic classification is recoverable from ``exact`` and ``mergeable`` and
  is not declared separately.
- ``value_type`` — the Python type(s) ``lift`` accepts. The algebra checks it, so a pair fed to
  ``Sum`` is refused as a plan-authoring error rather than concatenated in silence.
- ``partial_ok`` — whether folding only the children that are present is a meaningful
  estimate (a mean, a minimum, a quantile over 22 of 24 hours) or an undercount dressed as
  an answer (a sum, a count). The ``partial`` roll policy consults it.
- ``columns`` with ``encode`` / ``decode`` — how an accumulator is stored: the named parts a
  store holds (a mean as ``(mean, count)``, a proportion as ``(active, total)``) and the two
  functions between them and the accumulator. This is what lets a stored ``(average, count)``
  pair re-enter the algebra as a mean accumulator and roll further, and what the bridge
  writes when a concept declares an ``ACCUMULATOR`` field.

The factorization is the whole point. Storing ``lower(acc)`` and later re-averaging those
scalars is the mistake this design exists to make unconstructible: a mean of means, a
95th percentile of 95th percentiles. Accumulators combine; reported values re-enter only an
exact operator.

Two failure channels, deliberately: :class:`Refuse` (a value, from :mod:`.algebra`) for
anything the algebra can decide about a plan or its data, and :class:`IllegalOperatorUse`
(an exception) only for calling an operator's methods directly in a way no lawful plan
produces — lifting into a holistic operator that has no sketch, registering an operator that
breaks its own laws. The algebra checks ``mergeable`` before it touches a value, so a plan
reaches a :class:`Refuse` first; the exception is the backstop for direct callers.
"""


from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import permutations
from typing import (
    Any,
    ClassVar,
    Iterable,
    Protocol,
    Sequence,
    TypeVar,
    runtime_checkable,
)

from agent_neo.a3.carrier import ABSENT, Absent

__all__ = (
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


@runtime_checkable
class Operator(Protocol[V, A]):
    """The contract every aggregation operator declares.

    ``combine`` must be associative and commutative (:data:`~agent_neo.a3.laws.LAW_COMBINE_ASSOCIATIVE`,
    :data:`~agent_neo.a3.laws.LAW_COMBINE_COMMUTATIVE`); the registry checks both over the
    samples it is given. ``mergeable`` is ``False`` only for a holistic operator with no
    accumulator bound.
    """

    exact: ClassVar[bool]
    partial_ok: ClassVar[bool]
    value_type: ClassVar[type | tuple[type, ...]]
    columns: ClassVar[tuple[str, ...]]

    @property
    def mergeable(self) -> bool: ...

    def lift(self, value: V) -> A: ...

    def combine(self, left: A, right: A) -> A: ...

    def lower(self, accumulator: A) -> V | Absent: ...

    def encode(self, accumulator: A) -> tuple[Any, ...]: ...

    def decode(self, *columns: Any) -> A: ...


class _Scalar:
    """An operator whose accumulator is one stored value."""

    columns: ClassVar[tuple[str, ...]] = ('value',)

    @property
    def mergeable(self) -> bool:
        return True

    def encode(self, accumulator: Any) -> tuple[Any, ...]:
        return (accumulator,)

    def decode(self, *columns: Any) -> Any:
        (value,) = columns
        return value


# ---------------------------------------------------------------------------
# Exact operators: the accumulator is the value
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Sum(_Scalar):
    exact: ClassVar[bool] = True
    partial_ok: ClassVar[bool] = False
    value_type: ClassVar[type | tuple[type, ...]] = (int, float)

    def lift(self, value: float) -> float:
        return value

    def combine(self, left: float, right: float) -> float:
        return left + right

    def lower(self, accumulator: float) -> float:
        return accumulator


@dataclass(frozen=True, slots=True)
class Min(_Scalar):
    exact: ClassVar[bool] = True
    partial_ok: ClassVar[bool] = True
    value_type: ClassVar[type | tuple[type, ...]] = (int, float)

    def lift(self, value: float) -> float:
        return value

    def combine(self, left: float, right: float) -> float:
        return min(left, right)

    def lower(self, accumulator: float) -> float:
        return accumulator


@dataclass(frozen=True, slots=True)
class Max(_Scalar):
    exact: ClassVar[bool] = True
    partial_ok: ClassVar[bool] = True
    value_type: ClassVar[type | tuple[type, ...]] = (int, float)

    def lift(self, value: float) -> float:
        return value

    def combine(self, left: float, right: float) -> float:
        return max(left, right)

    def lower(self, accumulator: float) -> float:
        return accumulator


# ---------------------------------------------------------------------------
# Inexact operators with one stored value: a count is not its own count
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Count(_Scalar):
    """``lift`` of anything is 1; a reported count re-entered would count as one thing."""

    exact: ClassVar[bool] = False
    partial_ok: ClassVar[bool] = False
    value_type: ClassVar[type | tuple[type, ...]] = object

    def lift(self, value: object) -> int:
        return 1

    def combine(self, left: int, right: int) -> int:
        return left + right

    def lower(self, accumulator: int) -> int:
        return accumulator


# ---------------------------------------------------------------------------
# Ratio operators: one accumulator shape, three ways in, stored as (report, denominator)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RatioAccumulator:
    """``numerator / denominator``, kept apart until ``lower``.

    Shared by :class:`Mean` (Σv, n), :class:`WeightedMean` (Σw·v, Σw) and
    :class:`Proportion` (Σactive, Σtotal): the same mergeable shape entered from three
    different value types. Stored as the pair ``(report, denominator)`` — the form stores
    already hold (an average and its count) — and rebuilt from it exactly.
    """

    numerator: float
    denominator: float

    def merged(self, other: RatioAccumulator) -> RatioAccumulator:
        return RatioAccumulator(self.numerator + other.numerator, self.denominator + other.denominator)

    def ratio(self) -> float | Absent:
        """The report, or ``ABSENT`` when nothing was accumulated."""
        return self.numerator / self.denominator if self.denominator else ABSENT

    def encoded(self) -> tuple[float | None, float]:
        ratio = self.ratio()
        return (None if ratio is ABSENT else ratio, self.denominator)

    @classmethod
    def decoded(cls, report: float | None, denominator: float) -> RatioAccumulator:
        return cls(0.0 if report is None or not denominator else report * denominator, denominator)


class _Ratio:
    partial_ok: ClassVar[bool] = True
    exact: ClassVar[bool] = False

    @property
    def mergeable(self) -> bool:
        return True

    def combine(self, left: RatioAccumulator, right: RatioAccumulator) -> RatioAccumulator:
        return left.merged(right)

    def lower(self, accumulator: RatioAccumulator) -> float | Absent:
        return accumulator.ratio()

    def encode(self, accumulator: RatioAccumulator) -> tuple[Any, ...]:
        return accumulator.encoded()

    def decode(self, *columns: Any) -> RatioAccumulator:
        report, denominator = columns
        return RatioAccumulator.decoded(report, denominator)


@dataclass(frozen=True, slots=True)
class Mean(_Ratio):
    """Arithmetic mean as (Σv, n); stored as ``(mean, count)``."""

    value_type: ClassVar[type | tuple[type, ...]] = (int, float)
    columns: ClassVar[tuple[str, ...]] = ('mean', 'count')

    def lift(self, value: float) -> RatioAccumulator:
        return RatioAccumulator(numerator=value, denominator=1.0)


@dataclass(frozen=True, slots=True)
class WeightedMean(_Ratio):
    """Weighted mean as (Σw·v, Σw); a value is a ``(value, weight)`` pair; stored as ``(mean, weight)``."""

    value_type: ClassVar[type | tuple[type, ...]] = tuple
    columns: ClassVar[tuple[str, ...]] = ('mean', 'weight')

    def lift(self, value: tuple[float, float]) -> RatioAccumulator:
        measurement, weight = value
        return RatioAccumulator(numerator=measurement * weight, denominator=weight)


@dataclass(frozen=True, slots=True)
class Proportion(_Ratio):
    """Share of a total as (Σactive, Σtotal); a value is an ``(active, total)`` pair.

    Equivalent to a :class:`WeightedMean` of an indicator, kept as its own operator because
    its value type is the pair the source data naturally carries (e.g. active and total
    duration), not a rate to be re-weighted. Stored as ``(active, total)``.
    """

    value_type: ClassVar[type | tuple[type, ...]] = tuple
    columns: ClassVar[tuple[str, ...]] = ('active', 'total')

    def lift(self, value: tuple[float, float]) -> RatioAccumulator:
        active, total = value
        return RatioAccumulator(numerator=active, denominator=total)

    def encode(self, accumulator: RatioAccumulator) -> tuple[Any, ...]:
        return (accumulator.numerator, accumulator.denominator)

    def decode(self, *columns: Any) -> RatioAccumulator:
        active, total = columns
        return RatioAccumulator(active, total)


# ---------------------------------------------------------------------------
# Holistic operators: no exact bounded accumulator exists
# ---------------------------------------------------------------------------


@runtime_checkable
class Sketch(Protocol):
    """A mergeable summary standing in for the distribution it was built from.

    ``merge`` must be associative and commutative for the sketch to serve as an
    accumulator. Bindings (t-digest, KLL, an exact multiset for tests) live in domain
    packs; the algebra needs only this surface. The store holds the sketch itself.
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

    exact: ClassVar[bool] = False
    partial_ok: ClassVar[bool] = True
    value_type: ClassVar[type | tuple[type, ...]] = (int, float)
    columns: ClassVar[tuple[str, ...]] = ('sketch',)

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

    def encode(self, accumulator: Sketch) -> tuple[Any, ...]:
        return (accumulator,)

    def decode(self, *columns: Any) -> Sketch:
        (sketch,) = columns
        return sketch


# ---------------------------------------------------------------------------
# Registry: the point at which "an operator without a factorization cannot be
# registered" becomes true rather than aspirational
# ---------------------------------------------------------------------------


def _close(left: Any, right: Any) -> bool:
    if left is ABSENT or right is ABSENT:
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9)
    return bool(left == right)


class OperatorRegistry:
    """Named operators an algebra instance will accept in plans.

    Registration validates the contract: the three methods, the four declarations, the
    storage columns, and — for holistic operators — that a sketch is bound. Given
    ``samples`` (values the operator's ``lift`` accepts), it also *runs* the laws over them:
    associativity and commutativity of ``combine`` observed through ``lower``, the ``exact``
    claim, and the ``encode``/``decode`` round trip. A plan may then name operators rather
    than carry them, and a typechecker can answer "can this be rolled?" from the registry alone.
    """

    def __init__(self) -> None:
        self._operators: dict[str, Any] = {}

    def register(self, name: str, operator: Any, *, samples: Sequence[Any] = ()) -> Any:
        if name in self._operators:
            raise IllegalOperatorUse(f'operator {name!r} is already registered')
        missing = [attr for attr in ('lift', 'combine', 'lower', 'encode', 'decode') if not callable(getattr(operator, attr, None))]
        if missing:
            raise IllegalOperatorUse(f'operator {name!r} lacks the factorization methods {missing}')
        for declaration, kind in (('exact', bool), ('partial_ok', bool), ('value_type', (type, tuple)), ('columns', tuple)):
            if not isinstance(getattr(operator, declaration, None), kind):
                raise IllegalOperatorUse(f'operator {name!r} does not declare {declaration}')
        if not operator.columns:
            raise IllegalOperatorUse(f'operator {name!r} declares no storage columns')
        if not operator.mergeable:
            raise IllegalOperatorUse(f'operator {name!r} is holistic and has no mergeable sketch bound; it cannot be rolled up')
        if samples:
            self._check_laws(name, operator, samples)
        self._operators[name] = operator
        return operator

    @staticmethod
    def _check_laws(name: str, op: Any, samples: Iterable[Any]) -> None:
        accumulators = [op.lift(v) for v in samples]
        if len(accumulators) < 3:
            raise IllegalOperatorUse(f'operator {name!r}: at least three samples are needed to check its laws')
        for a, b, c in permutations(accumulators[:4], 3):
            if not _close(op.lower(op.combine(a, op.combine(b, c))), op.lower(op.combine(op.combine(a, b), c))):
                raise IllegalOperatorUse(f'operator {name!r}: combine is not associative on the samples')
            if not _close(op.lower(op.combine(a, b)), op.lower(op.combine(b, a))):
                raise IllegalOperatorUse(f'operator {name!r}: combine is not commutative on the samples')
        folded = accumulators[0]
        for acc in accumulators[1:]:
            folded = op.combine(folded, acc)
        if op.exact:
            reentered = op.combine(*(op.lift(op.lower(acc)) for acc in (op.combine(accumulators[0], accumulators[1]), accumulators[2])))
            direct = op.combine(op.combine(accumulators[0], accumulators[1]), accumulators[2])
            if not _close(op.lower(reentered), op.lower(direct)):
                raise IllegalOperatorUse(f'operator {name!r} claims exact, but a re-entered report does not fold like its accumulator')
        encoded = op.encode(folded)
        if len(encoded) != len(op.columns) or not _close(op.lower(op.decode(*encoded)), op.lower(folded)):
            raise IllegalOperatorUse(f'operator {name!r}: encode/decode does not round-trip through its {len(op.columns)} column(s)')

    def get(self, name: str) -> Any:
        try:
            return self._operators[name]
        except KeyError:
            raise KeyError(f'no operator registered as {name!r}') from None

    def name_of(self, operator: Any) -> str | None:
        """The registry name of an operator instance, if registered."""
        return next((name for name, op in self._operators.items() if op == operator), None)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._operators))

    def __contains__(self, name: object) -> bool:
        return name in self._operators
