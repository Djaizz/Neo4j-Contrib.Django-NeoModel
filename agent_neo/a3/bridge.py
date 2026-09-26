"""The seam between stored products and the algebra — in both directions.

An :class:`~agent_neo.a3.product.Ask` resolves to the identities it *should* produce
(:class:`Resolver` — the interpreter's job; it needs a calendar and, for a per-kind ask, the
subjects in scope). What the :class:`Store` holds is a subset. The difference is the
coverage: the denominator is the ask, never the data.

What a payload field *is* decides how it enters the algebra. The concept says
(:class:`~agent_neo.a3.product.Field`): a leaf observation becomes a leaf carrier that may be
lifted into any operator; a stored accumulator becomes a carrier already tagged with its
operator, ready to roll further; a stored reported value becomes a carrier that remembers it
was lowered, so ``lift`` refuses it. A stored mean can be read and compared; it can never be
averaged again.

Going back, ``instances_from_carrier`` turns a carrier into the instances an interpreter
persists, each carrying as lineage the keys of the leaves it came from.
"""


from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Protocol

from agent_neo.a3.algebra import Carrier
from agent_neo.a3.carrier import Coordinate
from agent_neo.a3.operators import OperatorRegistry
from agent_neo.a3.product import (
    PLAIN_KEY_SCHEME,
    Ask,
    Field,
    FieldRole,
    Identity,
    Instance,
    KeyScheme,
    LifecycleStatus,
    LineageRef,
)

__all__ = (
    'Resolver',
    'Store',
    'carrier_from_instances',
    'instances_from_carrier',
    'lowered_name',
)


class Resolver(Protocol):
    """Ask → the identities it should produce: window enumeration, subject enumeration, maturity clamping."""

    def resolve(self, ask: Ask) -> tuple[Identity, ...]: ...


class Store(Protocol):
    """The current instances at identities. ``present`` answers without payloads; ``fetch`` returns them."""

    def present(self, identities: Iterable[Identity]) -> frozenset[Identity]: ...

    def fetch(self, identities: Iterable[Identity]) -> tuple[Instance, ...]: ...


def lowered_name(spec: Field, operators: OperatorRegistry | None) -> str:
    """The name ``lower`` would have recorded for this field's operator: its class name when the
    registry can resolve it, else the registry name as declared. Shared by the bridge and the shape
    checker so the two never disagree about what a stored report was lowered from."""
    if operators is not None and spec.operator in operators:
        return type(operators.get(spec.operator)).__name__
    return spec.operator or ''


def carrier_from_instances(
    expected: Iterable[Identity],
    instances: Iterable[Instance],
    *,
    field: str,
    spec: Field,
    operators: OperatorRegistry | None = None,
) -> Carrier[Any]:
    """Cells from the instances found, expected set from the ask, tag from the field's role.

    A payload holding ``None`` for the field is a cell that is *absent* (and so missing), not
    a zero. An instance outside the expected set, or two at one coordinate, is a broken store
    and raises.
    """
    expected_coords = frozenset(identity.coordinate for identity in expected)
    cells: dict[Coordinate, Any] = {}
    for instance in instances:
        coordinate = instance.identity.coordinate
        if coordinate not in expected_coords:
            raise ValueError(f'instance {instance.identity.cache_key()!r} is outside the expected set of the ask')
        if coordinate in cells:
            raise ValueError(f'two instances for one coordinate {coordinate!r}; the store has lost at-most-one-current')
        value = instance.payload.get(field)
        if value is not None:
            cells[coordinate] = value
    if spec.role is FieldRole.ACCUMULATOR:
        if operators is None:
            raise ValueError(f'field {field!r} holds {spec.operator!r} accumulators; an operator registry is required to tag them')
        return Carrier(cells, expected_coords, operators.get(spec.operator))
    if spec.role is FieldRole.REPORTED:
        return Carrier(cells, expected_coords, None, (lowered_name(spec, operators),))
    return Carrier(cells, expected_coords)


def instances_from_carrier(
    carrier: Carrier[Any],
    *,
    product: str,
    computed_at: datetime,
    computed_by: str,
    field: str,
    source_product: str | None = None,
    scheme: KeyScheme = PLAIN_KEY_SCHEME,
    lifecycle: LifecycleStatus = LifecycleStatus.OFFICIAL,
) -> tuple[Instance, ...]:
    """One instance per present cell. Lineage = keys of the leaf identities behind the cell,
    under ``source_product`` (the family the leaves belong to; defaults to ``product``).

    Persist a *tagged* carrier and the field is an ACCUMULATOR the concept should declare as
    such; persist a lowered one and it is REPORTED. The concept's declaration, not this call,
    is what the algebra consults later — keep them in agreement."""
    leaf_family = source_product or product
    return tuple(
        Instance(
            identity=Identity(product, coordinate),
            payload={field: value},
            computed_at=computed_at,
            computed_by=computed_by,
            lifecycle=lifecycle,
            lineage=tuple(LineageRef(Identity(leaf_family, leaf).cache_key(scheme)) for leaf in sorted(carrier.sources(coordinate), key=repr)),
        )
        for coordinate, value in carrier.cells.items()
    )
