"""Product layer: the vocabulary of stored analytical answers.

- :class:`Layer` and :class:`LifecycleStatus` — the two enumerations every analytical
  product shares. Defined here, at the floor, and re-exported by the graph-bound interpreter
  under its historical names; the dependency runs interpreter → algebra, never the reverse.
- :class:`Concept` — a *family* plus a *revision*. The family is the stable name a product
  is known by (it goes in the key); the revision is the store's own key for the recipe that
  computed an instance (opaque here; it is what gets retired). A concept declares what each
  payload field *is* (:class:`Field`): a leaf observation, an operator's accumulator held in
  named columns, or a reported value. That declaration is what lets the bridge rebuild a
  stored ``(mean, count)`` as a mean accumulator and refuse to re-average a stored mean.
- :class:`Identity` — a family at a :class:`~agent_neo.a3.carrier.Coordinate`. Its
  ``cache_key`` is produced through a :class:`KeyScheme`, so the same identity can address
  nodes an interpreter wrote under its own conventions, byte for byte.
- :class:`Instance` — one computed answer at an identity, carrying what the three gates
  need: when it was computed, by which revision, and whether lineage has flagged it.
- :class:`Ask` — the canonical request. Policy *slots* (a staleness bound, a maturity lag)
  whose values a domain supplies; no field that forces a recompute, because recompute is
  derived (:data:`~agent_neo.a3.laws.LAW_REDO_DERIVED`).
- :class:`Refuse` — the first-class result for a plan the algebra will not execute. Every
  :class:`RefuseReason` names the operation that produces it; a reason nothing produces is
  deleted.
"""


from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import IntEnum, StrEnum
from typing import Any, Mapping, Protocol, runtime_checkable

from agent_neo.a3.carrier import Classifications, Coordinate, freeze_classifications

__all__ = (
    'PLAIN_KEY_SCHEME',
    'Ask',
    'Concept',
    'Field',
    'FieldRole',
    'Identity',
    'Instance',
    'KeyScheme',
    'Layer',
    'LifecycleStatus',
    'LineageRef',
    'Refuse',
    'RefuseReason',
    'TermLike',
    'servable',
)


# ---------------------------------------------------------------------------
# Shared vocabulary
# ---------------------------------------------------------------------------


class Layer(IntEnum):
    """The layered stack every product sits in: ``SOURCE`` (0) … ``VIEW`` (4).

    ``SOURCE`` is the source-observation leaf that grounds lineage; it is not itself a
    computed product. A product may depend only on products at the same or a lower layer
    (checked by :func:`agent_neo.a3.term.shape` for concepts that hold a term), and only
    ``VIEW`` crosses the serving boundary.
    """

    SOURCE = 0
    FACT = 1
    METRIC = 2
    INTERPRETATION = 3
    VIEW = 4

    @property
    def rank(self) -> int:
        return int(self)

    @property
    def label(self) -> str:
        return self.name.lower()

    def may_depend_on(self, other: Layer) -> bool:
        return other.rank <= self.rank

    @property
    def is_served(self) -> bool:
        return self is Layer.VIEW


class LifecycleStatus(StrEnum):
    """What is current, in place of version numbers.

    ``OFFICIAL`` and ``PROVISIONAL`` are both in circulation (served, inside cascade scope);
    ``RETIRED`` is the only "no longer current" state, kept for audit until swept. Evolving
    anything is mint-new plus flip-prior-to-``RETIRED``; no supersession edge, no fourth state.
    """

    OFFICIAL = 'official'
    PROVISIONAL = 'provisional'
    RETIRED = 'retired'


# ---------------------------------------------------------------------------
# Refusal
# ---------------------------------------------------------------------------


class RefuseReason(StrEnum):
    """Why the algebra will not execute a plan. Each names its producer."""

    ILL_TYPED_ROLL = 'ill_typed_roll'  # roll/lift: rolling values, lifting accumulators, or lifting reported values
    NO_MERGEABLE_ACCUMULATOR = 'no_mergeable_accumulator'  # lift/roll: a holistic operator with nothing to accumulate into
    INCOMPLETE_PARTITION = 'incomplete_partition'  # roll: a parent whose children are not all present
    DOUBLE_COUNTED = 'double_counted'  # roll: a child that rolls into more than one parent
    UNSUPPORTED_COMPOSITION = 'unsupported_composition'  # map/join/shift/classify/scale applied to a shape they do not accept
    IMMATURE_WINDOW = 'immature_window'  # gate / term: the period has not settled
    LAYER_VIOLATION = 'layer_violation'  # check_layers: a concept reads a product above its own layer
    NOT_SERVABLE = 'not_servable'  # servable: only VIEW-layer products cross the serving boundary
    NO_RECIPE = 'no_recipe'  # ensure: the identity is missing or invalid and its concept holds no term to compute it from


@dataclass(frozen=True, slots=True)
class Refuse:
    reason: RefuseReason
    detail: str = ''
    context: Mapping[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Identity and its key
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KeyScheme:
    """How an identity's classifications serialize into its cache key.

    ``entries`` is an *ordered* tuple of ``(name, alias, neutral)``: the classifications an
    interpreter knows, the short code it writes for each, and the value meaning "unsliced".
    The rule an interpreter's keys obey, and this reproduces byte for byte:

    - if every scheme'd classification is neutral or absent, there is no suffix at all —
      keys written before classifications existed are unchanged;
    - otherwise *every* scheme'd classification is written, in scheme order, with the
      neutral value filled in where the coordinate has none;
    - classifications the scheme does not know follow, in name order, unaliased.

    The plain scheme (no entries) writes every classification in name order.
    """

    entries: tuple[tuple[str, str, str], ...] = ()

    def suffix(self, classifications: Classifications) -> str:
        given = dict(classifications)
        known = {name for name, _, _ in self.entries}
        parts: list[str] = []
        if self.entries and any(given.get(name, neutral) != neutral for name, _, neutral in self.entries):
            parts += [f'|{alias}={given.get(name, neutral)}' for name, alias, neutral in self.entries]
        parts += [f'|{name}={value}' for name, value in classifications if name not in known]
        return ''.join(parts)


    def canonical(self, coordinate: Coordinate) -> Coordinate:
        """The coordinate with every scheme'd classification at its neutral value removed.

        Two coordinates that differ only by an explicit neutral pair name one slot and one
        key; a carrier keyed by both would hold one answer twice. Resolvers and bridges
        canonicalize before anything is keyed.
        """
        neutral = {name: value for name, _, value in self.entries}
        kept = tuple((name, value) for name, value in coordinate.classifications if neutral.get(name) != value)
        return replace(coordinate, classifications=kept) if kept != coordinate.classifications else coordinate


PLAIN_KEY_SCHEME = KeyScheme()


@dataclass(frozen=True, slots=True)
class Identity:
    """A product family at a coordinate: the de-versioned address of one stored answer."""

    product: str
    coordinate: Coordinate

    def cache_key(self, scheme: KeyScheme = PLAIN_KEY_SCHEME) -> str:
        c = self.coordinate
        return (
            f'{self.product}|{c.scope_name}|{c.subject_kind}={c.subject_key}|'
            f'{c.temporal_granularity}|{c.period_anchor}{scheme.suffix(c.classifications)}'
        )


# ---------------------------------------------------------------------------
# Concept: family + revision + what its fields are
# ---------------------------------------------------------------------------


class FieldRole(StrEnum):
    """What a payload field holds, which decides what the algebra may do with it."""

    LEAF = 'leaf'  # an observation; may be lifted into any operator
    ACCUMULATOR = 'accumulator'  # an operator's mergeable state; enters the algebra already tagged, may be rolled further
    REPORTED = 'reported'  # an operator's lowered output; may be read, mapped, joined — never lifted


@dataclass(frozen=True, slots=True)
class Field:
    role: FieldRole
    operator: str | None = None  # registry name, for ACCUMULATOR and REPORTED
    #: for an ACCUMULATOR: the payload names holding the operator's storage columns, positionally
    #: (``Mean.columns == ('mean', 'count')`` stored as ``('average_temperature', 'source_hour_count')``);
    #: ``None`` means the field's own name, which suits a one-column operator
    columns: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if (self.role is FieldRole.LEAF) == (self.operator is not None):
            raise ValueError('a LEAF field names no operator; ACCUMULATOR and REPORTED fields must name theirs')
        if self.columns is not None and self.role is not FieldRole.ACCUMULATOR:
            raise ValueError('only an ACCUMULATOR field is stored in columns')


@runtime_checkable
class TermLike(Protocol):
    """What a concept's recipe must expose for its dependencies to be derived rather than declared."""

    def products_read(self) -> frozenset[str]: ...


@dataclass(frozen=True, slots=True)
class Concept:
    """A design-level recipe: the family it computes, the revision of the recipe, and the
    shape of what it stores.

    ``depends_on`` is *derived* from the recipe's term when it has one — the families the term
    reads — and a declaration that disagrees is an error. A concept adopted without a term
    (its recipe still lives in interpreter code) declares its dependencies, so the layer check
    applies to it too. ``revision`` is the store's key for the recipe, verbatim: the same
    string an :class:`Instance` records as ``computed_by``.
    """

    family: str
    revision: str
    layer: Layer
    fields: tuple[tuple[str, Field], ...] = ()
    term: TermLike | None = None
    lifecycle: LifecycleStatus = LifecycleStatus.OFFICIAL
    depends_on: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if isinstance(self.fields, Mapping):
            object.__setattr__(self, 'fields', tuple(sorted(self.fields.items())))
        declared = frozenset(self.depends_on)
        if self.term is not None:
            derived = frozenset(self.term.products_read())
            if declared and declared != derived:
                raise ValueError(f'{self.family!r} declares dependencies {sorted(declared)} but its term reads {sorted(derived)}')
            declared = derived
        object.__setattr__(self, 'depends_on', declared)

    def field(self, name: str) -> Field:
        for field_name, spec in self.fields:
            if field_name == name:
                return spec
        raise KeyError(f'{self.family!r} declares no field {name!r}')


def servable(concept: Concept) -> Refuse | None:
    """Only ``VIEW``-layer products cross the serving boundary; everything else supports them."""
    if concept.layer.is_served:
        return None
    return Refuse(RefuseReason.NOT_SERVABLE,
                  f'{concept.family!r} is a {concept.layer.label}-layer product; only views are served',
                  {'concept': concept.family, 'layer': concept.layer})


# ---------------------------------------------------------------------------
# Instance and Ask
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LineageRef:
    """One thing an instance read, with the facts the lineage gate needs about it now.

    The interpreter fetches these when it fetches the instance: the referenced node's
    current lifecycle, whether it is itself flagged, and when it last changed. The gate then
    decides from facts, not from a bit the interpreter decided for it.
    """

    key: str
    lifecycle: LifecycleStatus = LifecycleStatus.OFFICIAL
    needs_redo: bool = False
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Instance:
    """One computed answer at an :class:`Identity`, with what the three gates need to judge it.

    ``computed_at`` may be unknown for nodes written before it was recorded; the freshness
    gate treats unknown as stale when a bound is set. ``computed_by`` is the store's own key
    for the recipe revision (a :class:`Concept`'s ``revision``); ``producing`` is that recipe's
    current lifecycle, and defaults to ``None`` — an instance whose recipe nobody looked up is
    recomputed, not silently served as if its recipe were official.
    """

    identity: Identity
    payload: Mapping[str, Any]
    computed_at: datetime | None = None
    computed_by: str | None = None
    producing: LifecycleStatus | None = None
    lifecycle: LifecycleStatus = LifecycleStatus.OFFICIAL
    needs_redo: bool = False
    lineage: tuple[LineageRef, ...] = ()


@dataclass(frozen=True, slots=True)
class Ask:
    """The canonical request. Policy slots, no override.

    ``subject_key=None`` asks for every subject of ``subject_kind`` in scope — "per floor" —
    and leaves enumeration to the resolver. ``max_staleness`` and ``maturity_lag`` are slots:
    ``None`` leaves that gate unapplied, and the interpreter — not the algebra — owns any
    default worth having.
    """

    product: str
    scope_name: str
    subject_kind: str
    subject_key: str | None
    temporal_granularity: str
    local_period_start: datetime | str | None = None
    local_period_end: datetime | str | None = None
    classifications: Classifications = ()
    max_staleness: timedelta | None = None
    maturity_lag: timedelta | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, 'classifications', freeze_classifications(self.classifications))
