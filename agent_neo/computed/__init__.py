"""Computed graph node ensure-on-read engine."""


from __future__ import annotations

from typing import LiteralString

from agent_neo.computed.abstract import AbstractComputedGraphNode, AbstractDesignNode, ComputedNodeResult
from agent_neo.computed.enum import ComputedNodeLayer, GraphEdgeKind, NodeLifecycleStatus
from agent_neo.computed.identity import ComputedSlotIdentity, build_slot_key
from agent_neo.computed.registry import (
    register_computed_node_class,
    register_design_node_class,
    register_relationship_target_class,
)
from agent_neo.computed.request import ComputeRequest


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
