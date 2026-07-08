"""Design-node evolution — cascade trigger for design changes.

Rationale: never bump a version scalar. Mint a new ``official`` design node and flip the
prior to ``retired`` (no ``SUPERSEDES`` edge). That ``.save()`` fires signal handlers,
which mark every instance that ``computes_design`` the retired design node as ``needs_redo``
— design change converges like data change, without per-family invalidation.

Note: design-graph ``DEPENDS_ON_DESIGN`` is wired here, but instance cascade does not yet
walk that edge. Retirement of a producing design node still fans out via ``computes_design``.
"""


from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, LiteralString

from neomodel.sync_.database import db

from agent_neo.graph_db import reconnect_neo4j_driver, retry_neo4j_cluster_operation

from .enum import NodeLifecycleStatus, GraphEdgeKind


__all__: tuple[LiteralString, ...] = (
    'promote_concept',
    'reconnect_concept_depends_on_concepts',
    'retire_concept',
)


def promote_concept(
    *,
    previous: Any,
    current: Any,
    reason: str | None = None,
    now: datetime | None = None,
    depends_on_concepts: list[Any] | None = None,
) -> Any:
    """Promote a freshly-built ``current`` design node to official and retire ``previous``.

    ``current`` is an unsaved (or freshly created) design node for the same logical family;
    it is saved as official, then :func:`retire_concept` retires ``previous`` so the change
    cascades. When ``depends_on_concepts`` is provided, wires
    ``(current)-[:DEPENDS_ON_DESIGN]->(dependency)`` edges on the design graph.
    Returns the now-official ``current`` node.
    """
    current.lifecycle_status = NodeLifecycleStatus.OFFICIAL.value
    current.save()
    if depends_on_concepts:
        reconnect_concept_depends_on_concepts(current, depends_on_concepts)
    return retire_concept(previous=previous, current=current, reason=reason, now=now)


def reconnect_concept_depends_on_concepts(
    concept: Any,
    dependency_concepts: list[Any],
) -> None:
    """Replace-all ``DEPENDS_ON_DESIGN`` edges from ``concept`` to ``dependency_concepts``.

    Uses NeoModel ``element_id`` for idempotent connect/disconnect. When the design-node class
    declares ``DEPENDS_ON_DESIGN_RELS``, the first slot's manager name is used; otherwise
    ``depends_on_concept`` or raw Cypher is used.
    """
    from .dependency_registry import get_design_depends_on_design_slots

    concept_slots = get_design_depends_on_design_slots(concept.__class__)
    if len(concept_slots) == 1:
        rel_name = concept_slots[0].manager_name
    else:
        rel_name = 'depends_on_concept'
    manager = getattr(concept, rel_name, None)
    if manager is not None:
        existing_concepts = list(manager.all())
        target_element_ids = {
            getattr(dependency_concept, 'element_id', None)
            for dependency_concept in dependency_concepts
        }
        for existing_concept in existing_concepts:
            if getattr(existing_concept, 'element_id', None) not in target_element_ids:
                manager.disconnect(existing_concept)
        existing_element_ids = {
            getattr(existing_concept, 'element_id', None) for existing_concept in existing_concepts
        }
        for dependency_concept in dependency_concepts:
            if getattr(dependency_concept, 'element_id', None) not in existing_element_ids:
                manager.connect(dependency_concept)
        return

    concept_element_id = getattr(concept, 'element_id', None)
    if not concept_element_id:
        return
    dependency_element_ids = [
        element_id
        for dependency_concept in dependency_concepts
        if (element_id := getattr(dependency_concept, 'element_id', None))
    ]
    rel_type = GraphEdgeKind.DEPENDS_ON_DESIGN.value

    def _run_disconnect() -> None:
        db.cypher_query(
            f'MATCH (concept) WHERE elementId(concept) = $concept_element_id '
            f'MATCH (concept)-[rel:{rel_type}]->(dep) '
            'WHERE NOT elementId(dep) IN $dependency_element_ids '
            'DELETE rel',
            {
                'concept_element_id': concept_element_id,
                'dependency_element_ids': dependency_element_ids,
            },
        )

    retry_neo4j_cluster_operation(
        _run_disconnect,
        description='design node DEPENDS_ON_DESIGN disconnect stale',
        reconnect=reconnect_neo4j_driver,
    )

    for dependency_element_id in dependency_element_ids:
        def _run_connect(dep_id: str = dependency_element_id) -> None:
            db.cypher_query(
                f'MATCH (concept) WHERE elementId(concept) = $concept_element_id '
                f'MATCH (dep) WHERE elementId(dep) = $dependency_element_id '
                f'MERGE (concept)-[:{rel_type}]->(dep)',
                {
                    'concept_element_id': concept_element_id,
                    'dependency_element_id': dep_id,
                },
            )

        retry_neo4j_cluster_operation(
            _run_connect,
            description='design node DEPENDS_ON_DESIGN connect',
            reconnect=reconnect_neo4j_driver,
        )


def retire_concept(
    *,
    previous: Any,
    current: Any,
    reason: str | None = None,
    now: datetime | None = None,
) -> Any:
    """Retire ``previous`` (no relationship is created between ``current`` and ``previous``).

    Saving ``previous`` with ``lifecycle_status='retired'`` is the cascade hook: the ``post_save``
    receiver marks every instance that ``computes_design`` it ``needs_redo``. ``current`` must
    already be saved (it is the new official design node). A no-op if there is no real
    predecessor (including when ``previous`` and ``current`` are the same Neo4j node).

    Same-node detection uses Neo4j ``element_id`` (``elementId(n)`` / NeoModel
    ``node.element_id``) — the physical graph-node handle — not Python object identity
    and not a logical ``cache_key``.
    """
    if previous is None:
        return current
    # Physical Neo4j node id: do not retire the node we just promoted.
    if getattr(previous, 'element_id', None) == getattr(current, 'element_id', object()):
        return current

    previous.lifecycle_status = NodeLifecycleStatus.RETIRED.value
    if hasattr(type(previous), 'retired_at'):
        previous.retired_at = now or datetime.now(tz=UTC)
    if reason and hasattr(type(previous), 'retirement_reason'):
        previous.retirement_reason = reason
    previous.save()  # fires post_save -> cascade marks computes_design instances needs_redo

    return current
