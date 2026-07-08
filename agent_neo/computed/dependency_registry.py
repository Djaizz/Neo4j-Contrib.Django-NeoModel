"""Declarative dependency registries for computed graph node classes."""


from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, ClassVar, Iterable, LiteralString

from neomodel.sync_.relationship_manager import RelationshipDefinition

from agent_neo.computed.registry import (
    _EXTRA_RELATIONSHIP_TARGET_RESOLVERS,
    iter_registered_computed_node_classes,
    iter_registered_design_node_classes,
)

from .enum import GraphEdgeKind


__all__: tuple[LiteralString, ...] = (
    'DependencySlot',
    'collect_dependency_targets',
    'dependency_manager_names',
    'get_computes_design_class',
    'get_design_depends_on_design_slots',
    'get_computed_node_depends_on_slots',
    'infer_depends_on_slots_from_managers',
    'iter_dependency_managers',
    'validate_all_dependency_registries',
    'validate_design_dependency_registry',
    'validate_computed_node_dependency_registry',
)


log = logging.getLogger(__name__)

_VALIDATED: bool = False


@dataclass(frozen=True, slots=True)
class DependencySlot:
    """One upstream dependency edge declared on a computed node or design-node class."""

    target_class: type
    manager_name: str
    rel_type: GraphEdgeKind = GraphEdgeKind.DEPENDS_ON


def get_computed_node_depends_on_slots(product_cls: type) -> tuple[DependencySlot, ...]:
    """Return the ``DEPENDS_ON_RELS`` registry for a computed graph node class."""
    cached_slots = getattr(product_cls, '_DEPENDS_ON_RELS_CACHE', None)
    if cached_slots is not None:
        return cached_slots
    declared_registry = getattr(product_cls, 'DEPENDS_ON_RELS', None)
    if declared_registry:
        cached_slots = tuple(declared_registry)
        product_cls._DEPENDS_ON_RELS_CACHE = cached_slots
        return cached_slots
    inferred_slots = infer_depends_on_slots_from_managers(product_cls)
    product_cls._DEPENDS_ON_RELS_CACHE = inferred_slots
    if inferred_slots:
        product_cls.DEPENDS_ON_RELS = inferred_slots
    return inferred_slots


def get_computes_design_class(product_cls: type) -> type:
    """Return the design-node class wired by the product's ``computes_design`` relationship."""
    cached_design_node_class = getattr(product_cls, '_COMPUTES_DESIGN_CLS_CACHE', None)
    if cached_design_node_class is not None:
        return cached_design_node_class
    computes_design_rel_name = getattr(product_cls, 'COMPUTES_DESIGN_REL', 'computes_design')
    relationship_manager = getattr(product_cls, computes_design_rel_name, None)
    if relationship_manager is None or not isinstance(relationship_manager, RelationshipDefinition):
        raise TypeError(
            f'{product_cls.__name__} has no {computes_design_rel_name!r} NeoModel RelationshipTo manager',
        )
    concept_class = _resolve_relationship_target_class(
        relationship_manager,
        owning_class=product_cls,
    )
    product_cls._COMPUTES_DESIGN_CLS_CACHE = concept_class
    return concept_class


def get_design_depends_on_design_slots(concept_cls: type) -> tuple[DependencySlot, ...]:
    """Return the ``DEPENDS_ON_DESIGN_RELS`` registry for a design-node class."""
    registry = getattr(concept_cls, 'DEPENDS_ON_DESIGN_RELS', None)
    if registry is None:
        return ()
    return tuple(registry)


def dependency_manager_names(slots: Iterable[DependencySlot]) -> tuple[str, ...]:
    """NeoModel manager attribute names for the given dependency slots."""
    return tuple(slot.manager_name for slot in slots)


def iter_dependency_managers(instance: Any, slots: Iterable[DependencySlot]) -> Iterable[Any]:
    """Yield NeoModel relationship managers for each declared dependency slot."""
    for slot in slots:
        manager = getattr(instance, slot.manager_name, None)
        if manager is not None:
            yield manager


def collect_dependency_targets(
    compute_result: Any,
    slots: Iterable[DependencySlot],
) -> dict[str, list[Any]]:
    """Build manager-name -> target-node lists from a compute result and slot registry."""
    dependency_targets = getattr(compute_result, 'dependency_targets', None) or {}
    collected: dict[str, list[Any]] = {}
    for slot in slots:
        targets = dependency_targets.get(slot.manager_name)
        if targets is None:
            targets = []
        collected[slot.manager_name] = list(targets)
    return collected


def _resolve_relationship_target_class(
    manager: RelationshipDefinition,
    *,
    owning_class: type,
) -> type:
    """Resolve the Python class for a NeoModel ``RelationshipTo`` manager."""
    target_class_name = _relationship_target_class_name(manager)
    if target_class_name is None:
        raise ValueError('Could not resolve RelationshipTo target class')
    if target_class_name == owning_class.__name__:
        return owning_class
    if target_class_name in _EXTRA_RELATIONSHIP_TARGET_RESOLVERS:
        return _EXTRA_RELATIONSHIP_TARGET_RESOLVERS[target_class_name]
    lookup_node_class = getattr(manager, 'lookup_node_class', None)
    if callable(lookup_node_class):
        try:
            resolved_class = lookup_node_class()
        except (AttributeError, KeyError):
            resolved_class = None
        if resolved_class is not None:
            return resolved_class
    for candidate_class in (*iter_registered_computed_node_classes(), *iter_registered_design_node_classes()):
        if candidate_class.__name__ == target_class_name:
            return candidate_class
    raise ValueError(f'Unknown RelationshipTo target class {target_class_name!r}')


def infer_depends_on_slots_from_managers(product_cls: type) -> tuple[DependencySlot, ...]:
    """Build ``DEPENDS_ON_RELS`` slots from declared ``DEPENDS_ON``-typed ``RelationshipTo`` managers."""
    inferred_slots: list[DependencySlot] = []
    for attribute_name, attribute_value in vars(product_cls).items():
        if not isinstance(attribute_value, RelationshipDefinition):
            continue
        if _relationship_rel_type_value(attribute_value) != GraphEdgeKind.DEPENDS_ON.value:
            continue
        inferred_slots.append(
            DependencySlot(
                target_class=_resolve_relationship_target_class(
                    attribute_value,
                    owning_class=product_cls,
                ),
                manager_name=attribute_name,
            ),
        )
    return tuple(sorted(inferred_slots, key=lambda slot: slot.manager_name))


def _relationship_target_class_name(manager: RelationshipDefinition) -> str | None:
    """Resolve the declared target class name on a NeoModel RelationshipTo manager."""
    raw_class = getattr(manager, '_raw_class', None)
    if isinstance(raw_class, str):
        return raw_class
    if raw_class is not None:
        return getattr(raw_class, '__name__', None)
    lookup = getattr(manager, 'lookup_node_class', None)
    if callable(lookup):
        resolved_class = lookup()
        if resolved_class is not None:
            return getattr(resolved_class, '__name__', None)
    return None


def _relationship_rel_type_value(manager: RelationshipDefinition) -> str | None:
    relation_type = getattr(manager, 'definition', {}).get('relation_type')
    if relation_type is None:
        return None
    return getattr(relation_type, 'value', relation_type)


def validate_computed_node_dependency_registry(product_cls: type) -> list[str]:
    """Validate ``DEPENDS_ON_RELS`` against declared NeoModel ``RelationshipTo`` managers."""
    errors: list[str] = []
    class_name = getattr(product_cls, '__name__', repr(product_cls))
    explicit_registry = product_cls.__dict__.get('DEPENDS_ON_RELS')
    declared_slots = (
        tuple(explicit_registry)
        if explicit_registry is not None and 'DEPENDS_ON_RELS' in product_cls.__dict__
        else get_computed_node_depends_on_slots(product_cls)
    )
    declared_manager_names = {slot.manager_name for slot in declared_slots}

    for slot in declared_slots:
        manager = getattr(product_cls, slot.manager_name, None)
        if manager is None:
            errors.append(f'{class_name}: DEPENDS_ON_RELS slot {slot.manager_name!r} has no manager on class')
            continue
        if not isinstance(manager, RelationshipDefinition):
            errors.append(
                f'{class_name}: attribute {slot.manager_name!r} is not a NeoModel RelationshipTo manager',
            )
            continue
        expected_target_name = slot.target_class.__name__
        actual_target_name = _relationship_target_class_name(manager)
        if actual_target_name is not None and actual_target_name != expected_target_name:
            errors.append(
                f'{class_name}: {slot.manager_name!r} targets {actual_target_name!r}, '
                f'expected {expected_target_name!r}',
            )
        actual_rel_type = _relationship_rel_type_value(manager)
        if actual_rel_type is not None and actual_rel_type != slot.rel_type.value:
            errors.append(
                f'{class_name}: {slot.manager_name!r} rel_type {actual_rel_type!r} != {slot.rel_type.value!r}',
            )

    for attribute_name, attribute_value in vars(product_cls).items():
        if not isinstance(attribute_value, RelationshipDefinition):
            continue
        if _relationship_rel_type_value(attribute_value) != GraphEdgeKind.DEPENDS_ON.value:
            continue
        if explicit_registry is not None and 'DEPENDS_ON_RELS' in product_cls.__dict__:
            if attribute_name not in declared_manager_names:
                errors.append(
                    f'{class_name}: RelationshipTo manager {attribute_name!r} is not listed in DEPENDS_ON_RELS',
                )

    return errors


def validate_design_dependency_registry(concept_cls: type) -> list[str]:
    """Validate ``DEPENDS_ON_DESIGN_RELS`` against design-node ``RelationshipTo`` managers."""
    errors: list[str] = []
    class_name = getattr(concept_cls, '__name__', repr(concept_cls))
    declared_slots = get_design_depends_on_design_slots(concept_cls)
    declared_manager_names = {slot.manager_name for slot in declared_slots}

    for slot in declared_slots:
        if slot.rel_type != GraphEdgeKind.DEPENDS_ON_DESIGN:
            errors.append(
                f'{class_name}: concept slot {slot.manager_name!r} must use DEPENDS_ON_CONCEPT rel_type',
            )
        manager = getattr(concept_cls, slot.manager_name, None)
        if manager is None:
            errors.append(f'{class_name}: DEPENDS_ON_DESIGN_RELS slot {slot.manager_name!r} has no manager')
            continue
        if not isinstance(manager, RelationshipDefinition):
            errors.append(
                f'{class_name}: attribute {slot.manager_name!r} is not a NeoModel RelationshipTo manager',
            )
            continue
        expected_target_name = slot.target_class.__name__
        actual_target_name = _relationship_target_class_name(manager)
        if actual_target_name is not None and actual_target_name != expected_target_name:
            errors.append(
                f'{class_name}: {slot.manager_name!r} targets {actual_target_name!r}, '
                f'expected {expected_target_name!r}',
            )

    for attribute_name, attribute_value in vars(concept_cls).items():
        if not isinstance(attribute_value, RelationshipDefinition):
            continue
        if _relationship_rel_type_value(attribute_value) != GraphEdgeKind.DEPENDS_ON_DESIGN.value:
            continue
        if attribute_name not in declared_manager_names:
            errors.append(
                f'{class_name}: RelationshipTo manager {attribute_name!r} is not listed in DEPENDS_ON_DESIGN_RELS',
            )

    return errors


def validate_all_dependency_registries(*, strict: bool = True) -> list[str]:
    """Validate dependency registries for all registered computed and design-node classes."""
    errors: list[str] = []
    for product_cls in iter_registered_computed_node_classes():
        get_computed_node_depends_on_slots(product_cls)
        errors.extend(validate_computed_node_dependency_registry(product_cls))
    for concept_cls in iter_registered_design_node_classes():
        errors.extend(validate_design_dependency_registry(concept_cls))

    global _VALIDATED
    _VALIDATED = True
    if errors:
        message = 'Computed node dependency registry validation failed:\n' + '\n'.join(f'  - {error}' for error in errors)
        if strict:
            raise RuntimeError(message)
        log.warning(message)
    return errors


def register_dependency_registry_validation(*, strict: bool = True) -> None:
    """Run registry validation once during Django app startup."""
    global _VALIDATED
    if _VALIDATED:
        return
    validate_all_dependency_registries(strict=strict)
