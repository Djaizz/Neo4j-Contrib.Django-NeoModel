"""Dependency-aware cascade engine for computed graph nodes."""


from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, LiteralString
import contextvars
import logging

from neomodel.sync_.database import db

from agent_neo.computed.registry import iter_registered_computed_node_classes
from agent_neo.graph_db import reconnect_neo4j_driver, retry_neo4j_cluster_operation
from agent_neo.time.periods import TimeGranularity, epoch_seconds

from .enum import GraphEdgeKind, NodeLifecycleStatus
from .request import ComputeRequest

if TYPE_CHECKING:
    from agent_neo.computed.scope import ComputeScope


__all__: tuple[LiteralString, ...] = (
    'DEFAULT_MAX_CASCADE_DEPTH',
    'CascadeImpact',
    'cascade_suppressed',
    'is_cascade_suppressed',
    'mark_impacted_needs_redo',
    'find_inputs_changed_needs_redo',
    'collect_needs_redo_impacts',
    'recompute_needs_redo',
)


log = logging.getLogger(__name__)

#: Upper bound on the transitive dependency walk. Layered-stack ordering guarantees a
#: cross-layer DAG (a node depends only on same-or-lower layers), so cycles are not a
#: real risk; the bound is a defensive guard against pathological fan-out and any
#: accidental same-layer loop.
DEFAULT_MAX_CASCADE_DEPTH: int = 25

#: Lineage edge types whose *inbound* traversal reaches dependents of a change:
#: the unified instance-level ``DEPENDS_ON`` graph plus the ``computes_design``
#: bridge to each instance's design node.
_CASCADE_REL_TYPES: tuple[str, ...] = (
    GraphEdgeKind.DEPENDS_ON.value,
    GraphEdgeKind.COMPUTES_DESIGN.value,
)


def _cypher_lifecycle_in_circulation(node_var: str) -> str:
    """Cypher predicate: node is in circulation (``official`` or ``provisional``, not ``retired``).

    Nodes missing ``lifecycle_status`` are treated as ``official``.
    """
    official_value = NodeLifecycleStatus.OFFICIAL.value
    retired_value = NodeLifecycleStatus.RETIRED.value
    return f"coalesce({node_var}.lifecycle_status, '{official_value}') <> '{retired_value}'"


def _AUDIT_UPDATED_SET(node_var: str) -> str:  # noqa: N802 - Cypher-fragment builder
    """Cypher ``SET`` fragment that bumps the audit ``updated`` field to ``$now``.

    Every raw-Cypher node mutation must keep ``updated`` authoritative (the
    ``save()`` hook on ``DjangoNeoModelWithCreatedAndUpdatedProps`` is bypassed by
    direct Cypher). Callers must bind a ``$now`` param (epoch seconds). The node
    is assumed to already exist, so ``created`` is left untouched here; only
    ``MERGE``-style creators set ``created = coalesce(created, $now)``.
    """
    return f'{node_var}.updated = $now'

#: Set while an eager recompute sweep is running so the signal receiver does not
#: re-mark/re-enter through the retirement saves the sweep itself performs.
_CASCADE_SUPPRESSED: contextvars.ContextVar[bool] = contextvars.ContextVar(
    'agent_neo_cascade_suppressed', default=False,
)


@dataclass(frozen=True, slots=True)
class CascadeImpact:
    """One downstream computed graph node marked ``needs_redo`` by a cascade.

    ``element_id`` is the Neo4j physical node id (``elementId(n)``) — the stable
    handle for this *graph node*, distinct from ``cache_key`` (the logical node
    slot). Cascade mark/recompute and de-dup key on ``element_id`` so each node is
    addressed exactly once even when multiple nodes share a slot history.
    """

    element_id: str  # Neo4j elementId(n); not cache_key / logical identity
    cache_key: str | None
    labels: tuple[str, ...]


class cascade_suppressed:  # noqa: N801 - context-manager sentinel, lower_snake by convention here
    """Context manager that suppresses signal-driven cascade marking within its body.

    Used by :func:`recompute_needs_redo` so the retirement saves it triggers do not
    re-enter the marking path (the sweep already orders work dependency-safely).
    """

    __slots__ = ('_token',)

    def __enter__(self) -> cascade_suppressed:
        self._token = _CASCADE_SUPPRESSED.set(True)
        return self

    def __exit__(self, *exc: object) -> None:
        _CASCADE_SUPPRESSED.reset(self._token)


def is_cascade_suppressed() -> bool:
    """Whether signal-driven cascade marking is currently suppressed."""
    return _CASCADE_SUPPRESSED.get()


def mark_impacted_needs_redo(
    *,
    changed_element_ids: list[str],
    now: datetime | None = None,
    max_depth: int = DEFAULT_MAX_CASCADE_DEPTH,
) -> list[CascadeImpact]:
    """Set ``needs_redo_since`` on the current downstream subgraph of the changed nodes.

    ``changed_element_ids`` are Neo4j ``elementId(n)`` values (physical node handles),
    not ``cache_key`` strings: mark must start from the exact changed nodes in the
    graph. One bounded Cypher statement walks lineage edges inbound from every
    changed node and flags all reachable *current* (``official`` or ``provisional``)
    dependents — ``retired`` dependents are excluded. Idempotent and signal-free
    (raw Cypher), so it can run safely inside a ``post_save`` handler without
    provoking a cascade storm. Returns the impacted dependents.
    """
    if not changed_element_ids:
        return []
    if not isinstance(max_depth, int) or max_depth < 1:
        raise ValueError(f'max_depth must be a positive int; got {max_depth!r}')

    rel_pattern = '|'.join(_CASCADE_REL_TYPES)
    # max_depth is a validated int (cannot be a Cypher parameter inside a
    # variable-length pattern), so string interpolation here is injection-safe.
    # ``updated`` is bumped alongside ``needs_redo_since`` so the audit timestamp
    # reflects this state change (raw Cypher bypasses the ``save()`` hook).
    query = (
        'MATCH (changed) WHERE elementId(changed) IN $element_ids '
        f'MATCH (dependent)-[:{rel_pattern}*1..{max_depth}]->(changed) '
        f'WHERE {_cypher_lifecycle_in_circulation("dependent")} '
        f'SET dependent.needs_redo_since = $now, {_AUDIT_UPDATED_SET("dependent")} '
        'RETURN DISTINCT elementId(dependent) AS element_id, '
        'dependent.cache_key AS cache_key, labels(dependent) AS labels'
    )
    params = {'element_ids': changed_element_ids, 'now': epoch_seconds(now)}

    def _run() -> list[Any]:
        rows, _ = db.cypher_query(query, params)
        return rows

    rows = retry_neo4j_cluster_operation(
        _run,
        description=f'cascade mark_impacted_needs_redo ({len(changed_element_ids)} changed)',
        reconnect=reconnect_neo4j_driver,
    )
    impacts = [
        CascadeImpact(
            element_id=row[0],
            cache_key=row[1],
            labels=tuple(row[2] or ()),
        )
        for row in rows
    ]
    if impacts:
        log.debug('cascade marked %d downstream products needs_redo', len(impacts))
    return impacts


def _to_neo4j_datetime(value: datetime) -> Any:
    """Render a tz-aware datetime as a native ``neo4j.time.DateTime`` for Cypher."""
    from neo4j.time import DateTime as Neo4jDateTime
    from agent_neo.models.base import coerce_to_fixed_offset_for_neo4j

    return Neo4jDateTime.from_native(coerce_to_fixed_offset_for_neo4j(value))


def find_inputs_changed_needs_redo(
    *,
    facility_name: str | None = None,
    now: datetime | None = None,
    max_depth: int = DEFAULT_MAX_CASCADE_DEPTH,
) -> list[CascadeImpact]:
    """Detect ``updated``-vs-``computed_at`` drift in bulk and mark the impacted subgraph ``needs_redo``.

    The robust, signal-free complement to explicit marks: one set-based Cypher finds every
    current (``official``/``provisional``) product whose direct lineage input was ``updated``
    more recently than the product was ``computed_at`` (catching raw-Cypher/bulk upstream writes
    that never ran a mark), flags those products (``needs_redo_since`` + ``updated``), then
    transitively flags everything downstream of them via :func:`mark_impacted_needs_redo`. Scope
    to ``scope_name`` to avoid a full-store scan whenever possible. Returns the de-duplicated
    impact set.
    """
    rel_pattern = '|'.join(_CASCADE_REL_TYPES)
    facility_filter = '' if facility_name is None else 'AND dependent.facility_name = $scope_name '
    # Depth-1 timestamp comparison: a dependent is drifted iff some direct input's
    # ``updated`` is newer than the dependent's ``computed_at`` (own ``updated`` then
    # 0 as fallbacks). All compared fields are epoch-second floats.
    query = (
        'MATCH (dependent)-[:' + rel_pattern + ']->(upstream) '
        f'WHERE {_cypher_lifecycle_in_circulation("dependent")} '
        f'{facility_filter}'
        'AND coalesce(upstream.updated, 0) > '
        'coalesce(dependent.computed_at, dependent.updated, 0) '
        f'SET dependent.needs_redo_since = $now, {_AUDIT_UPDATED_SET("dependent")} '
        'RETURN DISTINCT elementId(dependent) AS element_id, '
        'dependent.cache_key AS cache_key, labels(dependent) AS labels'
    )
    params: dict[str, Any] = {'now': epoch_seconds(now)}
    if facility_name is not None:
        params['scope_name'] = facility_name

    def _run() -> list[Any]:
        rows, _ = db.cypher_query(query, params)
        return rows

    rows = retry_neo4j_cluster_operation(
        _run,
        description='cascade find_inputs_changed_needs_redo',
        reconnect=reconnect_neo4j_driver,
    )
    directly_drifted = [
        CascadeImpact(element_id=row[0], cache_key=row[1], labels=tuple(row[2] or ()))
        for row in rows
    ]
    if not directly_drifted:
        return []

    # Transitively flag everything downstream of the drifted products. The drifted
    # products themselves are already flagged above; union and de-dup by element id.
    downstream = mark_impacted_needs_redo(
        changed_element_ids=[impact.element_id for impact in directly_drifted],
        now=now,
        max_depth=max_depth,
    )
    by_element_id: dict[str, CascadeImpact] = {impact.element_id: impact for impact in directly_drifted}
    for impact in downstream:
        by_element_id.setdefault(impact.element_id, impact)
    return list(by_element_id.values())


def collect_needs_redo_impacts(*, facility_name: str | None = None) -> list[CascadeImpact]:
    """Gather every currently ``needs_redo_since``-flagged current product (for an eager sweep).

    Used by the opt-in eager-recompute path to recompute all outstanding marks (e.g. after a
    batch of corrections) without re-walking lineage. Scope to ``scope_name`` to avoid a
    full-store scan whenever possible.
    """
    facility_filter = '' if facility_name is None else 'AND n.facility_name = $scope_name '
    query = (
        'MATCH (n) WHERE n.needs_redo_since IS NOT NULL '
        f'AND {_cypher_lifecycle_in_circulation("n")} '
        f'{facility_filter}'
        'RETURN elementId(n) AS element_id, n.cache_key AS cache_key, labels(n) AS labels'
    )
    params = {'scope_name': facility_name} if facility_name is not None else {}

    def _run() -> list[Any]:
        rows, _ = db.cypher_query(query, params)
        return rows

    rows = retry_neo4j_cluster_operation(
        _run,
        description='cascade collect_needs_redo_impacts',
        reconnect=reconnect_neo4j_driver,
    )
    return [
        CascadeImpact(element_id=row[0], cache_key=row[1], labels=tuple(row[2] or ()))
        for row in rows
    ]


@dataclass(frozen=True, slots=True)
class _ImpactMeta:
    """ComputeRequest-shaping metadata for one impacted node (batched, not per-node fetched).

    Keyed by Neo4j ``element_id`` (physical node), not ``cache_key`` (logical slot).
    """

    element_id: str
    labels: tuple[str, ...]
    time_granularity: TimeGranularity | str | None
    subject_kind: str | None
    subject_key: str | None
    local_period_start: datetime | None
    local_period_end: datetime | None


@dataclass(slots=True)
class _RecomputeGroup:
    """A coalesced range recompute for one ``(class, subject, time_granularity)`` cohort."""

    product_cls: type
    subject_kind: str
    subject_key: str
    time_granularity: TimeGranularity | str
    local_period_start: datetime
    local_period_end: datetime
    member_count: int = 1


def recompute_needs_redo(
    scope: ComputeScope,
    impacts: list[CascadeImpact],
) -> dict[str, Any]:
    """Opt-in eager sweep: recompute marked nodes in layered-stack dependency order.

    Removes the per-impact N+1: one batched Cypher fetches the request-shaping
    metadata for every impacted node, then impacts are coalesced into one range
    ``ComputeRequest`` per ``(product class, subject_kind, subject_key, time_granularity)``
    cohort (spanning ``[min(local_period_start), max(local_period_end)]``).
    Groups recompute in layer-rank order (fact -> metric -> interpretation -> view)
    via the product class's ``.get`` — the same ensure path used on read, so there
    is one compute path. Cascade marking is suppressed for the duration so the
    deactivation saves performed here do not re-enter the marker.

    Lazy reads already guarantee eventual convergence; this just forces immediate
    consistency when a caller wants it (e.g. after a known correction batch).
    """
    if not impacts:
        return {'recomputed': 0, 'skipped': 0, 'by_layer': {}, 'groups': 0}

    registry = _product_class_registry()
    metadata_by_element_id = _fetch_impact_metadata([impact.element_id for impact in impacts])

    groups: dict[tuple[str, str, str, str], _RecomputeGroup] = {}
    skipped = 0
    for impact in impacts:
        product_cls = _resolve_product_class(impact, registry)
        meta = metadata_by_element_id.get(impact.element_id)
        if product_cls is None or meta is None:
            skipped += 1
            continue
        group = _group_for_meta(product_cls, meta)
        if group is None:
            skipped += 1
            continue
        existing = groups.get(_group_key(group))
        if existing is None:
            groups[_group_key(group)] = group
        else:
            existing.local_period_start = min(existing.local_period_start, group.local_period_start)
            existing.local_period_end = max(existing.local_period_end, group.local_period_end)
            existing.member_count += 1

    recomputed = 0
    by_layer: dict[str, int] = {}
    ordered_groups = sorted(groups.values(), key=lambda group: group.product_cls.layer().rank)

    with cascade_suppressed():
        for group in ordered_groups:
            request = ComputeRequest(
                subject_kind=group.subject_kind,
                subject_key=group.subject_key,
                time_granularity=group.time_granularity,
                local_period_start=group.local_period_start,
                local_period_end=group.local_period_end,
            )
            try:
                group.product_cls.get(scope, request)
            except Exception as exc:  # noqa: BLE001 - one bad group must not abort the sweep
                log.warning(
                    'cascade recompute failed for %s %s/%s: %s',
                    group.product_cls.__name__, group.subject_kind, group.subject_key, exc,
                )
                skipped += group.member_count
                continue
            recomputed += group.member_count
            layer_name = group.product_cls.layer().label
            by_layer[layer_name] = by_layer.get(layer_name, 0) + 1

    return {'recomputed': recomputed, 'skipped': skipped, 'by_layer': by_layer, 'groups': len(ordered_groups)}


def _fetch_impact_metadata(element_ids: list[str]) -> dict[str, _ImpactMeta]:
    """One Cypher: fetch request-shaping fields for every impacted node (no N+1).

    ``element_ids`` are Neo4j ``elementId(n)`` values (physical nodes), not ``cache_key``.
    """
    if not element_ids:
        return {}
    query = (
        'MATCH (n) WHERE elementId(n) IN $element_ids '
        'RETURN elementId(n) AS element_id, labels(n) AS labels, '
        'n.time_granularity AS time_granularity, n.subject_kind AS subject_kind, '
        'n.subject_key AS subject_key, '
        'n.local_period_start AS local_period_start, '
        'n.local_period_end AS local_period_end'
    )

    def _run() -> list[Any]:
        rows, _ = db.cypher_query(query, {'element_ids': element_ids})
        return rows

    rows = retry_neo4j_cluster_operation(
        _run,
        description=f'cascade fetch_impact_metadata ({len(element_ids)} nodes)',
        reconnect=reconnect_neo4j_driver,
    )
    metadata: dict[str, _ImpactMeta] = {}
    for row in rows:
        metadata[row[0]] = _ImpactMeta(
            element_id=row[0],
            labels=tuple(row[1] or ()),
            time_granularity=row[2],
            subject_kind=row[3],
            subject_key=row[4],
            local_period_start=_to_native_datetime(row[5]),
            local_period_end=_to_native_datetime(row[6]),
        )
    return metadata


def _to_native_datetime(value: Any) -> datetime | None:
    """Coerce a raw Cypher temporal (``neo4j.time.DateTime``) to a native ``datetime``."""
    if value is None:
        return None
    return value.to_native() if hasattr(value, 'to_native') else value


def _group_for_meta(product_cls: type, meta: _ImpactMeta) -> _RecomputeGroup | None:
    """Build a single-member recompute group from one node's metadata (or ``None`` if unshapeable)."""
    if not (meta.time_granularity and meta.subject_kind and meta.subject_key and meta.local_period_start):
        return None
    # Hourly resolvers treat the upper bound exclusively; daily/weekly/monthly
    # treat it inclusively at the lower-of-window. Mirror ``_span_upper_bound``.
    local_period_end = meta.local_period_end if meta.time_granularity == TimeGranularity.HOURLY else meta.local_period_start
    if local_period_end is None:
        local_period_end = meta.local_period_start
    return _RecomputeGroup(
        product_cls=product_cls,
        subject_kind=meta.subject_kind,
        subject_key=meta.subject_key,
        time_granularity=meta.time_granularity,
        local_period_start=meta.local_period_start,
        local_period_end=local_period_end,
    )


def _group_key(group: _RecomputeGroup) -> tuple[str, str, str, str]:
    return (group.product_cls.__name__, group.subject_kind, group.subject_key, group.time_granularity)


# ============================================================================
# Product-class registry (lazy; avoids import cycles with the product modules)
# ============================================================================

_REGISTRY_CACHE: dict[str, type] | None = None


def _product_class_registry() -> dict[str, type]:
    """Map ``__label__`` -> registered computed node class, built lazily and cached.

    Imported lazily because computed node modules import this package; importing
    them at module top level would create a cycle during app initialization.
    """
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is not None:
        return _REGISTRY_CACHE

    registry: dict[str, type] = {}
    for product_cls in iter_registered_computed_node_classes():
        label = getattr(product_cls, '__label__', None)
        if label:
            registry[label] = product_cls
    _REGISTRY_CACHE = registry
    return registry


def _resolve_product_class(impact: CascadeImpact, registry: dict[str, type]) -> type | None:
    for label in impact.labels:
        if label in registry:
            return registry[label]
    return None
