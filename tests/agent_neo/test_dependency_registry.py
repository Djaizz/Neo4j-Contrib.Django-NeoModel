"""Tests for computed dependency registry validation."""

from __future__ import annotations

from neomodel import RelationshipTo, StringProperty

from agent_neo.analytical_product.dependency_registry import (
    DependencySlot,
    validate_computed_node_dependency_registry,
)
from agent_neo.analytical_product.enum import GraphEdgeKind
from agent_neo.models.base import DjangoNeoModelWithCreatedAndUpdatedProps


class _UpstreamNode(DjangoNeoModelWithCreatedAndUpdatedProps):
    name = StringProperty(required=True)


class _ComputedNode(DjangoNeoModelWithCreatedAndUpdatedProps):
    DEPENDS_ON_RELS = (
        DependencySlot(target_class=_UpstreamNode, manager_name="depends_on_upstream"),
    )
    depends_on_upstream = RelationshipTo(_UpstreamNode.__name__, GraphEdgeKind.DEPENDS_ON.value)


class _BrokenComputedNode(DjangoNeoModelWithCreatedAndUpdatedProps):
    DEPENDS_ON_RELS = (
        DependencySlot(target_class=_UpstreamNode, manager_name="missing_manager"),
    )


def test_validate_computed_node_dependency_registry_accepts_declared_slot() -> None:
    errors = validate_computed_node_dependency_registry(_ComputedNode)
    assert errors == []


def test_validate_computed_node_dependency_registry_flags_missing_manager() -> None:
    errors = validate_computed_node_dependency_registry(_BrokenComputedNode)
    assert any("missing_manager" in error for error in errors)
