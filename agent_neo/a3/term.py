"""Terms — what an agent writes — and shapes — what is decided before any value is touched.

A term is a tree of frozen nodes that name operators, lattices and functions rather than
carrying them; an :class:`Env` binds the names. Two interpretations exist for every term:

- :func:`shape` runs the plan on *coordinates only* — the ask's expected identities, the
  store's report of which are present, the operator tag — and returns the shape of the result
  or the :class:`~agent_neo.a3.product.Refuse` evaluation would return. Ill-typed rolls,
  unmergeable operators, incomplete partitions, double counting, immature parents and layer
  violations are all decided here, without fetching a payload.
- :func:`evaluate` fetches the instances and runs the same plan over values.

The two agree by construction: every decision they share is made by one function
(:func:`~agent_neo.a3.algebra.plan_roll`, :func:`~agent_neo.a3.algebra.lift_refusal`,
:func:`~agent_neo.a3.algebra.roll_refusal`). That agreement is
:data:`~agent_neo.a3.laws.LAW_SHAPE_SOUND`, and it is what makes WHAT/HOW separation real:
a term can be checked, planned, explained and rewritten before it is run.

A :class:`~agent_neo.a3.product.Concept` may hold a term as its recipe. Its dependencies are
then *derived* — the products its ``Ensure`` leaves read — and :func:`check_layers` refuses a
recipe that reads above its own layer.
"""


from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping, Union

from agent_neo.a3 import algebra
from agent_neo.a3.algebra import (
    Carrier,
    OnMissing,
    lift_refusal,
    plan_roll,
    roll_refusal,
)
from agent_neo.a3.bridge import Resolver, Store, carrier_from_instances, lowered_name
from agent_neo.a3.carrier import (
    Classifications,
    Coordinate,
    Dimension,
    freeze_classifications,
)
from agent_neo.a3.gates import maturity_gate
from agent_neo.a3.lattice import Lattice
from agent_neo.a3.operators import OperatorRegistry
from agent_neo.a3.product import Ask, Concept, FieldRole, Refuse, RefuseReason

__all__ = (
    'Classify',
    'Ensure',
    'Env',
    'Join',
    'Lift',
    'Lower',
    'Map',
    'Rekey',
    'Relift',
    'Restrict',
    'Roll',
    'Shape',
    'Shift',
    'Slice',
    'Term',
    'check_layers',
    'evaluate',
    'products_read',
    'shape',
)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


class _Node:
    """Shared by every node so a term satisfies :class:`~agent_neo.a3.product.TermLike`."""

    def products_read(self) -> frozenset[str]:
        return products_read(self)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class Ensure(_Node):
    """Materialize a product's ``field`` over the ask: the leaf of every term."""

    ask: Ask
    field: str


@dataclass(frozen=True, slots=True)
class Lift(_Node):
    term: Term
    operator: str


@dataclass(frozen=True, slots=True)
class Relift(_Node):
    """Re-enter a distributive operator's own reported values as its accumulators."""

    term: Term
    operator: str


@dataclass(frozen=True, slots=True)
class Roll(_Node):
    term: Term
    dimension: Dimension
    to_level: str
    lattice: str
    on_missing: OnMissing = OnMissing.REFUSE


@dataclass(frozen=True, slots=True)
class Restrict(_Node):
    term: Term
    predicate: str


@dataclass(frozen=True, slots=True)
class Slice(_Node):
    term: Term
    classifications: Classifications

    def __post_init__(self) -> None:
        object.__setattr__(self, 'classifications', freeze_classifications(self.classifications))


@dataclass(frozen=True, slots=True)
class Classify(_Node):
    term: Term
    name: str
    assign: str


@dataclass(frozen=True, slots=True)
class Shift(_Node):
    term: Term
    dimension: Dimension
    rekey: str  # a function on that dimension's key


@dataclass(frozen=True, slots=True)
class Rekey(_Node):
    term: Term
    relabel: str  # a function Coordinate -> Coordinate


@dataclass(frozen=True, slots=True)
class Map(_Node):
    term: Term
    fn: str


@dataclass(frozen=True, slots=True)
class Join(_Node):
    left: Term
    right: Term


@dataclass(frozen=True, slots=True)
class Lower(_Node):
    term: Term


Term = Union[Ensure, Lift, Relift, Roll, Restrict, Slice, Classify, Shift, Rekey, Map, Join, Lower]


def products_read(term: Term) -> frozenset[str]:
    """The families a term's ``Ensure`` leaves read: a concept's derived dependencies."""
    if isinstance(term, Ensure):
        return frozenset({term.ask.product})
    if isinstance(term, Join):
        return products_read(term.left) | products_read(term.right)
    return products_read(term.term)


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Env:
    """What a term's names resolve to. The algebra ships none of these values."""

    operators: OperatorRegistry
    lattices: Mapping[str, Lattice]
    resolver: Resolver
    store: Store
    concepts: Mapping[str, Concept]  # by family
    functions: Mapping[str, Callable[..., Any]] = field(default_factory=dict)
    #: classification name → the name of the function that assigns it; consulted by every roll
    #: to decide whether a never-asked child belongs to a classified parent
    classifiers: Mapping[str, str] = field(default_factory=dict)
    #: the evaluation instant and the maturity slot for parents a roll produces along the period dimension
    now: datetime | None = None
    maturity_lag: timedelta | None = None
    exclusive_end: Callable[[str, str], datetime] | None = None  # (granularity, anchor) → period end

    def function(self, name: str) -> Callable[..., Any]:
        try:
            return self.functions[name]
        except KeyError:
            raise KeyError(f'term names no function {name!r} in the environment') from None

    def classifier_functions(self) -> Mapping[str, Callable[[Coordinate], str]]:
        return {name: self.function(fn) for name, fn in self.classifiers.items()}

    def lattice(self, name: str) -> Lattice:
        try:
            return self.lattices[name]
        except KeyError:
            raise KeyError(f'term names no lattice {name!r} in the environment') from None


# ---------------------------------------------------------------------------
# Shape: the value-free interpretation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Shape:
    expected: frozenset[Coordinate]
    present: frozenset[Coordinate]
    operator: Any | None = None
    lowered_from: tuple[str, ...] = ()

    @property
    def is_values(self) -> bool:
        return self.operator is None

    @property
    def missing(self) -> frozenset[Coordinate]:
        return self.expected - self.present

    def _with(self, expected: frozenset[Coordinate], present: frozenset[Coordinate], **changes: Any) -> Shape:
        fields = {'operator': self.operator, 'lowered_from': self.lowered_from}
        fields.update(changes)
        return Shape(expected, present, **fields)


def _ensure_shape(node: Ensure, env: Env) -> Shape:
    identities = env.resolver.resolve(node.ask)
    present = env.store.present(identities)
    spec = env.concepts[node.ask.product].field(node.field)
    operator = env.operators.get(spec.operator) if spec.role is FieldRole.ACCUMULATOR else None
    lowered = (lowered_name(spec, env.operators),) if spec.role is FieldRole.REPORTED else ()
    return Shape(frozenset(i.coordinate for i in identities), frozenset(i.coordinate for i in present), operator, lowered)


def _immature_parents(parents: frozenset[Coordinate], env: Env) -> Refuse | None:
    if env.exclusive_end is None or env.now is None or env.maturity_lag is None:
        return None
    for parent in sorted(parents, key=repr):
        refusal = maturity_gate(exclusive_end=env.exclusive_end(*parent.period), now=env.now, lag=env.maturity_lag)
        if refusal is not None:
            return Refuse(RefuseReason.IMMATURE_WINDOW, f'rolled period {parent.period_anchor!r} has not settled', {**refusal.context, 'coordinate': parent})
    return None


def shape(term: Term, env: Env) -> Shape | Refuse:
    """Decide everything about a term that does not need a value."""
    if isinstance(term, Ensure):
        return _ensure_shape(term, env)
    if isinstance(term, Join):
        left, right = shape(term.left, env), shape(term.right, env)
        if isinstance(left, Refuse):
            return left
        if isinstance(right, Refuse):
            return right
        if not (left.is_values and right.is_values):
            return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION, 'join is defined over values; lower both sides first')
        return Shape(left.expected | right.expected, left.present & right.present, None,
                     tuple(dict.fromkeys((*left.lowered_from, *right.lowered_from))))

    inner = shape(term.term, env)
    if isinstance(inner, Refuse):
        return inner
    if isinstance(term, Lift):
        operator = env.operators.get(term.operator)
        return lift_refusal(inner.operator, inner.lowered_from, operator) or inner._with(inner.expected, inner.present, operator=operator)
    if isinstance(term, Relift):
        probe = algebra.relift(Carrier({}, inner.expected, inner.operator, inner.lowered_from), env.operators.get(term.operator))
        return probe if isinstance(probe, Refuse) else inner._with(inner.expected, inner.present, operator=probe.operator, lowered_from=())
    if isinstance(term, Rekey):
        relabel = env.function(term.relabel)
        expected = frozenset(relabel(c) for c in inner.expected)
        if len(expected) != len(inner.expected):
            return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION, 'relabeling is not injective on the expected set')
        return inner._with(expected, frozenset(relabel(c) for c in inner.present))
    if isinstance(term, Lower):
        if inner.is_values:
            return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION, 'carrier already holds values')
        return inner._with(inner.expected, inner.present, operator=None, lowered_from=(*inner.lowered_from, type(inner.operator).__name__))
    if isinstance(term, Roll):
        refusal = roll_refusal(inner.operator, inner.lowered_from, term.on_missing)
        if refusal is not None:
            return refusal
        plan = plan_roll(inner.expected, inner.present, dimension=term.dimension, to_level=term.to_level,
                         lattice=env.lattice(term.lattice), on_missing=term.on_missing, classifiers=env.classifier_functions())
        if isinstance(plan, Refuse):
            return plan
        if term.dimension is Dimension.PERIOD:
            immature = _immature_parents(plan.parents, env)
            if immature is not None:
                return immature
        return inner._with(plan.parents, frozenset(plan.folds))
    if isinstance(term, (Restrict, Slice)):
        keep = _keep(term, env)
        return inner._with(frozenset(c for c in inner.expected if keep(c)), frozenset(c for c in inner.present if keep(c)))
    if isinstance(term, Classify):
        if any(c.classification(term.name) is not None for c in inner.expected):
            return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION, f'coordinates already carry a {term.name!r} classification')
        assign = env.function(term.assign)
        rename = lambda c: c.with_classifications(**{term.name: assign(c)})
        return inner._with(frozenset(rename(c) for c in inner.expected), frozenset(rename(c) for c in inner.present))
    if isinstance(term, Shift):
        rekey = env.function(term.rekey)
        move = lambda c: c.moved(term.dimension, c.along(term.dimension)[0], rekey(c.along(term.dimension)[1]))
        expected = frozenset(move(c) for c in inner.expected)
        if len(expected) != len(inner.expected):
            return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION, f'rekeying along {term.dimension.value} is not injective on the expected set')
        return inner._with(expected, frozenset(move(c) for c in inner.present))
    if isinstance(term, Map):
        if not inner.is_values:
            return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION, 'map over accumulators is not defined; lower first')
        return inner
    raise TypeError(f'not a term: {term!r}')


def _keep(term: Restrict | Slice, env: Env) -> Callable[[Coordinate], bool]:
    if isinstance(term, Restrict):
        return env.function(term.predicate)
    wanted = term.classifications
    return lambda c: all(c.classification(name) == value for name, value in wanted)


# ---------------------------------------------------------------------------
# Evaluate: the same plan, over values
# ---------------------------------------------------------------------------


def evaluate(term: Term, env: Env) -> Carrier[Any] | Refuse:
    if isinstance(term, Ensure):
        identities = env.resolver.resolve(term.ask)
        instances = env.store.fetch(identities)
        spec = env.concepts[term.ask.product].field(term.field)
        return carrier_from_instances(identities, instances, field=term.field, spec=spec, operators=env.operators)
    if isinstance(term, Join):
        left, right = evaluate(term.left, env), evaluate(term.right, env)
        if isinstance(left, Refuse):
            return left
        if isinstance(right, Refuse):
            return right
        return algebra.join(left, right)

    inner = evaluate(term.term, env)
    if isinstance(inner, Refuse):
        return inner
    if isinstance(term, Lift):
        return algebra.lift(inner, env.operators.get(term.operator))
    if isinstance(term, Relift):
        return algebra.relift(inner, env.operators.get(term.operator))
    if isinstance(term, Rekey):
        return algebra.rekey(inner, env.function(term.relabel))
    if isinstance(term, Lower):
        return algebra.lower(inner)
    if isinstance(term, Roll):
        # The shape checker already applied maturity to the parents; evaluation re-checks so the two never disagree.
        rolled = algebra.roll(inner, dimension=term.dimension, to_level=term.to_level, lattice=env.lattice(term.lattice),
                              on_missing=term.on_missing, classifiers=env.classifier_functions())
        if isinstance(rolled, Refuse) or term.dimension is not Dimension.PERIOD:
            return rolled
        return _immature_parents(rolled.expected, env) or rolled
    if isinstance(term, Restrict):
        return algebra.restrict(inner, env.function(term.predicate))
    if isinstance(term, Slice):
        return algebra.slice(inner, **dict(term.classifications))
    if isinstance(term, Classify):
        return algebra.classify(inner, term.name, env.function(term.assign))
    if isinstance(term, Shift):
        return algebra.shift(inner, term.dimension, env.function(term.rekey))
    if isinstance(term, Map):
        return algebra.map(inner, env.function(term.fn))
    raise TypeError(f'not a term: {term!r}')


# ---------------------------------------------------------------------------
# Concepts that hold a term
# ---------------------------------------------------------------------------


def check_layers(concept: Concept, env: Env) -> Refuse | None:
    """A recipe may read products at its own layer or below, never above."""
    for family in sorted(concept.depends_on):
        upstream = env.concepts.get(family)
        if upstream is None:
            return Refuse(RefuseReason.LAYER_VIOLATION, f'{concept.family!r} reads unknown product {family!r}')
        if not concept.layer.may_depend_on(upstream.layer):
            return Refuse(RefuseReason.LAYER_VIOLATION,
                          f'{concept.family!r} ({concept.layer.label}) reads {family!r} ({upstream.layer.label}); a product may depend only on its own layer or below',
                          {'concept': concept.family, 'reads': family})
    return None
