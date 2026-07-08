"""Analytical product graph node ensure-on-read engine."""


from __future__ import annotations

from typing import LiteralString

from agent_neo.analytical_product.abstract import AbstractComputedGraphNode, AbstractDesignNode, ComputedNodeResult
from agent_neo.analytical_product.enum import ComputedNodeLayer, GraphEdgeKind, NodeLifecycleStatus
from agent_neo.analytical_product.identity import ComputedSlotIdentity, build_slot_key
from agent_neo.analytical_product.registry import (
    register_computed_node_class,
    register_design_node_class,
    register_relationship_target_class,
)
from agent_neo.analytical_product.request import ComputeRequest


__all__: tuple[LiteralString, ...] = (
    "AbstractComputedGraphNode",
    "AbstractDesignNode",
    "ComputeRequest",
    "ComputedNodeLayer",
    "ComputedNodeResult",
    "ComputedSlotIdentity",
    "GraphEdgeKind",
    "NodeLifecycleStatus",
    "build_slot_key",
    "register_computed_node_class",
    "register_design_node_class",
    "register_relationship_target_class",
)
