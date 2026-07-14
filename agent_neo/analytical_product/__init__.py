"""Analytical product graph node ensure-on-read engine."""


from __future__ import annotations

from typing import LiteralString

from agent_neo.analytical_product.abstract import AbstractAnalyticalComputedProduct, AbstractAnalyticalConcept, ComputedNodeResult
from agent_neo.analytical_product.enum import ComputedNodeLayer, GraphEdgeKind, NodeLifecycleStatus
from agent_neo.analytical_product.identity import AnalyticalProductIdentity, build_cache_key
from agent_neo.analytical_product.registry import (
    register_analytical_product_class,
    register_analytical_concept_class,
    register_relationship_target_class,
)
from agent_neo.analytical_product.request import AnalyticalProductRequest


__all__: tuple[LiteralString, ...] = (
    "AbstractAnalyticalComputedProduct",
    "AbstractAnalyticalConcept",
    "AnalyticalProductRequest",
    "ComputedNodeLayer",
    "ComputedNodeResult",
    "AnalyticalProductIdentity",
    "GraphEdgeKind",
    "NodeLifecycleStatus",
    "build_cache_key",
    "register_analytical_product_class",
    "register_analytical_concept_class",
    "register_relationship_target_class",
)
