"""Bulk graph persistence for computed graph nodes.

Rationale: populate-scale and multi-window ``.get`` cannot N+1 NeoModel ``save``/``connect``.
``persist_many`` does set-oriented upsert, lineage replace, retire-prior, and **owns audit
timestamps + cascade-mark parity** because raw Cypher bypasses ``save()`` and Django signals.
"""


from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from typing import TYPE_CHECKING, Any, LiteralString, TypeVar

from neomodel.properties import Property
from neomodel.sync_.database import db

from agent_neo.graph_db import (
    GRAPH_DB_BATCH_SIZE,
    reconnect_neo4j_driver,
    retry_neo4j_cluster_operation,
)
from agent_neo.util.datetime import coerce_to_utc_for_neo4j_datetime

from .enum import (
    NodeLifecycleStatus,
    GraphEdgeKind,
)
from .identity import AnalyticalProductIdentity

if TYPE_CHECKING:
    from agent_neo.analytical_product.scope import ComputeScope

    from .abstract import ComputedNodeResult


__all__: tuple[LiteralString, ...] = (
    'BulkPersistItem',
    'persist_many',
    'prefetch_current_by_cache_keys',
)


T = TypeVar('T')


@dataclass(frozen=True, slots=True)
class BulkPersistItem:
    """One computed graph node instance to write in a bulk persistence pass."""

    identity: AnalyticalProductIdentity
    compute_result: ComputedNodeResult
    retiring: Any | None


def persist_many(product_cls: type, scope: ComputeScope, items: list[BulkPersistItem]) -> dict[str, Any]:
    """Persist a computed cohort and return the current nodes keyed by ``cache_key``.

    Implements retire-not-mutate at set scale (mint/refresh current, flip prior to
    ``retired``, no ``SUPERSEDES`` edge). Because this path is raw Cypher, it **must** also
    set ``created``/``updated`` (epoch seconds, ``DateTimeProperty``-comparable) and mark
    impacted dependents — otherwise cascade silently misses bulk writes.
    """
    if not items:
        return {}

    local_tz = _local_tz(scope)
    now = datetime.now(tz=UTC)
    now_epoch_seconds = now.timestamp()
    upsert_rows = [
        _upsert_row(
            product_cls,
            item.identity,
            item.compute_result,
            local_tz=local_tz,
            now=now,
            now_epoch_seconds=now_epoch_seconds,
        )
        for item in items
    ]
    cache_keys = [row['cache_key'] for row in upsert_rows]
    upserted_element_ids_by_cache_key = _bulk_upsert_nodes(product_cls, upsert_rows, now_epoch_seconds)

    from .dependency_registry import collect_dependency_targets, get_computed_node_depends_on_slots

    depends_on_slots = get_computed_node_depends_on_slots(product_cls)
    for slot in depends_on_slots:
        _bulk_replace_relationships(
            product_cls,
            _relationship_rows(
                cache_keys=cache_keys,
                rel_name=slot.manager_name,
                rel_type=slot.rel_type.value,
                target_groups=[
                    collect_dependency_targets(item.compute_result, (slot,))[slot.manager_name]
                    for item in items
                ],
            ),
        )
    computes_design_rel_name = getattr(product_cls, 'COMPUTES_DESIGN_REL', 'computes_design')
    _bulk_replace_relationships(
        product_cls,
        _single_relationship_rows(
            cache_keys=cache_keys,
            rel_name=computes_design_rel_name,
            rel_type=GraphEdgeKind.COMPUTES_DESIGN.value,
            targets=[item.compute_result.computes_design for item in items],
        ),
    )
    for_subject_rel_name = getattr(product_cls, 'FOR_SUBJECT_REL', None)
    if for_subject_rel_name is not None:
        _bulk_replace_relationships(
            product_cls,
            _single_relationship_rows(
                cache_keys=cache_keys,
                rel_name=for_subject_rel_name,
                rel_type=GraphEdgeKind.FOR_SUBJECT.value,
                targets=[item.compute_result.for_subject for item in items],
            ),
        )

    retired_element_ids = _bulk_retire_prior_nodes(
        items,
        upserted_element_ids_by_cache_key,
        now_epoch_seconds,
    )
    _mark_bulk_changed_nodes(
        changed_element_ids=[
            *retired_element_ids,
            *upserted_element_ids_by_cache_key.values(),
        ]
    )
    return prefetch_current_by_cache_keys(product_cls, cache_keys)


def prefetch_current_by_cache_keys(product_cls: type, cache_keys: Iterable[str]) -> dict[str, Any]:
    """Fetch current product nodes by cache key in one indexed NeoModel query."""
    clean_cache_keys = [cache_key for cache_key in dict.fromkeys(cache_keys) if cache_key]
    if not clean_cache_keys:
        return {}
    nodes = list(product_cls.nodes.filter(cache_key__in=clean_cache_keys))  # type: ignore[attr-defined]
    return {
        node.cache_key: node
        for node in nodes
        if getattr(node, 'lifecycle_status', None) != NodeLifecycleStatus.RETIRED.value
    }


def _product_kind(product_cls: type, compute_result: ComputedNodeResult) -> str:
    """Resolve ``product_kind`` from the design node or the wired design node's ``LAYER``."""
    concept = compute_result.computes_design
    if concept is not None:
        concept_product_kind = getattr(concept, 'product_kind', None)
        if concept_product_kind:
            return str(concept_product_kind)
    return product_cls.layer().name


def _upsert_row(
    product_cls: type,
    identity: AnalyticalProductIdentity,
    compute_result: ComputedNodeResult,
    *,
    local_tz: tzinfo,
    now: datetime,
    now_epoch_seconds: float,
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        'cache_key': identity.cache_key,
        'facility_name': identity.scope_name,
        'subject_kind': identity.subject_kind,
        'subject_key': identity.subject_key,
        'product_kind': _product_kind(product_cls, compute_result),
        'temporal_granularity': identity.temporal_granularity,
        'local_period_start': coerce_to_utc_for_neo4j_datetime(
            identity.local_period_start,
            local_tz,
            name='local_period_start',
        ),
        'local_period_end': coerce_to_utc_for_neo4j_datetime(
            identity.local_period_end,
            local_tz,
            name='local_period_end',
        ),
        'lifecycle_status': NodeLifecycleStatus.OFFICIAL.value,
        'computed_at': now,
        'needs_redo_since': None,
    }
    properties.update(compute_result.payload)
    return {
        'cache_key': identity.cache_key,
        'properties': _deflate_model_properties(product_cls, properties, now_epoch_seconds),
    }


def _deflate_model_properties(product_cls: type, properties: dict[str, Any], now_epoch_seconds: float) -> dict[str, Any]:
    model_properties: dict[str, Property] = product_cls.defined_properties(aliases=False, rels=False)
    clean_properties: dict[str, Any] = {}
    for field_name, value in properties.items():
        if field_name not in model_properties:
            continue
        property_definition = model_properties[field_name]
        db_property_name = property_definition.get_db_property_name(field_name)
        if value is None:
            clean_properties[db_property_name] = None
            continue
        clean_properties[db_property_name] = property_definition.deflate(value)

    # Raw Cypher bypasses the DjangoNeoModelWithCreatedAndUpdatedProps save hook.
    clean_properties['updated'] = now_epoch_seconds
    return clean_properties


def _bulk_upsert_nodes(product_cls: type, rows: list[dict[str, Any]], now_epoch_seconds: float) -> dict[str, str]:
    label = _label(product_cls)
    query = (
        f'UNWIND $rows AS row '
        f'MERGE (n:`{label}` {{cache_key: row.cache_key}}) '
        f'SET n += row.properties, '
        f'n.updated = $now, '
        f'n.created = coalesce(n.created, $now), '
        f'n.needs_redo_since = null '
        f'RETURN n.cache_key AS cache_key, elementId(n) AS element_id'
    )
    element_ids_by_cache_key: dict[str, str] = {}
    for batch in _batched(rows, GRAPH_DB_BATCH_SIZE):
        def _run() -> list[list[Any]]:
            result_rows, _ = db.cypher_query(query, {'rows': batch, 'now': now_epoch_seconds})
            return result_rows

        for cache_key, element_id in retry_neo4j_cluster_operation(
            _run,
            description=f'bulk upsert {label} computed instances',
            reconnect=reconnect_neo4j_driver,
        ):
            element_ids_by_cache_key[str(cache_key)] = str(element_id)
    return element_ids_by_cache_key


def _relationship_rows(
    *,
    cache_keys: list[str],
    rel_name: str,
    rel_type: str,
    target_groups: list[list[Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cache_key, targets in zip(cache_keys, target_groups, strict=True):
        rows.append(_relationship_row(cache_key, rel_name, rel_type, targets))
    return rows


def _single_relationship_rows(
    *,
    cache_keys: list[str],
    rel_name: str,
    rel_type: str,
    targets: list[Any | None],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cache_key, target in zip(cache_keys, targets, strict=True):
        if target is None:
            continue
        rows.append(_relationship_row(cache_key, rel_name, rel_type, [target]))
    return rows


def _relationship_row(cache_key: str, rel_name: str, rel_type: str, targets: list[Any]) -> dict[str, Any]:
    target_element_ids: list[str] = []
    target_labels: set[str] = set()
    for target in targets:
        element_id = getattr(target, 'element_id', None)
        target_label = getattr(type(target), '__label__', None)
        if not element_id or not target_label:
            continue
        target_element_ids.append(str(element_id))
        target_labels.add(str(target_label))
    return {
        'cache_key': cache_key,
        'rel_name': rel_name,
        'rel_type': rel_type,
        'target_element_ids': target_element_ids,
        'target_labels': sorted(target_labels),
    }


def _bulk_replace_relationships(product_cls: type, rows: list[dict[str, Any]]) -> None:
    clean_rows = [row for row in rows if row['target_element_ids'] or row['target_labels']]
    if not clean_rows:
        return

    label = _label(product_cls)
    for rel_type in sorted({row['rel_type'] for row in clean_rows}):
        rel_rows = [row for row in clean_rows if row['rel_type'] == rel_type]
        query = (
            f'UNWIND $rows AS row '
            f'MATCH (source:`{label}` {{cache_key: row.cache_key}}) '
            f'CALL (source, row) {{ '
            f'  OPTIONAL MATCH (source)-[old:`{rel_type}`]->(old_target) '
            f'  WHERE any(label IN labels(old_target) WHERE label IN row.target_labels) '
            f'  DELETE old '
            f'}} '
            f'WITH source, row '
            f'UNWIND row.target_element_ids AS target_element_id '
            f'MATCH (target) WHERE elementId(target) = target_element_id '
            f'MERGE (source)-[:`{rel_type}`]->(target) '
            f'RETURN count(*) AS relationships_merged'
        )
        for batch in _batched(rel_rows, GRAPH_DB_BATCH_SIZE):
            def _run() -> list[Any]:
                result_rows, _ = db.cypher_query(query, {'rows': batch})
                return result_rows

            retry_neo4j_cluster_operation(
                _run,
                description=f'bulk replace {label} {rel_type} relationships',
                reconnect=reconnect_neo4j_driver,
            )


def _bulk_retire_prior_nodes(
    items: list[BulkPersistItem],
    upserted_element_ids_by_cache_key: dict[str, str],
    now_epoch_seconds: float,
) -> list[str]:
    retiring_element_ids: list[str] = []
    for item in items:
        retiring = item.retiring
        if retiring is None:
            continue
        retiring_element_id = getattr(retiring, 'element_id', None)
        current_element_id = upserted_element_ids_by_cache_key.get(item.identity.cache_key)
        if retiring_element_id and current_element_id and str(retiring_element_id) != str(current_element_id):
            retiring_element_ids.append(str(retiring_element_id))

    clean_retiring_element_ids = list(dict.fromkeys(retiring_element_ids))
    if not clean_retiring_element_ids:
        return []

    query = (
        'UNWIND $element_ids AS element_id '
        'MATCH (n) WHERE elementId(n) = element_id '
        'SET n.lifecycle_status = $retired, n.updated = $now '
        'RETURN elementId(n) AS element_id'
    )
    retired_element_ids: list[str] = []
    for batch in _batched(clean_retiring_element_ids, GRAPH_DB_BATCH_SIZE):
        def _run() -> list[list[Any]]:
            result_rows, _ = db.cypher_query(
                query,
                {
                    'element_ids': batch,
                    'retired': NodeLifecycleStatus.RETIRED.value,
                    'now': now_epoch_seconds,
                },
            )
            return result_rows

        retired_element_ids.extend(
            str(row[0])
            for row in retry_neo4j_cluster_operation(
                _run,
                description='bulk retire prior computed instances',
                reconnect=reconnect_neo4j_driver,
            )
        )
    return retired_element_ids


def _mark_bulk_changed_nodes(*, changed_element_ids: list[str]) -> None:
    clean_element_ids = list(dict.fromkeys(element_id for element_id in changed_element_ids if element_id))
    if not clean_element_ids:
        return
    from .computed_product_cascade import is_cascade_suppressed, mark_impacted_needs_redo

    if is_cascade_suppressed():
        return
    mark_impacted_needs_redo(changed_element_ids=clean_element_ids)


def _local_tz(scope: ComputeScope) -> tzinfo:
    for attr in ('local_tz', 'tz', 'timezone'):
        candidate = getattr(scope, attr, None)
        if isinstance(candidate, tzinfo):
            return candidate
    raise AttributeError('ComputeScope does not expose a facility timezone (local_tz/tz/timezone)')


def _label(model_class: type) -> str:
    label = getattr(model_class, '__label__', None)
    if not label:
        raise AttributeError(f'{model_class.__name__} does not declare __label__')
    return str(label)


def _batched(items: list[T], size: int) -> Iterable[list[T]]:
    for start_index_0_based in range(0, len(items), size):
        yield items[start_index_0_based:start_index_0_based + size]
