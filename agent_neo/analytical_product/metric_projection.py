"""Projection helpers for serving computed-product rows across the View boundary.

These are generic graph-node mechanisms: project a persisted instance to a payload
dict, serve multi-row collections, and ensure concept anchors. The functions operate
on any ``AbstractAnalyticalComputedProduct`` subclass — they carry no domain logic.
"""


from __future__ import annotations

from typing import Any, Callable, LiteralString

from agent_neo.analytical_product.abstract import (
    AbstractAnalyticalComputedProduct,
    AbstractAnalyticalConcept,
    ComputedNodeResult,
)
from agent_neo.analytical_product.enum import NodeLifecycleStatus
from agent_neo.analytical_product.request import AnalyticalProductRequest
from agent_neo.analytical_product.scope import AnalyticalProductScope
from agent_neo.util.json_safe import json_safe_structure


__all__: tuple[LiteralString, ...] = (
    'AnalyticalProductScope',
    'identity_from_view_identity',
    'project_instance_to_payload',
    'serve_multi_row_projection',
    'ensure_official_concept',
    'serve_projected_payload_rows',
)


def identity_from_view_identity(
    view_identity: Any,
    *,
    product_class_name: str,
    identity_class: type[Any],
) -> Any:
    """Map a View-layer identity to the backing product-layer identity coordinates."""
    return identity_class(
        analytical_product_class_name=product_class_name,
        scope_name=view_identity.scope_name,
        subject_kind=view_identity.subject_kind,
        subject_key=view_identity.subject_key,
        temporal_granularity=view_identity.temporal_granularity,
        local_period_start=view_identity.local_period_start,
        local_period_end=view_identity.local_period_end,
        day_classif=view_identity.day_classif,
        hour_classif=view_identity.hour_classif,
    )


def project_instance_to_payload(
    product_class: type[Any],
    compute_scope: AnalyticalProductScope,
    instance: Any,
) -> dict[str, Any]:
    """Project one product node using the family's payload helper."""
    payload_builder = getattr(product_class, '_to_payload', None)
    if callable(payload_builder):
        return payload_builder(instance, compute_scope.tz)
    return product_class.to_payload(instance)


def serve_multi_row_projection(
    product_class: type[AbstractAnalyticalComputedProduct],
    compute_scope: AnalyticalProductScope,
    request: AnalyticalProductRequest,
    *,
    serialize: Callable[[Any], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Serve a multi-row product collection through a View boundary without 1:1 view persistence."""
    instances = product_class.get(compute_scope, request)
    return [serialize(instance) for instance in instances]


def ensure_official_concept(
    concept_class: type[AbstractAnalyticalConcept],
    *,
    concept_key: str,
    analytical_product_class_name: str,
    metric_set_class_name: str,
) -> AbstractAnalyticalConcept:
    """Get or create an OFFICIAL concept anchor for a projection ViewSet."""
    concept = concept_class.nodes.get_or_none(concept_key=concept_key)
    if concept is None:
        concept = concept_class(
            **concept_class.official_concept_defaults(
                concept_key=concept_key,
                analytical_product_class_name=analytical_product_class_name,
                metric_set_class_name=metric_set_class_name,
            ),
        ).save()
    elif concept.lifecycle_status != NodeLifecycleStatus.OFFICIAL.value:
        concept.lifecycle_status = NodeLifecycleStatus.OFFICIAL.value
        concept.save()
    return concept


def serve_projected_payload_rows(
    view_set_class: type[AbstractAnalyticalComputedProduct],
    compute_scope: AnalyticalProductScope,
    request: AnalyticalProductRequest,
) -> list[dict[str, Any]]:
    """Serve persisted ``projected_payload_json`` from ViewSet instances."""
    view_instances = view_set_class.get(compute_scope, request)
    payloads: list[dict[str, Any]] = []
    for view_instance in view_instances:
        projected_payload = getattr(view_instance, 'projected_payload_json', None)
        if projected_payload:
            payloads.append(json_safe_structure(projected_payload))
    return payloads
