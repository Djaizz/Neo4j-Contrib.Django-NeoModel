"""The seam between stored products and the algebra — in both directions.

An :class:`~agent_neo.a3.product.Ask` resolves to the identities it *should* produce
(:class:`Resolver` — the interpreter's job; it needs a calendar and, for a per-kind ask, the
subjects in scope) and a :class:`Store` says which of them exist and hands back their
instances. :func:`carrier_from_instances` turns that into a carrier whose expected set is the
resolved identities, whose cells are the instances found, and whose tag is decided by the
concept's :class:`~agent_neo.a3.product.Field` declaration for the field read:

- ``LEAF`` — plain values, ready to be lifted into any operator;
- ``ACCUMULATOR`` — the operator's storage columns, decoded back into accumulators through
  the operator's own ``decode``, so a stored ``(average, count)`` re-enters as a mean and
  rolls further;
- ``REPORTED`` — values already lowered, remembered as such, so a stored mean cannot be
  averaged again.

:func:`instances_from_carrier` is the reverse: it refuses a carrier whose tag does not match
the field's declared role, writes accumulators into their declared columns, canonicalizes
coordinates under the interpreter's :class:`~agent_neo.a3.product.KeyScheme`, and records
the stored leaves behind each cell as lineage — whatever families they came from.
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
    Refuse,
    RefuseReason,
)

__all__ = (
    'Resolver',
    'Store',
    'carrier_from_instances',
    'columns_of',
    'instances_from_carrier',
    'lowered_name',
)


class Resolver(Protocol):
    """An ask → the identities it should produce. The interpreter owns the calendar and the
    subject enumeration; it also clamps windows for maturity here, so ``gate`` sees only
    settled periods on that path."""

    def resolve(self, ask: Ask) -> tuple[Identity, ...]: ...


class Store(Protocol):
    def present(self, identities: Iterable[Identity]) -> frozenset[Identity]: ...

    def fetch(self, identities: Iterable[Identity]) -> tuple[Instance, ...]: ...


def _operator(spec: Field, operators: OperatorRegistry | None, field: str) -> Any:
    if operators is None or spec.operator not in operators:
        raise ValueError(f'field {field!r} is declared {spec.role.value} of {spec.operator!r}; a registry that knows it is required')
    return operators.get(spec.operator)


def lowered_name(spec: Field, operators: OperatorRegistry | None, field: str = '') -> str:
    """The name ``lower`` records for this field's operator: its class name. One convention,
    shared by the bridge and the shape checker, so a stored report and a freshly lowered one
    compare equal."""
    return type(_operator(spec, operators, field)).__name__


def columns_of(spec: Field, field: str, operator: Any) -> tuple[str, ...]:
    """The payload names an ACCUMULATOR field's columns live under."""
    columns = spec.columns or (field,)
    if len(columns) != len(operator.columns):
        raise ValueError(f'field {field!r} holds {type(operator).__name__} accumulators, which store as {operator.columns}; '
                         f'{len(columns)} column name(s) declared')
    return columns


def carrier_from_instances(
    expected: Iterable[Identity],
    instances: Iterable[Instance],
    *,
    field: str,
    spec: Field,
    operators: OperatorRegistry | None = None,
    scheme: KeyScheme = PLAIN_KEY_SCHEME,
) -> Carrier[Any]:
    """Cells from the instances found, expected set from the ask, tag from the field's role,
    family from the identities.

    Coordinates on both sides are canonicalized under ``scheme`` first, so an instance a store
    wrote with explicit neutral classifications meets the ask that omitted them: one identity,
    one cell. A payload holding ``None`` for the field — or for any of an accumulator's
    columns — is a cell that is *absent* (and so missing), not a zero. An instance outside the
    expected set, or two at one coordinate, is a broken store and raises.
    """
    expected = tuple(expected)
    families = {identity.product for identity in expected}
    if len(families) > 1:
        raise ValueError(f'one carrier holds one family; the expected set names {sorted(families)}')
    family = next(iter(families), None)
    expected_coords = frozenset(scheme.canonical(identity.coordinate) for identity in expected)
    operator = _operator(spec, operators, field) if spec.role is not FieldRole.LEAF else None
    columns = columns_of(spec, field, operator) if spec.role is FieldRole.ACCUMULATOR else (field,)

    cells: dict[Coordinate, Any] = {}
    for instance in instances:
        coordinate = scheme.canonical(instance.identity.coordinate)
        if coordinate not in expected_coords:
            raise ValueError(f'instance {instance.identity.cache_key(scheme)!r} is outside the expected set of the ask')
        if coordinate in cells:
            raise ValueError(f'two instances for one coordinate {coordinate!r}; the store has lost at-most-one-current')
        values = tuple(instance.payload.get(column) for column in columns)
        if any(value is None for value in values):
            continue
        cells[coordinate] = operator.decode(*values) if spec.role is FieldRole.ACCUMULATOR else values[0]
    if spec.role is FieldRole.ACCUMULATOR:
        return Carrier(cells, expected_coords, operator, family=family)
    if spec.role is FieldRole.REPORTED:
        return Carrier(cells, expected_coords, None, (type(operator).__name__,), family=family)
    return Carrier(cells, expected_coords, family=family)


def instances_from_carrier(
    carrier: Carrier[Any],
    *,
    product: str,
    computed_at: datetime,
    computed_by: str,
    field: str,
    spec: Field,
    operators: OperatorRegistry | None = None,
    scheme: KeyScheme = PLAIN_KEY_SCHEME,
    lifecycle: LifecycleStatus = LifecycleStatus.OFFICIAL,
    producing: LifecycleStatus | None = LifecycleStatus.OFFICIAL,
) -> tuple[Instance, ...] | Refuse:
    """One instance per present cell, at the canonical coordinate, in the field's declared
    shape. Lineage = the keys of the stored leaves behind the cell (:meth:`Carrier.sources`).

    The carrier's tag must be what the field declares — accumulators of the field's operator
    into an ``ACCUMULATOR`` field, its reports into a ``REPORTED`` field, plain values into a
    ``LEAF`` — or the write is refused: the declaration is what the algebra consults when the
    product is read back, and the two may not disagree.
    """
    if carrier.operator is not None:
        if spec.role is not FieldRole.ACCUMULATOR or _operator(spec, operators, field) != carrier.operator:
            return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION,
                          f'{type(carrier.operator).__name__} accumulators cannot be stored in {field!r}, declared {spec.role.value}'
                          f'{" of " + spec.operator if spec.operator else ""}', {'field': field, 'operator': carrier.operator})
        columns = columns_of(spec, field, carrier.operator)
        payload_of = lambda value: dict(zip(columns, carrier.operator.encode(value)))
    elif carrier.lowered_from:
        if spec.role is not FieldRole.REPORTED or lowered_name(spec, operators, field) != carrier.lowered_from[-1]:
            return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION,
                          f'reported {carrier.lowered_from[-1]} values cannot be stored in {field!r}, declared {spec.role.value}'
                          f'{" of " + spec.operator if spec.operator else ""}', {'field': field, 'lowered_from': carrier.lowered_from})
        payload_of = lambda value: {field: value}
    else:
        if spec.role is not FieldRole.LEAF:
            return Refuse(RefuseReason.UNSUPPORTED_COMPOSITION,
                          f'plain values cannot be stored in {field!r}, declared {spec.role.value} of {spec.operator!r}', {'field': field})
        payload_of = lambda value: {field: value}
    return tuple(
        Instance(
            identity=Identity(product, scheme.canonical(coordinate)),
            payload=payload_of(value),
            computed_at=computed_at,
            computed_by=computed_by,
            producing=producing,
            lifecycle=lifecycle,
            lineage=tuple(LineageRef(leaf.cache_key(scheme)) for leaf in sorted(carrier.sources(coordinate), key=repr)),
        )
        for coordinate, value in carrier.cells.items()
    )
