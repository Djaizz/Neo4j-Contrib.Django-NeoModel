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

A recipe serves a whole family, so its leaves are *relative*: an :class:`AskFrom` leaf names
the product it reads and a function that derives its ask from the ask being served
(``Env.ask``). The product is stated on the leaf so dependencies stay static; evaluation
verifies the derived ask reads it. Reading a leaf is *ensuring* it: an interpreter binds
``Env.ensure`` and a leaf's instances are what that serves — a refused identity is a missing
cell, never a stale value read around the gate (:data:`~agent_neo.a3.laws.LAW_ENSURE_RECURSIVE`).
:func:`leaves` lists a term's leaves so the interpreter can ensure them first.
"""


from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping, Sequence, Union

from agent_neo.a3 import algebra
from agent_neo.a3.algebra import (
    Carrier,
    OnMissing,
    lift_refusal,
    plan_roll,
    roll_refusal,
    slice_refusal,
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
from agent_neo.a3.product import (
    PLAIN_KEY_SCHEME,
    Ask,
    Concept,
    FieldRole,
    Identity,
    Instance,
    KeyScheme,
    Refuse,
    RefuseReason,
)

__all__ = (
    'AskFrom',
    'Classify',
    'Ensure',
    'Env',
    'Join',
    'Lift',
    'Lower',
    'Map',
    'Rekey',
    'Restrict',
    'Roll',
    'Shape',
    'Shift',
    'Slice',
    'Term',
    'check_layers',
    'evaluate',
    'leaf_ask',
    'leaves',
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
class AskFrom:
    """A leaf's ask, relative to the ask being served: ``derive`` names an ``Env`` function
    ``Ask -> Ask``; ``product`` is what the derived ask must read."""

    product: str
    derive: str


@dataclass(frozen=True, slots=True)
class Ensure(_Node):
    """Materialize a product's ``field`` over an ask — literal, or derived from the ask being
    served — the leaf of every term."""

    ask: Ask | AskFrom
    field: str


@dataclass(frozen=True, slots=True)
class Lift(_Node):
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


Term = Union[Ensure, Lift, Roll, Restrict, Slice, Classify, Shift, Rekey, Map, Join, Lower]


def leaves(term: Term) -> tuple[Ensure, ...]:
    """A term's ``Ensure`` leaves, left to right."""
    if isinstance(term, Ensure):
        return (term,)
    if isinstance(term, Join):
        return (*leaves(term.left), *leaves(term.right))
    return leaves(term.term)


def products_read(term: Term) -> frozenset[str]:
    """The families a term's leaves read — literal or relative: a concept's derived dependencies."""
    return frozenset(leaf.ask.product for leaf in leaves(term))


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
    #: the interpreter's key scheme; coordinates are canonicalized under it at every leaf
    scheme: KeyScheme = PLAIN_KEY_SCHEME
    #: the ask being served, which ``AskFrom`` leaves derive theirs from
    ask: Ask | None = None
    #: when bound, a leaf's instances are what this serves for the leaf's ask — the gate-approved
    #: ones — and a refused identity is a missing cell; ``shape`` and ``evaluate`` both read it
    ensure: Callable[[Ask], Sequence[Instance | Refuse]] | None = None

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


def leaf_ask(node: Ensure, env: Env) -> Ask:
    """The ask a leaf reads: as written, or derived from the ask being served."""
    if isinstance(node.ask, Ask):
        return node.ask
    if env.ask is None:
        raise KeyError(f'leaf reads {node.ask.product!r} relative to the ask being served, and the environment binds none')
    derived = env.function(node.ask.derive)(env.ask)
    if derived.product != node.ask.product:
        raise ValueError(f'{node.ask.derive!r} derived an ask for {derived.product!r}; the leaf declares {node.ask.product!r}')
    return derived


def _leaf_instances(ask: Ask, identities: tuple[Identity, ...], env: Env) -> tuple[Instance, ...]:
    if env.ensure is not None:
        return tuple(r for r in env.ensure(ask) if isinstance(r, Instance))
    return env.store.fetch(identities)


def _ensure_shape(node: Ensure, env: Env) -> Shape:
    ask = leaf_ask(node, env)
    identities = env.resolver.resolve(ask)
    expected = frozenset(env.scheme.canonical(i.coordinate) for i in identities)
    served = _leaf_instances(ask, identities, env) if env.ensure is not None else env.store.present(identities)
    present = frozenset(env.scheme.canonical(i.identity.coordinate if isinstance(i, Instance) else i.coordinate) for i in served)
    spec = env.concepts[ask.product].field(node.field)
    operator = env.operators.get(spec.operator) if spec.role is FieldRole.ACCUMULATOR else None
    lowered = (lowered_name(spec, env.operators, node.field),) if spec.role is FieldRole.REPORTED else ()
    return Shape(expected, present, operator, lowered)


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
        if isinstance(term, Slice):
            refusal = slice_refusal(inner.expected, (name for name, _ in term.classifications))
            if refusal is not None:
                return refusal
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
    """Run the plan over values. No refusal is checked between steps: every primitive absorbs
    a ``Refuse`` in any carrier position (:data:`~agent_neo.a3.laws.LAW_REFUSE_ABSORBS`)."""
    if isinstance(term, Ensure):
        ask = leaf_ask(term, env)
        identities = env.resolver.resolve(ask)
        instances = _leaf_instances(ask, identities, env)
        spec = env.concepts[ask.product].field(term.field)
        return carrier_from_instances(identities, instances, field=term.field, spec=spec, operators=env.operators, scheme=env.scheme)
    if isinstance(term, Join):
        return algebra.join(evaluate(term.left, env), evaluate(term.right, env))

    inner = evaluate(term.term, env)
    if isinstance(term, Lift):
        return algebra.lift(inner, env.operators.get(term.operator))
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
