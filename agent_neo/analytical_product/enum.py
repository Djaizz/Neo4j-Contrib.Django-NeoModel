"""Shared enums for computed graph nodes (lifecycle, lineage edges, layer kinds).

Cross-family building blocks so every computed node family shares identical layered-stack
vocabulary, lifecycle, and relationship-type enums. Enums only — ensure-on-read logic lives
in :mod:`agent_neo.analytical_product.abstract`.

Rationale: currency is ``lifecycle_status`` alone (no ``SUPERSEDES`` edge). Instance
dependency graphs use one graph type ``DEPENDS_ON`` even when Python splits managers
per NeoModel target class.
"""


from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import LiteralString


__all__: tuple[LiteralString, ...] = (
    'ComputedNodeLayer',
    'NodeLifecycleStatus',
    'GraphEdgeKind',
    'AnalyticalProductRelType',
    )


# ----------------------------------------------------------------------------
# Layer kinds (SOURCE → VIEW layered stack)
# ----------------------------------------------------------------------------
# SOURCE=0 = batched raw point/time coverage (the lineage leaf; not a computed node);
# FACT=1 = closest-to-source facts; METRIC=2 = derived metric rollups;
# INTERPRETATION=3 = interpretation; VIEW=4 = question/report view.


class ComputedNodeLayer(IntEnum):
    """Layer ordinals for the SOURCE → VIEW stack (SOURCE=0 … VIEW=4).

    ``SOURCE`` (L0) is the source-observation-set lineage leaf: it grounds the computed
    layers but is not itself a served computed node.
    """

    SOURCE = 0
    FACT = 1
    METRIC = 2
    INTERPRETATION = 3
    VIEW = 4

    @property
    def rank(self) -> int:
        """Lower rank is closer to source (SOURCE=0 … VIEW=4)."""
        return int(self)

    @property
    def label(self) -> str:
        """Human-readable layer label (source/fact/metric/interpretation/view)."""
        return self.name.lower()

    def may_depend_on(self, other: ComputedNodeLayer) -> bool:
        """Layering rule: a node may depend only on nodes at the same or a lower layer."""
        return other.rank <= self.rank

    @property
    def is_served(self) -> bool:
        """Only View-layer nodes cross the serving boundary."""
        return self is ComputedNodeLayer.VIEW


class NodeLifecycleStatus(StrEnum):
    """Replaces version numbers as the marker of what is current.

    - ``OFFICIAL`` and ``PROVISIONAL`` are both "in circulation": at most one instance/design
      node per identity (``cache_key`` or ``computed_node_class_name``) is ``OFFICIAL``, at
      most one is ``PROVISIONAL``; both are served and both are included in cascade/``needs_redo``
      scope.
    - ``RETIRED`` is the only "no longer current" state, retained for audit/replay until an
      administrative sweep removes it.
    - There is no ``SUPERSEDES`` relationship: "current" is this status alone, never a rewired
      edge. Evolving a node is mint-new + flip-prior-to-``RETIRED``.
    """

    OFFICIAL = 'official'
    PROVISIONAL = 'provisional'
    RETIRED = 'retired'


class GraphEdgeKind(StrEnum):
    """Lineage, provenance, and topology edge types for computed graph nodes."""

    DEPENDS_ON_CONCEPT = "DEPENDS_ON_CONCEPT"
    COMPUTES_CONCEPT = "COMPUTES_CONCEPT"
    FOR_SUBJECT = "FOR_SUBJECT"
    DEPENDS_ON = "DEPENDS_ON"
    DEPENDS_ON_DESIGN = "DEPENDS_ON_CONCEPT"
    COMPUTES_DESIGN = "COMPUTES_CONCEPT"


AnalyticalProductRelType = GraphEdgeKind
