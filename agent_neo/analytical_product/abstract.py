"""Computed graph node engine: abstract NeoModel bases + the canonical ``.get(request)`` path.

Every computed family inherits :class:`AbstractComputedGraphNode`, wires ``computes_design``
(layer via the design node), implements ``_compute``, and shares one ensure/lineage/freshness
behavior plus a unified instance spine. Design-node families inherit :class:`AbstractDesignNode`,
declare ``LAYER``, and carry design-graph ``DEPENDS_ON_DESIGN_RELS`` registries plus shared
lifecycle fields. Identity uses ``cls.__name__`` as ``computed_node_class_name``.

Ensure algorithm::

    get(request):
      1. resolve identities (maturity-clamped windows)
      2. for each identity:
           probe current (official/provisional) instance at cache_key
           if found and valid (lineage + drift + age-fresh) -> serve
           else: _compute; persist; retire prior current (no SUPERSEDES edge)
      3. return instances in identity order

Only View-layer nodes are servable at the boundary: ``serve`` raises for non-View layers.
Populate and cascade recompute reuse this same ``get`` path. Cohort writes go through
:func:`persist_many` (signals bypassed — cascade-mark parity owned there).
"""


from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, tzinfo
from typing import TYPE_CHECKING, Any, ClassVar, Iterable, LiteralString

from neomodel.properties import (
    DateTimeNeo4jFormatProperty,
    DateTimeProperty,
    Property,
    StringProperty,
)
from neomodel.sync_.database import db

from agent_neo.graph_db import reconnect_neo4j_driver, retry_neo4j_cluster_operation
from agent_neo.util.django_neomodel.models import DjangoNeoModelWithCreatedAndUpdatedProps
from agent_neo.util.datetime import coerce_to_utc, coerce_to_utc_for_neo4j_datetime

from .computed_product_bulk_persist import BulkPersistItem, persist_many, prefetch_current_by_cache_keys
from .dependency_registry import (
    get_computes_design_class,
    get_computed_node_depends_on_slots,
    iter_dependency_managers,
)
from .enum import (
    ComputedNodeLayer,
    NodeLifecycleStatus,
    GraphEdgeKind,
)
from .identity import ComputedSlotIdentity
from .request import ComputeRequest

if TYPE_CHECKING:
    from agent_neo.analytical_product.scope import ComputeScope

    from .dependency_registry import DependencySlot


__all__: tuple[LiteralString, ...] = (
    'AbstractDesignNode',
    'AbstractComputedGraphNode',
    'ComputedNodeResult',
)


#: Lineage edge types whose *upstream* target, when ``updated`` more recently than
#: this instance was ``computed_at``, means the instance ``needs_redo`` (E6/E7
#: input-drift gate). Mirrors the cascade engine's ``_CASCADE_REL_TYPES``: the
#: unified instance-level ``DEPENDS_ON`` graph (peer computed instances and
#: source-layer leaves) plus the ``computes_design`` bridge to each instance's design node.
_INPUT_REL_PATTERN: str = '|'.join((
    GraphEdgeKind.DEPENDS_ON.value,
    GraphEdgeKind.COMPUTES_DESIGN.value,
))


# ============================================================================
# Compute result (what a family's _compute returns)
# ============================================================================

@dataclass(slots=True)
class ComputedNodeResult:
    """The output of a family's ``_compute``: the payload plus the lineage to wire (E6).

    ``payload`` holds the family-specific scalar/JSON fields to persist on the instance (e.g.
    ``{'kwh': 12.3, 'calculation_method': ...}``). The engine sets identity/lifecycle fields itself.

    ``dependency_targets`` maps each declared ``DEPENDS_ON_RELS`` slot's ``manager_name`` to the
    already-resolved upstream nodes to connect (peer computed instances, source-layer leaves,
    etc.). Keys must match the product class ``DEPENDS_ON_RELS`` registry.
    """

    payload: dict[str, Any]
    dependency_targets: dict[str, list[Any]] = field(default_factory=dict)
    #: Single-cardinality provenance edges: the producing design node (``computes_design``) and
    #: the topology subject (``FOR_SUBJECT``). ``None`` leaves any existing edge untouched.
    computes_design: Any | None = None
    for_subject: Any | None = None


# ============================================================================
# Abstract design-node base (design-graph DEPENDS_ON_DESIGN registry + lifecycle)
# ============================================================================

class AbstractDesignNode(DjangoNeoModelWithCreatedAndUpdatedProps):
    """Abstract base for design nodes: shared lifecycle fields + ``DEPENDS_ON_DESIGN_RELS``.

    Design-node subclasses still declare explicit NeoModel ``RelationshipTo`` managers (one per
    upstream design-node type) and family-specific fields (``concept_key``, ``time_granularity``,
    etc.). The registry lists every manager so ``promote_concept`` and startup validation can
    discover them without ad-hoc Cypher.
    """

    __abstract_node__: bool = True

    LAYER: ClassVar[ComputedNodeLayer]

    DEPENDS_ON_DESIGN_RELS: ClassVar[tuple[DependencySlot, ...]] = ()

    lifecycle_status: Property = StringProperty(
        index=True,
        default=NodeLifecycleStatus.PROVISIONAL.value,
        choices={status.value: status.value for status in NodeLifecycleStatus},
    )
    product_kind: Property = StringProperty(index=True)
    retired_at: Property = DateTimeProperty(required=False)
    retirement_reason: Property = StringProperty(required=False)

    @classmethod
    def official_concept_defaults(cls, **field_overrides: Any) -> dict[str, Any]:
        """Return lifecycle + ``product_kind`` defaults for get-or-create of official design nodes."""
        return {
            'lifecycle_status': NodeLifecycleStatus.OFFICIAL.value,
            'product_kind': cls.LAYER.name,
            **field_overrides,
        }


# ============================================================================
# Abstract computed graph node base (ensure path + unified spine)
# ============================================================================

class AbstractComputedGraphNode(DjangoNeoModelWithCreatedAndUpdatedProps):
    """Abstract base for every computed graph node NeoModel: spine + unified ensure path.

    A concrete product class must:

    - inherit this class (which provides shared identity/lifecycle fields);
    - declare a ``computes_design`` ``RelationshipTo`` its design node (layer lives on the design node);
    - declare its lineage relationship managers and family payload fields;
    - implement :meth:`_compute`.

    Cache-key family identity uses ``cls.__name__`` as ``computed_node_class_name``;
    product classes do not declare a separate class-name attribute.
    """

    __abstract_node__: bool = True

    #: Override hooks for concrete NeoModel relationship-manager names on the product model.
    COMPUTES_DESIGN_REL: ClassVar[str] = 'computes_concept'
    FOR_SUBJECT_REL: ClassVar[str | None] = None
    DEPENDS_ON_RELS: ClassVar[tuple[DependencySlot, ...]] = ()

    # --- Logical slot identity (no version encoded) ---
    cache_key: Property = StringProperty(
        required=True,
        unique_index=True,
        max_length=256,
        label='Logical slot id',
        help_text='Deterministic over (facility, subject, time_granularity, window) — not over the design.',
    )
    facility_name: Property = StringProperty(required=True, index=True)
    subject_kind: Property = StringProperty(required=True, index=True)
    subject_key: Property = StringProperty(required=True, index=True)
    product_kind: Property = StringProperty(required=True, index=True)
    time_granularity: Property = StringProperty(required=True, index=True)
    local_period_start: Property = DateTimeNeo4jFormatProperty(required=True, index=True)
    local_period_end: Property = DateTimeNeo4jFormatProperty(required=True)

    # --- Lifecycle (replaces versioning) ---
    lifecycle_status: Property = StringProperty(
        index=True,
        default=NodeLifecycleStatus.PROVISIONAL.value,
        choices={status.value: status.value for status in NodeLifecycleStatus},
    )
    computed_at: Property = DateTimeProperty(default_now=True, required=False)
    needs_redo_since: Property = DateTimeProperty(required=False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def concept_class(cls) -> type[AbstractDesignNode]:
        """Design-node class for this computed family (from ``computes_design`` relationship)."""
        return get_computes_design_class(cls)

    @classmethod
    def layer(cls) -> ComputedNodeLayer:
        """Layer for this computed family (delegates to the wired design node's ``LAYER``)."""
        return cls.concept_class().LAYER

    @classmethod
    def get(cls, scope: ComputeScope, request: ComputeRequest) -> list[Any]:
        """Ensure-on-read every period instance the request resolves to; return the instances."""
        local_tz = _local_tz(scope)
        identities = request.resolve_identities(
            computed_node_class_name=cls.__name__,
            scope_name=_scope_name(scope),
            local_tz=local_tz,
        )
        if not identities:
            return []

        existing_by_cache_key = cls._prefetch_current_by_cache_keys(identity.cache_key for identity in identities)
        instances_by_cache_key: dict[str, Any] = {}
        persist_items: list[tuple[ComputedSlotIdentity, ComputedNodeResult, Any | None]] = []
        for identity in identities:
            existing = existing_by_cache_key.get(identity.cache_key)
            if (
                existing is not None
                and cls._is_valid(existing, identity=identity, request=request)
            ):
                instances_by_cache_key[identity.cache_key] = existing
                continue

            compute_result = cls._compute(scope, identity, request)
            persist_items.append((identity, compute_result, existing))

        if persist_items:
            instances_by_cache_key.update(cls._persist_many(scope, persist_items))

        return [instances_by_cache_key[i.cache_key] for i in identities if i.cache_key in instances_by_cache_key]

    @classmethod
    def serve(cls, scope: ComputeScope, request: ComputeRequest) -> list[dict[str, Any]]:
        """Boundary-checked serving form (E2/E11): Views only."""
        if not cls.layer().is_served:
            raise TypeError(
                f'{cls.__name__} is a {cls.layer().label}-layer node and cannot be served directly; '
                'only View-layer nodes cross the serving boundary.',
            )
        return [cls.to_payload(instance) for instance in cls.get(scope, request)]

    @classmethod
    def ensure_one(cls, scope: ComputeScope, identity: ComputedSlotIdentity, request: ComputeRequest) -> Any:
        """Fetch the valid current instance at ``identity`` or compute, persist, and retire the prior one."""
        existing = cls._probe_current(identity)
        if (
            existing is not None
            and cls._is_valid(existing, identity=identity, request=request)
        ):
            return existing

        compute_result = cls._compute(scope, identity, request)
        return cls._persist(scope, identity, compute_result, retiring=existing)

    # ------------------------------------------------------------------
    # Compute hook (implemented per family)
    # ------------------------------------------------------------------

    @classmethod
    def _compute(cls, scope: ComputeScope, identity: ComputedSlotIdentity, request: ComputeRequest) -> ComputedNodeResult:
        """Produce the payload + lineage for one computed graph node instance. Override per family."""
        raise NotImplementedError(f'{cls.__name__} must implement _compute()')

    @classmethod
    def to_payload(cls, instance: Any) -> dict[str, Any]:
        """Project a persisted instance into a plain serving dict. Override per family for shape."""
        return {
            'cache_key': getattr(instance, 'cache_key', None),
            'facility_name': getattr(instance, 'facility_name', None),
            'subject_kind': getattr(instance, 'subject_kind', None),
            'subject_key': getattr(instance, 'subject_key', None),
            'product_kind': getattr(instance, 'product_kind', None),
            'time_granularity': getattr(instance, 'time_granularity', None),
            'local_period_start': getattr(instance, 'local_period_start', None),
            'local_period_end': getattr(instance, 'local_period_end', None),
            'lifecycle_status': getattr(instance, 'lifecycle_status', None),
        }

    # ------------------------------------------------------------------
    # Probe + validity gates (E6 lineage / E7 freshness)
    # ------------------------------------------------------------------

    @classmethod
    def _probe_current(cls, identity: ComputedSlotIdentity) -> Any:
        """Return the current (official or provisional) instance at this identity's cache_key, or None."""
        node = cls.nodes.get_or_none(cache_key=identity.cache_key)  # type: ignore[attr-defined]
        if node is None:
            return None
        if getattr(node, 'lifecycle_status', None) == NodeLifecycleStatus.RETIRED.value:
            return None
        return node

    @classmethod
    def _prefetch_current_by_cache_keys(cls, cache_keys: Iterable[str]) -> dict[str, Any]:
        """Fetch current instances by cache key in one indexed query."""
        return prefetch_current_by_cache_keys(cls, cache_keys)

    @classmethod
    def _is_valid(cls, instance: Any, *, identity: ComputedSlotIdentity, request: ComputeRequest) -> bool:
        """A served instance is valid iff **all three** independent gates pass (E6 + E7)."""
        return (
            not cls._lineage_needs_redo(instance)
            and not cls._inputs_need_redo(instance)
            and cls._is_age_fresh(instance, identity=identity, freshness=request.freshness)
        )

    @classmethod
    def _inputs_need_redo(cls, instance: Any) -> bool:
        """Input-drift ``needs_redo`` gate (E6/E7): True iff a direct upstream input changed since compute."""
        element_id = getattr(instance, 'element_id', None)
        if not element_id:
            return False
        query = (
            'MATCH (n) WHERE elementId(n) = $element_id '
            f'MATCH (n)-[:{_INPUT_REL_PATTERN}]->(upstream) '
            'WHERE coalesce(upstream.updated, 0) > '
            'coalesce(n.computed_at, n.updated, 0) '
            'RETURN count(upstream) > 0 AS changed'
        )

        def _run() -> list[Any]:
            rows, _ = db.cypher_query(query, {'element_id': element_id})
            return rows

        rows = retry_neo4j_cluster_operation(
            _run,
            description='computed _inputs_need_redo timestamp probe',
            reconnect=reconnect_neo4j_driver,
        )
        return bool(rows[0][0]) if rows else False

    @classmethod
    def _lineage_needs_redo(cls, instance: Any) -> bool:
        """Lineage ``needs_redo`` predicate (E6)."""
        from neomodel.exceptions import CardinalityViolation

        if getattr(instance, 'needs_redo_since', None) is not None:
            return True

        concept_manager = getattr(instance, cls.COMPUTES_DESIGN_REL, None)
        if concept_manager is not None:
            try:
                concepts = list(concept_manager.all())
            except CardinalityViolation:
                concepts = []
            if not concepts:
                return True
            for concept in concepts:
                if getattr(concept, 'lifecycle_status', NodeLifecycleStatus.OFFICIAL.value) == (
                    NodeLifecycleStatus.RETIRED.value
                ):
                    return True

        for manager in iter_dependency_managers(instance, get_computed_node_depends_on_slots(cls)):
            try:
                dependencies = list(manager.all())
            except CardinalityViolation:
                dependencies = []
            for dependency in dependencies:
                if getattr(dependency, 'needs_redo_since', None) is not None:
                    return True
                if getattr(dependency, 'lifecycle_status', NodeLifecycleStatus.OFFICIAL.value) == (
                    NodeLifecycleStatus.RETIRED.value
                ):
                    return True
        return False

    @classmethod
    def _is_age_fresh(cls, instance: Any, *, identity: ComputedSlotIdentity, freshness: Any) -> bool:
        """Time-freshness gate (E7): is this stored instance still appropriate for the enquiry?"""
        now = datetime.now(tz=UTC)
        if freshness.max_staleness is None:
            return True
        computed_at = coerce_to_utc(getattr(instance, 'computed_at', None))
        if computed_at is None:
            return False
        return (now - computed_at) <= freshness.max_staleness

    # ------------------------------------------------------------------
    # Persistence + lineage wiring + retirement (E1 + E6)
    # ------------------------------------------------------------------

    @classmethod
    def _persist_many(
        cls,
        scope: ComputeScope,
        items: list[tuple[ComputedSlotIdentity, ComputedNodeResult, Any | None]],
    ) -> dict[str, Any]:
        """Persist a computed cohort through the shared bulk graph path."""
        bulk_items = [
            BulkPersistItem(identity=identity, compute_result=compute_result, retiring=retiring)
            for identity, compute_result, retiring in items
        ]
        return persist_many(cls, scope, bulk_items)

    @classmethod
    def _persist(
        cls,
        scope: ComputeScope,
        identity: ComputedSlotIdentity,
        compute_result: ComputedNodeResult,
        *,
        retiring: Any,
    ) -> Any:
        """Create/refresh the official instance, wire lineage edges, and retire the prior one."""
        persisted_by_cache_key = cls._persist_many(
            scope,
            [(identity, compute_result, retiring)],
        )
        return persisted_by_cache_key[identity.cache_key]

    @staticmethod
    def _reconnect(node: Any, rel_name: str, targets: list[Any]) -> None:
        """Idempotently set a relationship manager's targets to exactly ``targets``."""
        manager = getattr(node, rel_name, None)
        if manager is None or not targets:
            return
        existing = list(manager.all())
        target_ids = {getattr(t, 'element_id', None) for t in targets}
        for current in existing:
            if getattr(current, 'element_id', None) not in target_ids:
                manager.disconnect(current)
        existing_ids = {getattr(t, 'element_id', None) for t in existing}
        for target in targets:
            if getattr(target, 'element_id', None) not in existing_ids:
                manager.connect(target)

    @staticmethod
    def _reconnect_single(node: Any, rel_name: str, target: Any) -> None:
        """Set a cardinality-One/-ZeroOrOne relationship manager to exactly ``target``."""
        from neomodel.exceptions import CardinalityViolation

        manager = getattr(node, rel_name, None)
        if manager is None:
            return
        target_id = getattr(target, 'element_id', None)
        try:
            current = manager.single()
        except CardinalityViolation:
            current = None
        if current is not None and getattr(current, 'element_id', None) == target_id:
            return
        if current is not None:
            manager.disconnect(current)
        manager.connect(target)

    @classmethod
    def _retire_prior(cls, old_node: Any) -> None:
        """Mark the prior current instance ``retired`` (status flip only, no relationship)."""
        _set_if_present(old_node, 'lifecycle_status', NodeLifecycleStatus.RETIRED.value)
        old_node.save()


# ============================================================================
# Module helpers
# ============================================================================

def _scope_name(scope: ComputeScope) -> str:
    """Resolve scope identifier from ``scope_name`` or legacy ``facility_name``."""
    scope_name = getattr(scope, "scope_name", None)
    if scope_name:
        return str(scope_name)
    facility_name = getattr(scope, "facility_name", None)
    if facility_name:
        return str(facility_name)
    raise AttributeError("ComputeScope does not expose scope_name or facility_name")


def _local_tz(scope: ComputeScope) -> tzinfo:
    """Resolve the scope-local timezone from the active ComputeScope."""
    for attr in ("local_tz", "tz", "timezone"):
        candidate = getattr(scope, attr, None)
        if isinstance(candidate, tzinfo):
            return candidate
    raise AttributeError("ComputeScope does not expose a timezone (local_tz/tz/timezone)")


def _set_if_present(node: Any, field_name: str, value: Any) -> None:
    """Set a field only if the model declares it (shared fields are optional across families)."""
    if hasattr(type(node), field_name) or hasattr(node, field_name):
        setattr(node, field_name, value)


def _set_period_datetime(
    node: Any,
    field_name: str,
    value: datetime,
    *,
    local_tz: tzinfo,
) -> None:
    """Persist facility-local period bounds in Neo4j-safe UTC (``DateTimeNeo4jFormatProperty``)."""
    if hasattr(type(node), field_name) or hasattr(node, field_name):
        setattr(
            node,
            field_name,
            coerce_to_utc_for_neo4j_datetime(value, local_tz, name=field_name),
        )
