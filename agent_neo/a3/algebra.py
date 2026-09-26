"""The carrier and the primitive operations closed over it.

**Carrier.** A sparse map from :class:`~agent_neo.a3.carrier.Coordinate` to a cell value,
plus what a plain map lacks:

- ``expected`` — the coordinates this carrier *should* have. Coverage is not stored per
  cell and is not part of the coordinate; it is *derived*: ``expected − cells`` is what is
  missing. The expected set enters at the bridge (an ask resolves to identities before any
  instance is fetched) and is transformed by every primitive, so a rolled carrier knows the
  parents it should have even when none of their children were present.
- ``operator`` — the accumulator tag. ``None`` means the cells are values; otherwise they are
  accumulators of that operator and only that operator may fold them.
- ``lowered_from`` — the operators whose *reported output* these values are. Empty means leaf
  observations. A lowered value never re-enters a fold: ``lift`` refuses it. That, with the
  tag, is what makes mean-of-means and p95-of-p95s unconstructible.

**Primitives.** ``lift`` · ``relift`` · ``roll`` · ``restrict`` · ``classify`` · ``rekey`` ·
``map`` · ``join`` · ``lower``. Each returns a carrier or a :class:`~agent_neo.a3.product.Refuse`;
none raises for anything a plan could produce (feeding an operator a value type it does not
take is a plan-authoring error and raises). ``slice``, ``shift``, ``scale`` and ``diff`` are
provided but *derived*; the laws test that they equal their expansions. ``rank`` is a
boundary projection to an ordered sequence, not an operation on carriers.

**Provenance** rides along: each derived cell knows the leaf coordinates it came from, so
an explanation is a lookup, not a graph walk.
"""


from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from functools import reduce
from typing import Any, Callable, Generic, Iterator, Mapping, TypeVar

from agent_neo.a3.carrier import ABSENT, Absent, Coordinate, CoverageState, Dimension
from agent_neo.a3.lattice import Lattice
from agent_neo.a3.operators import AggregateKind, IllegalOperatorUse
from agent_neo.a3.product import Refuse, RefuseReason

__all__ = (
    'Carrier',
    'Classifiers',
    'Coverage',
    'OnMissing',
    'RollPlan',
    'classify',
    'diff',
    'join',
    'lift',
    'lift_refusal',
    'lower',
    'map',
    'plan_roll',
    'rank',
    'rekey',
    'relift',
    'restrict',
    'roll',
    'roll_refusal',
    'scale',
    'shift',
    'slice',
)


V = TypeVar('V')
W = TypeVar('W')


class OnMissing(StrEnum):
    """What a roll does with a parent whose expected children are not all present."""

    REFUSE = 'refuse'  # the whole roll is a Refuse(INCOMPLETE_PARTITION) naming the parent and the gap
    ABSENT = 'absent'  # the parent is absent (never zero); ``gaps`` names what it lacked
    PARTIAL = 'partial'  # fold what is present, if the operator says that is an estimate and not an undercount


# ---------------------------------------------------------------------------
# Coverage: a report, derived on demand
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Coverage:
    known: frozenset[Coordinate]
    missing: frozenset[Coordinate]
    double_counted: frozenset[Coordinate] = frozenset()

    @property
    def complete(self) -> bool:
        return not self.missing and not self.double_counted

    def state(self, coordinate: Coordinate) -> CoverageState | None:
        if coordinate in self.double_counted:
            return CoverageState.DOUBLE_COUNTED
        if coordinate in self.missing:
            return CoverageState.MISSING
        if coordinate in self.known:
            return CoverageState.KNOWN
        return None


# ---------------------------------------------------------------------------
# Carrier
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Carrier(Generic[V]):
    cells: Mapping[Coordinate, V]
    expected: frozenset[Coordinate]
    operator: Any | None = None
    lowered_from: tuple[str, ...] = ()
    #: derived coordinate → the leaf coordinates it was computed from; leaves are absent here
    provenance: Mapping[Coordinate, frozenset[Coordinate]] = field(default_factory=dict)
    #: parent → the children it lacked; populated by ABSENT and PARTIAL rolls
    gaps: Mapping[Coordinate, frozenset[Coordinate]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        stray = set(self.cells) - self.expected
        if stray:
            raise ValueError(f'{len(stray)} cell(s) outside the expected set, e.g. {next(iter(stray))!r}')

    @classmethod
    def of(cls, cells: Mapping[Coordinate, V], *, operator: Any | None = None) -> Carrier[V]:
        """A carrier whose expected set is exactly its cells (nothing known to be missing)."""
        return cls(dict(cells), frozenset(cells), operator)

    def _with(self, cells: Mapping[Coordinate, Any], expected: frozenset[Coordinate], **changes: Any) -> Carrier[Any]:
        fields = {'operator': self.operator, 'lowered_from': self.lowered_from, 'provenance': self.provenance, 'gaps': self.gaps}
        fields.update(changes)
        return Carrier(cells, expected, **fields)

    # -- reading -------------------------------------------------------------

    def get(self, coordinate: Coordinate) -> V | Absent:
        return self.cells.get(coordinate, ABSENT)

    def __len__(self) -> int:
        return len(self.cells)

    def __iter__(self) -> Iterator[Coordinate]:
        return iter(self.cells)

    @property
    def missing(self) -> frozenset[Coordinate]:
        return self.expected - frozenset(self.cells)

    def coverage(self) -> Coverage:
        return Coverage(known=frozenset(self.cells), missing=self.missing)

    def sources(self, coordinate: Coordinate) -> frozenset[Coordinate]:
        """Leaf coordinates behind a cell; a leaf's source is itself."""
        return self.provenance.get(coordinate, frozenset({coordinate}))

    @property
    def is_values(self) -> bool:
        return self.operator is None

    @property
    def is_leaf(self) -> bool:
        return self.operator is None and not self.lowered_from


# ---------------------------------------------------------------------------
# Entering and leaving the fold
# ---------------------------------------------------------------------------


def lift_refusal(operator_tag: Any | None, lowered_from: tuple[str, ...], operator: Any) -> Refuse | None:
    """The type-level reasons a lift cannot proceed; shared by ``lift`` and ``shape``."""
    if operator_tag is not None:
        return Refuse(RefuseReason.ILL_TYPED_ROLL, 'carrier already holds accumulators; lower before lifting into another operator',
                      {'operator': operator_tag})
    if lowered_from:
        return Refuse(RefuseReason.ILL_TYPED_ROLL,
                      f'these are reported values of {", ".join(lowered_from)}; a reported value never re-enters a fold '
                      '(roll the stored accumulators, or the leaves)', {'lowered_from': lowered_from})
    if not operator.mergeable:
        return Refuse(RefuseReason.NO_MERGEABLE_ACCUMULATOR,
                      f'{type(operator).__name__} is holistic with nothing bound to accumulate into', {'operator': operator})
    return None


def lift(carrier: Carrier[V], operator: Any) -> Carrier[Any] | Refuse:
    """Leaf values → accumulators of ``operator``."""
    refusal = lift_refusal(carrier.operator, carrier.lowered_from, operator)
    if refusal is not None:
        return refusal
    bad = next((c for c, v in carrier.cells.items() if not isinstance(v, operator.value_type) or isinstance(v, bool)), None)
    if bad is not None:
        raise IllegalOperatorUse(
            f'{type(operator).__name__} takes {operator.value_type!r}, not the {type(carrier.cells[bad]).__name__} at {bad!r}. '
            'This is a plan-authoring error: the field holds a value type the operator does not accept.',
        )
    return carrier._with({c: operator.lift(v) for c, v in carrier.cells.items()}, carrier.expected, operator=operator)


def relift(carrier: Carrier[V], operator: Any) -> Carrier[Any] | Refuse:
    """Re-enter a *distributive* operator's own reported values as its accumulators.

    For a distributive operator the accumulator *is* the value: a stored sum of sums is a
    lawful sum, a stored maximum of maxima a lawful maximum. Nothing else may come back in —
    a stored mean has no way to recover its count — which is exactly the distinction Gray's
    classification draws, and the one place the algebra consults it.
    """
    if not carrier.is_values:
        return Refuse(RefuseReason.ILL_TYPED_ROLL, 'carrier already holds accumulators')
    if not carrier.lowered_from:
        return Refuse(RefuseReason.ILL_TYPED_ROLL, 'these are leaf values; enter them with lift')
    name = type(operator).__name__
    if carrier.lowered_from != (name,) or operator.kind is not AggregateKind.DISTRIBUTIVE:
        return Refuse(RefuseReason.ILL_TYPED_ROLL,
                      f'reported values of {", ".join(carrier.lowered_from)} cannot re-enter {name}: only a distributive '
                      "operator's own reported values are its accumulators",
                      {'lowered_from': carrier.lowered_from, 'operator': operator})
    return carrier._with(dict(carrier.cells), carrier.expected, operator=operator, lowered_from=())


def lower(carrier: Carrier[Any]) -> Carrier[Any] | Refuse:
    """Accumulators → reported values, remembered as such."""
    if carrier.is_values:
        return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION, 'carrier already holds values')
    op = carrier.operator
    return carrier._with({c: op.lower(a) for c, a in carrier.cells.items()}, carrier.expected,
                         operator=None, lowered_from=(*carrier.lowered_from, type(op).__name__))


# ---------------------------------------------------------------------------
# Roll
# ---------------------------------------------------------------------------


def _context(coordinate: Coordinate, dimension: Dimension) -> tuple[str, tuple[str, str]]:
    """Everything about a coordinate except the rolled dimension and its classifications."""
    other = Dimension.PERIOD if dimension is Dimension.SUBJECT else Dimension.SUBJECT
    return (coordinate.scope_name, coordinate.along(other))


@dataclass(frozen=True, slots=True)
class RollPlan:
    """Everything a roll decides *before* touching a value: which parents exist, which
    children each folds, and which it lacks. The shape checker and the fold share it."""

    parents: frozenset[Coordinate]
    folds: Mapping[Coordinate, tuple[Coordinate, ...]]  # parent → present children to combine
    gaps: Mapping[Coordinate, frozenset[Coordinate]]


def roll_refusal(operator: Any | None, lowered_from: tuple[str, ...], on_missing: OnMissing) -> Refuse | None:
    """The type-level reasons a roll cannot proceed; shared by ``roll`` and ``shape``."""
    if operator is None:
        return Refuse(RefuseReason.ILL_TYPED_ROLL,
                      'cannot roll values; lift into an operator first (combining lowered values is the mean-of-means / '
                      'p95-of-p95s error)', {'lowered_from': lowered_from})
    if not operator.mergeable:
        return Refuse(RefuseReason.NO_MERGEABLE_ACCUMULATOR, f'{type(operator).__name__} cannot be rolled without an accumulator')
    if on_missing is OnMissing.PARTIAL and not operator.partial_ok:
        return Refuse(RefuseReason.INCOMPLETE_PARTITION,
                      f'a partial fold of {type(operator).__name__} is an undercount, not an estimate; use ABSENT or REFUSE')
    return None


Classifiers = Mapping[str, Callable[[Coordinate], str]]


def plan_roll(
    expected: frozenset[Coordinate],
    present: frozenset[Coordinate],
    *,
    dimension: Dimension,
    to_level: str,
    lattice: Lattice,
    on_missing: OnMissing,
    classifiers: Classifiers | None = None,
) -> RollPlan | Refuse:
    """Decide a roll from coordinates alone.

    A parent's expected children are ``lattice.down(parent)`` — not merely the children that
    happened to be present — so a child no ask ever mentioned is still a gap. Two things
    take a child *out* of a classified parent's denominator: the carrier knows it under a
    different classification (it belongs to the sibling parent there), or a ``classifier``
    for that classification says the child would not carry the parent's value. The second
    is what lets a stored weekday-daily product roll into weekday-monthly when the weekend
    days were never asked for at all.
    """
    levels = {c.along(dimension)[0] for c in expected}
    if len(levels) > 1:
        return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION,
                      f'carrier mixes levels {sorted(levels)} along {dimension.value}; roll one level at a time')
    if not levels:
        return RollPlan(frozenset(), {}, {})
    child_level = next(iter(levels))
    if child_level == to_level:
        return RollPlan(expected, {c: (c,) for c in present}, {})

    known_keys: dict[tuple[str, tuple[str, str]], set[str]] = {}
    for c in expected:
        known_keys.setdefault(_context(c, dimension), set()).add(c.along(dimension)[1])

    parents: set[Coordinate] = set()
    double_counted: set[Coordinate] = set()
    for child in expected:
        level, key = child.along(dimension)
        ups = lattice.up(level, key, to_level)
        if len(ups) > 1:
            double_counted.add(child)
            continue
        if not ups:
            return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION,
                          f'lattice places no {to_level} above {dimension.value} {key!r} at level {level!r}', {'coordinate': child})
        parents.add(child.moved(dimension, to_level, next(iter(ups))))

    if double_counted and on_missing is OnMissing.REFUSE:
        return Refuse(RefuseReason.DOUBLE_COUNTED,
                      f'{len(double_counted)} child(ren) roll into more than one {to_level}; the hierarchy is not a partition',
                      {'children': frozenset(double_counted)})

    folds: dict[Coordinate, tuple[Coordinate, ...]] = {}
    gaps: dict[Coordinate, frozenset[Coordinate]] = {}
    for parent in sorted(parents, key=repr):
        plevel, pkey = parent.along(dimension)
        ctx = _context(parent, dimension)
        expected_children: set[Coordinate] = set()
        for key in lattice.down(plevel, pkey, child_level):
            candidate = parent.moved(dimension, child_level, key)
            if candidate in expected:
                expected_children.add(candidate)
            elif key in known_keys.get(ctx, ()):
                continue  # asked for under another classification: the sibling parent's child
            elif classifiers and any(classifiers[name](candidate) != value for name, value in parent.classifications if name in classifiers):
                continue  # would not carry this parent's classification: not its child
            else:
                expected_children.add(candidate)  # never asked for: a gap
        if not expected_children:
            raise ValueError(f'lattice is inconsistent: {(plevel, pkey)} lists none of the children that rolled into it')
        present_children = tuple(sorted((c for c in expected_children if c in present), key=repr))
        missing = expected_children - set(present_children)
        tainted = any(c in double_counted for c in expected_children)
        if missing or tainted:
            if on_missing is OnMissing.REFUSE:
                return Refuse(RefuseReason.INCOMPLETE_PARTITION,
                              f'{dimension.value} {pkey!r} at {to_level!r} lacks {len(missing)} of {len(expected_children)} children',
                              {'parent': parent, 'missing': frozenset(missing)})
            gaps[parent] = frozenset(missing)
            if on_missing is OnMissing.ABSENT or tainted:
                continue
        if present_children:
            folds[parent] = present_children
    return RollPlan(frozenset(parents), folds, gaps)


def roll(
    carrier: Carrier[Any],
    *,
    dimension: Dimension,
    to_level: str,
    lattice: Lattice,
    on_missing: OnMissing = OnMissing.REFUSE,
    classifiers: Classifiers | None = None,
) -> Carrier[Any] | Refuse:
    """Fold accumulators up one dimension to a coarser level, judged against the lattice.
    See :func:`plan_roll` for what is decided and how; this only adds the values.
    An empty partition is never zero: it is absent."""
    refusal = roll_refusal(carrier.operator, carrier.lowered_from, on_missing)
    if refusal is not None:
        return refusal
    plan = plan_roll(carrier.expected, frozenset(carrier.cells), dimension=dimension, to_level=to_level, lattice=lattice,
                     on_missing=on_missing, classifiers=classifiers)
    if isinstance(plan, Refuse):
        return plan
    if plan.parents == carrier.expected and all(children == (parent,) for parent, children in plan.folds.items()):
        return carrier  # already at that level
    op = carrier.operator
    cells = {parent: reduce(op.combine, (carrier.cells[c] for c in children)) for parent, children in plan.folds.items()}
    provenance = {parent: frozenset().union(*(carrier.sources(c) for c in children)) for parent, children in plan.folds.items()}
    return carrier._with(cells, plan.parents, provenance=provenance, gaps=plan.gaps)


# ---------------------------------------------------------------------------
# Coordinate-level primitives: restrict, classify, shift
# ---------------------------------------------------------------------------


def restrict(carrier: Carrier[V], predicate: Callable[[Coordinate], bool]) -> Carrier[V]:
    """Keep the coordinates the predicate accepts — in cells and in expected alike. Never fails."""
    return carrier._with({c: v for c, v in carrier.cells.items() if predicate(c)},
                         frozenset(c for c in carrier.expected if predicate(c)),
                         provenance={c: s for c, s in carrier.provenance.items() if predicate(c)},
                         gaps={c: g for c, g in carrier.gaps.items() if predicate(c)})


def slice(carrier: Carrier[V], **classifications: str) -> Carrier[V]:
    """``restrict`` to coordinates carrying every given classification value."""
    wanted = tuple(sorted(classifications.items()))
    return restrict(carrier, lambda c: all(c.classification(name) == value for name, value in wanted))


def classify(carrier: Carrier[V], name: str, assign: Callable[[Coordinate], str]) -> Carrier[V] | Refuse:
    """Give every coordinate a classification computed from it — a shift from the hour, a
    day type from the date. Applied to leaves before rolling, it turns a classification into
    a key dimension of everything rolled from them."""
    if any(c.classification(name) is not None for c in carrier.expected):
        return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION, f'coordinates already carry a {name!r} classification')

    def renamed(c: Coordinate) -> Coordinate:
        return c.with_classifications(**{name: assign(c)})

    return carrier._with({renamed(c): v for c, v in carrier.cells.items()},
                         frozenset(renamed(c) for c in carrier.expected),
                         provenance={renamed(c): frozenset(renamed(s) for s in sources) for c, sources in carrier.provenance.items()},
                         gaps={renamed(c): frozenset(renamed(g) for g in gap) for c, gap in carrier.gaps.items()})


def rekey(carrier: Carrier[V], relabel: Callable[[Coordinate], Coordinate]) -> Carrier[V] | Refuse:
    """Re-address every coordinate — last month's cells onto this month's anchors, a peer's
    cells onto this subject's key — so that ``join`` can align them. A relabeling is a functor:
    it keeps the operator tag, so accumulators may be moved as freely as values. Provenance
    keeps pointing at the original leaves. The relabeling must be injective on the expected set."""
    moved = {c: relabel(c) for c in carrier.expected}
    if len(set(moved.values())) != len(moved):
        return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION, 'relabeling is not injective on the expected set')
    return carrier._with({moved[c]: v for c, v in carrier.cells.items()}, frozenset(moved.values()),
                         provenance={moved[c]: carrier.sources(c) for c in carrier.cells},
                         gaps={moved[c]: g for c, g in carrier.gaps.items()})


def shift(carrier: Carrier[V], dimension: Dimension, rekey_fn: Callable[[str], str]) -> Carrier[V] | Refuse:
    """``rekey`` along one dimension at the same level: a function on that dimension's key."""
    def moved(c: Coordinate) -> Coordinate:
        level, key = c.along(dimension)
        return c.moved(dimension, level, rekey_fn(key))

    return rekey(carrier, moved)


# ---------------------------------------------------------------------------
# Pointwise and binary
# ---------------------------------------------------------------------------


def map(carrier: Carrier[V], fn: Callable[[V], W]) -> Carrier[W] | Refuse:
    """Pointwise transform of values. Refused over accumulators: it would break the
    guarantee that whatever carries an operator tag can still be combined by it."""
    if not carrier.is_values:
        return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION, 'map over accumulators is not defined; lower first')
    return carrier._with({c: fn(v) for c, v in carrier.cells.items()}, carrier.expected)


def join(left: Carrier[V], right: Carrier[W]) -> Carrier[tuple[V, W]] | Refuse:
    """Align two value carriers on coordinate. Cells are inner — a pair exists only where both
    sides have a value — but the expected set is the *union*: a coordinate one side expected
    and the other lacks is a gap of the join, not a coordinate that quietly stops mattering.
    Reported-ness is inherited from either side."""
    if not (left.is_values and right.is_values):
        return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION, 'join is defined over values; lower both sides first')
    expected = left.expected | right.expected
    cells = {c: (left.cells[c], right.cells[c]) for c in expected if c in left.cells and c in right.cells}
    return Carrier(cells, expected, None, tuple(dict.fromkeys((*left.lowered_from, *right.lowered_from))),
                   {c: left.sources(c) | right.sources(c) for c in cells}, {**left.gaps, **right.gaps})


# ---------------------------------------------------------------------------
# Derived — vocabulary, defined by expansion
# ---------------------------------------------------------------------------


def scale(carrier: Carrier[float], rate: float | Mapping[Coordinate, float]) -> Carrier[float] | Refuse:
    """``map(v × rate)``. A per-coordinate rate is applied per coordinate; a coordinate with
    no rate is a refusal, never a silent 1.0."""
    if not carrier.is_values:
        return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION, 'scale over accumulators is not defined; lower first')
    if isinstance(rate, Mapping):
        unrated = [c for c in carrier.cells if c not in rate]
        if unrated:
            return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION, f'no rate for {len(unrated)} coordinate(s)', {'coordinates': frozenset(unrated)})
        return carrier._with({c: v * rate[c] for c, v in carrier.cells.items()}, carrier.expected)
    return map(carrier, lambda v: v * rate)


def diff(primary: Carrier[float], baseline: Carrier[float]) -> Carrier[float] | Refuse:
    """``map(a − b, join(primary, baseline))``. A baseline from another period or peer is
    first moved onto the primary's coordinates with :func:`shift`."""
    joined = join(primary, baseline)
    if isinstance(joined, Refuse):
        return joined
    return map(joined, lambda pair: pair[0] - pair[1])


# ---------------------------------------------------------------------------
# Boundary
# ---------------------------------------------------------------------------


def rank(carrier: Carrier[V], *, key: Callable[[V], Any] | None = None, descending: bool = True) -> tuple[tuple[Coordinate, V], ...] | Refuse:
    """Order cells by value. Leaves the algebra: the result is a sequence, not a carrier."""
    if not carrier.is_values:
        return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION, 'rank orders values; lower first')
    scorer = key or (lambda v: v)
    return tuple(sorted(carrier.cells.items(), key=lambda item: scorer(item[1]), reverse=descending))
