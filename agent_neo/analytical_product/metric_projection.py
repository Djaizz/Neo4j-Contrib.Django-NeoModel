"""L4 ViewSet helpers that project persisted MetricSet rows across the serving boundary."""


from __future__ import annotations

from typing import Any, Callable, LiteralString, Protocol, runtime_checkable

from agent_neo.analytical_product.abstract import (
    AbstractAnalyticalComputedProduct,
    AbstractAnalyticalConcept,
    ComputedNodeResult,
)
from agent_neo.analytical_product.enum import NodeLifecycleStatus
from agent_neo.analytical_product.request import AnalyticalProductRequest
from agent_neo.util.json_safe import json_safe_structure


__all__: tuple[LiteralString, ...] = (
    'ComputeScope',
    'metric_identity_from_view_identity',
    'project_metric_instance_to_payload',
    'serve_multi_row_metric_projection',
)


@runtime_checkable
class ComputeScope(Protocol):
    """Minimal scope surface for metric projection (facility timezone, etc.)."""

    @property
    def tz(self) -> Any: ...


def metric_identity_from_view_identity(
    view_identity: Any,
    *,
    metric_set_class_name: str,
    identity_class: type[Any],
) -> Any:
    """Map a View identity slot to the backing MetricSet identity coordinates."""
    return identity_class(
        analytical_product_class_name=metric_set_class_name,
        facility_name=view_identity.facility_name,
        subject_kind=view_identity.subject_kind,
        subject_key=view_identity.subject_key,
        temporal_granularity=view_identity.temporal_granularity,
        local_period_start=view_identity.local_period_start,
        local_period_end=view_identity.local_period_end,
        day_classif=view_identity.day_classif,
        hour_classif=view_identity.hour_classif,
    )


def project_metric_instance_to_payload(
    metric_set_class: type[Any],
    compute_scope: ComputeScope,
    metric_instance: Any,
) -> dict[str, Any]:
    """Project one MetricSet node using the family's payload helper."""
    payload_builder = getattr(metric_set_class, '_to_payload', None)
    if callable(payload_builder):
        return payload_builder(metric_instance, compute_scope.tz)
    return metric_set_class.to_payload(metric_instance)


def serve_multi_row_metric_projection(
    metric_set_class: type[AbstractAnalyticalComputedProduct],
    compute_scope: ComputeScope,
    request: AnalyticalProductRequest,
    *,
    serialize: Callable[[Any], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Serve a multi-row MetricSet through a View boundary without 1:1 view persistence."""
    metric_instances = metric_set_class.get(compute_scope, request)
    return [serialize(metric_instance) for metric_instance in metric_instances]


def ensure_official_concept(
    concept_class: type[AbstractAnalyticalConcept],
    *,
    concept_key: str,
    analytical_product_class_name: str,
    metric_set_class_name: str,
) -> AbstractAnalyticalConcept:
    """Get or create an OFFICIAL concept anchor for a metric projection ViewSet."""
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
    compute_scope: ComputeScope,
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
