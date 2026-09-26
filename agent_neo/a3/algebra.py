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
- ``lowered_from`` — the operators whose *reported output* these values are, in order.
  Empty means leaf observations. A reported value re-enters only an operator that is not in
  that history or is *exact* (its report is its accumulator): a sum of daily sums is a sum, a
  mean of daily sums is a mean, a mean of means is refused. That, with the tag, is what
  makes mean-of-means and p95-of-p95s unconstructible while leaving "average daily total"
  writable.

**Primitives.** ``lift`` · ``roll`` · ``restrict`` · ``rekey`` · ``map`` · ``join`` · ``lower``. Each returns a carrier or a :class:`~agent_neo.a3.product.Refuse`;
none raises for anything a plan could produce (feeding an operator a value type it does not
take is a plan-authoring error and raises). Every primitive also *accepts* a ``Refuse`` in any
carrier position and returns it unchanged, so the algebra is closed over ``Carrier | Refuse``
and a composition never checks between steps (:data:`~agent_neo.a3.laws.LAW_REFUSE_ABSORBS`).
``slice``, ``shift``, ``classify``, ``scale`` and ``diff`` are provided but *derived*; the laws
test that they equal their expansions. ``rank`` is a boundary projection to an ordered
sequence, not an operation on carriers.

**Provenance** rides along: each derived cell knows the stored leaves it came from — as
:class:`~agent_neo.a3.product.Identity`, family and coordinate, because a coordinate alone
names nothing once two families have been joined — so an explanation is a lookup, not a
graph walk, and lineage is provenance's keys.
"""


from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from functools import reduce, wraps
from typing import Any, Callable, Generic, Iterable, Iterator, Mapping, TypeVar

from agent_neo.a3.carrier import ABSENT, Absent, Coordinate, CoverageState, Dimension
from agent_neo.a3.lattice import Lattice
from agent_neo.a3.operators import IllegalOperatorUse
from agent_neo.a3.product import Identity, Refuse, RefuseReason

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
    'restrict',
    'roll',
    'roll_refusal',
    'scale',
    'shift',
    'slice',
    'slice_refusal',
)


V = TypeVar('V')
W = TypeVar('W')


class OnMissing(StrEnum):
    """What a roll does with a parent whose expected children are not all present."""

    REFUSE = 'refuse'  # the whole roll is a Refuse(INCOMPLETE_PARTITION) naming the parent and the gap
    ABSENT = 'absent'  # the parent is absent (never zero); ``gaps`` names what it lacked
    PARTIAL = 'partial'  # fold what is present, if the operator says that is an estimate and not an undercount


F = TypeVar('F', bound=Callable[..., Any])


def _absorbing(primitive: F) -> F:
    """A ``Refuse`` in any argument position is the result. The first refusal in a composition
    is what the composition returns; nothing downstream of it runs."""
    @wraps(primitive)
    def absorbing(*args: Any, **kwargs: Any) -> Any:
        for argument in (*args, *kwargs.values()):
            if isinstance(argument, Refuse):
                return argument
        return primitive(*args, **kwargs)
    return absorbing  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Coverage: a report, derived on demand
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Coverage:
    known: frozenset[Coordinate]
    missing: frozenset[Coordinate]

    @property
    def complete(self) -> bool:
        return not self.missing

    def state(self, coordinate: Coordinate) -> CoverageState | None:
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
    #: derived coordinate → the stored leaves it was computed from; a leaf carrier has no entries
    provenance: Mapping[Coordinate, frozenset[Identity]] = field(default_factory=dict)
    #: parent → the children it lacked; populated by ABSENT and PARTIAL rolls
    gaps: Mapping[Coordinate, frozenset[Coordinate]] = field(default_factory=dict)
    #: the product family a *leaf* carrier was read from; ``None`` once cells are derived
    family: str | None = None

    def __post_init__(self) -> None:
        stray = set(self.cells) - self.expected
        if stray:
            raise ValueError(f'{len(stray)} cell(s) outside the expected set, e.g. {next(iter(stray))!r}')

    @classmethod
    def of(cls, cells: Mapping[Coordinate, V], *, operator: Any | None = None, family: str | None = None) -> Carrier[V]:
        """A carrier whose expected set is exactly its cells (nothing known to be missing)."""
        return cls(dict(cells), frozenset(cells), operator, family=family)

    def _with(self, cells: Mapping[Coordinate, Any], expected: frozenset[Coordinate], **changes: Any) -> Carrier[Any]:
        fields = {'operator': self.operator, 'lowered_from': self.lowered_from, 'provenance': self.provenance, 'gaps': self.gaps,
                  'family': self.family}
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

    def sources(self, coordinate: Coordinate) -> frozenset[Identity]:
        """The stored leaves behind a cell. A leaf's source is itself, under the family it was
        read from; a carrier that knows no family and has no provenance entry knows nothing."""
        known = self.provenance.get(coordinate)
        if known is not None:
            return known
        return frozenset({Identity(self.family, coordinate)}) if self.family is not None else frozenset()

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
    name = type(operator).__name__
    if name in lowered_from and not operator.exact:
        return Refuse(RefuseReason.ILL_TYPED_ROLL,
                      f'these are reported {name} values; a {name} of {name}s is not a {name} (roll the stored accumulators, '
                      'or the leaves)', {'lowered_from': lowered_from, 'operator': operator})
    if not operator.mergeable:
        return Refuse(RefuseReason.NO_MERGEABLE_ACCUMULATOR,
                      f'{type(operator).__name__} is holistic with nothing bound to accumulate into', {'operator': operator})
    return None


@_absorbing
def lift(carrier: Carrier[V], operator: Any) -> Carrier[Any] | Refuse:
    """Values → accumulators of ``operator``. ``lowered_from`` is kept as history: what these
    values were reports of still matters to the next lift. For an exact operator re-entering its
    own reports this is rolling further; for anything else it is a change of unit of analysis."""
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


@_absorbing
def lower(carrier: Carrier[Any]) -> Carrier[Any] | Refuse:
    """Accumulators → reported values, remembered as such."""
    if carrier.is_values:
        return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION, 'carrier already holds values')
    op = carrier.operator
    reports = {c: op.lower(a) for c, a in carrier.cells.items()}
    return carrier._with({c: v for c, v in reports.items() if v is not ABSENT}, carrier.expected,  # an undefined report is a missing cell
                         operator=None, lowered_from=(*carrier.lowered_from, type(op).__name__))


# ---------------------------------------------------------------------------
# Roll
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RollPlan:
    """What a roll will do, decided from coordinates alone (shared by ``roll`` and ``shape``)."""

    parents: frozenset[Coordinate]
    folds: Mapping[Coordinate, tuple[Coordinate, ...]]  # parent → its present children, in fold order
    gaps: Mapping[Coordinate, frozenset[Coordinate]]  # parent → its missing children


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

    A parent's denominator is *intrinsic*: ``lattice.down(parent)``, less the candidates a
    bound classifier says would not carry the parent's classification value. It depends on the
    parent, the lattice and the classifiers — never on what else the carrier happens to hold —
    so a child no ask ever mentioned is a gap, and slicing before or after the roll gives the
    same answer. Without a classifier for a classification the carrier carries, every candidate
    is expected under the parent's value; a classification that varies along the rolled
    dimension then refuses rather than guesses. A child that carries a value the classifier
    would not assign it is refused: a mislabelled coordinate cannot be folded anywhere. A child
    with more than one parent is refused under every policy: a lattice that is not a partition
    is not missing data.
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

    bound = classifiers or {}
    for child in sorted(expected, key=repr):
        for name, value in child.classifications:
            if name in bound and bound[name](child) != value:
                return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION,
                              f'{child!r} carries {name}={value!r} but the classifier assigns {bound[name](child)!r}; a mislabelled '
                              'coordinate folds into nothing', {'coordinate': child, 'classification': name})

    parents: set[Coordinate] = set()
    for child in expected:
        level, key = child.along(dimension)
        ups = lattice.up(level, key, to_level)
        if len(ups) > 1:
            return Refuse(RefuseReason.DOUBLE_COUNTED,
                          f'{dimension.value} {key!r} rolls into more than one {to_level}; the hierarchy is not a partition',
                          {'coordinate': child, 'parents': frozenset(ups)})
        if not ups:
            return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION,
                          f'lattice places no {to_level} above {dimension.value} {key!r} at level {level!r}', {'coordinate': child})
        parents.add(child.moved(dimension, to_level, next(iter(ups))))

    folds: dict[Coordinate, tuple[Coordinate, ...]] = {}
    gaps: dict[Coordinate, frozenset[Coordinate]] = {}
    for parent in sorted(parents, key=repr):
        plevel, pkey = parent.along(dimension)
        admitted = [(name, value) for name, value in parent.classifications if name in bound]
        expected_children = frozenset(
            candidate
            for candidate in (parent.moved(dimension, child_level, key) for key in lattice.down(plevel, pkey, child_level))
            if all(bound[name](candidate) == value for name, value in admitted)
        )
        if not expected_children:
            return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION,
                          f'lattice is inconsistent: {(plevel, pkey)} lists none of the children that rolled into it', {'parent': parent})
        present_children = tuple(sorted((c for c in expected_children if c in present), key=repr))
        missing = expected_children - frozenset(present_children)
        if missing:
            if on_missing is OnMissing.REFUSE:
                return Refuse(RefuseReason.INCOMPLETE_PARTITION,
                              f'{dimension.value} {pkey!r} at {to_level!r} lacks {len(missing)} of {len(expected_children)} children',
                              {'parent': parent, 'missing': missing})
            gaps[parent] = missing
            if on_missing is OnMissing.ABSENT:
                continue
        if present_children:
            folds[parent] = present_children
    return RollPlan(frozenset(parents), folds, gaps)


@_absorbing
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
    # gaps name the finest coordinates known to be missing under the parent: a missing child, or what a folded child itself lacked
    gaps: dict[Coordinate, frozenset[Coordinate]] = {}
    for parent in plan.parents:
        finest = frozenset().union(*(carrier.gaps.get(c, frozenset({c})) for c in plan.gaps.get(parent, ())),
                                   *(carrier.gaps.get(c, frozenset()) for c in plan.folds.get(parent, ())))
        if finest:
            gaps[parent] = finest
    return carrier._with(cells, plan.parents, provenance=provenance, gaps=gaps, family=None)


# ---------------------------------------------------------------------------
# Coordinate-level primitives: restrict, rekey (with classify and shift derived)
# ---------------------------------------------------------------------------


@_absorbing
def restrict(carrier: Carrier[V], predicate: Callable[[Coordinate], bool]) -> Carrier[V] | Refuse:
    """Keep the coordinates the predicate accepts — in cells and in expected alike. Never fails."""
    return carrier._with({c: v for c, v in carrier.cells.items() if predicate(c)},
                         frozenset(c for c in carrier.expected if predicate(c)),
                         provenance={c: s for c, s in carrier.provenance.items() if predicate(c)},
                         gaps={c: g for c, g in carrier.gaps.items() if predicate(c)})


def slice_refusal(expected: Iterable[Coordinate], names: Iterable[str]) -> Refuse | None:
    """A slice on a classification the coordinates do not carry is refused, not empty: the
    absence of a key is not a value of it, and an empty carrier with an empty expected set
    would report itself complete."""
    coordinates = tuple(expected)
    for name in names:
        uncarried = [c for c in coordinates if c.classification(name) is None]
        if uncarried:
            return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION,
                          f'{len(uncarried)} of {len(coordinates)} coordinate(s) carry no {name!r} classification; classify first',
                          {'classification': name, 'coordinate': min(uncarried, key=repr)})
    return None


@_absorbing
def slice(carrier: Carrier[V], **classifications: str) -> Carrier[V] | Refuse:
    """``restrict`` to coordinates carrying every given classification value; refused when the
    coordinates do not carry the classification at all."""
    wanted = tuple(sorted(classifications.items()))
    refusal = slice_refusal(carrier.expected, (name for name, _ in wanted))
    if refusal is not None:
        return refusal
    return restrict(carrier, lambda c: all(c.classification(name) == value for name, value in wanted))


@_absorbing
def classify(carrier: Carrier[V], name: str, assign: Callable[[Coordinate], str]) -> Carrier[V] | Refuse:
    """``rekey`` with a classification computed from each coordinate — a shift from the hour,
    a day type from the date. Applied to leaves before rolling, it turns a classification into
    a key dimension of everything rolled from them; bind the same function as the roll's
    classifier and the denominator follows it."""
    if any(c.classification(name) is not None for c in carrier.expected):
        return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION, f'coordinates already carry a {name!r} classification')

    return rekey(carrier, lambda c: c.with_classifications(**{name: assign(c)}))


@_absorbing
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
                         gaps={moved[c]: g for c, g in carrier.gaps.items()}, family=None)


@_absorbing
def shift(carrier: Carrier[V], dimension: Dimension, rekey_fn: Callable[[str], str]) -> Carrier[V] | Refuse:
    """``rekey`` along one dimension at the same level: a function on that dimension's key."""
    def moved(c: Coordinate) -> Coordinate:
        level, key = c.along(dimension)
        return c.moved(dimension, level, rekey_fn(key))

    return rekey(carrier, moved)


# ---------------------------------------------------------------------------
# Pointwise and binary
# ---------------------------------------------------------------------------


@_absorbing
def map(carrier: Carrier[V], fn: Callable[[V], W]) -> Carrier[W] | Refuse:
    """Pointwise transform of values. Refused over accumulators: it would break the
    guarantee that whatever carries an operator tag can still be combined by it."""
    if not carrier.is_values:
        return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION, 'map over accumulators is not defined; lower first')
    return carrier._with({c: fn(v) for c, v in carrier.cells.items()}, carrier.expected)


@_absorbing
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
                   provenance={c: left.sources(c) | right.sources(c) for c in cells}, gaps={**left.gaps, **right.gaps})


# ---------------------------------------------------------------------------
# Derived — vocabulary, defined by expansion
# ---------------------------------------------------------------------------


@_absorbing
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


@_absorbing
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


@_absorbing
def rank(carrier: Carrier[V], *, key: Callable[[V], Any] | None = None, descending: bool = True) -> tuple[tuple[Coordinate, V], ...] | Refuse:
    """Order cells by value. Leaves the algebra: the result is a sequence, not a carrier."""
    if not carrier.is_values:
        return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION, 'rank orders values; lower first')
    scorer = key or (lambda v: v)
    return tuple(sorted(carrier.cells.items(), key=lambda item: scorer(item[1]), reverse=descending))
