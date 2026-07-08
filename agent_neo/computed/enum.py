"""Shared analytical-product enums (lifecycle, lineage edges, layer kinds).

Cross-product building blocks so every family shares identical SFMIV, lifecycle, and
relationship-type vocabulary. Enums only — ensure-on-read is in :mod:`...mixin`.

Design (DjangoNeoModel-GraphDB) — bidirectional with:
  dana/ontologist/odb-governance-harness/necessary-and-sufficient-design/concretized/DjangoNeoModel-GraphDB/
    neomodel-schema-and-indexing.md
    ensure-path-and-lifecycle.md
    lineage-cascade-and-signals.md
    IMPLEMENTATION-CROSSWALK.md

Rationale: currency is ``lifecycle_status`` alone (no ``SUPERSEDES``
edge — ``LIFECYCLE-MANAGE/NO-SUPERSESSION``). Instance dependency graph uses one graph
type ``DEPENDS_ON`` even when Python splits managers per NeoModel target class.
"""


from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import LiteralString


__all__: tuple[LiteralString, ...] = (
    'ComputedNodeLayer',
    'NodeLifecycleStatus',
    'GraphEdgeKind',
    )


# ----------------------------------------------------------------------------
# Layer / product kinds (odb-governance-harness/README.md §3)
# ----------------------------------------------------------------------------
# SFMIV: SOURCE=0 = batched raw point/time coverage (the lineage leaf; not a
# computed product); FACT=1 = closest-to-source facts; METRIC=2 = derived metric
# rollups; INTERPRETATION=3 = interpretation; VIEW=4 = question/report view.


class ComputedNodeLayer(IntEnum):
    """SFMIV layer ordinals (SOURCE=0 … VIEW=4).

    Mnemonic **SFMIV**: Source, Fact, Metric, Interpretation, View. ``SOURCE`` (L0) is the
    source-observation-set lineage leaf: it grounds the computed layers but is not itself a
    served product. See ``ARCHI : ANALYTICAL-5-LAYERS``.
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
        """Human-readable SFMIV layer label (source/fact/metric/interpretation/view)."""
        return self.name.lower()

    def may_depend_on(self, other: ComputedNodeLayer) -> bool:
        """SFMIV rule: a product may depend only on products at the same or a lower layer."""
        return other.rank <= self.rank

    @property
    def is_served(self) -> bool:
        """Only View-layer products cross the serving boundary."""
        return self is ComputedNodeLayer.VIEW


class NodeLifecycleStatus(StrEnum):
    """Replaces version numbers as the marker of what is current (odb-governance-harness/README.md §5.2).

    See ``dana/ontologist/odb-governance-harness/!-REQUIREMENTS/LIFECYCLE-MANAGE/OFFICIAL-or-PROVISIONAL-or-RETIRED.md``
    and ``LIFECYCLE-MANAGE/NO-SUPERSESSION.md`` for the full policy. Summary:

    - ``OFFICIAL`` and ``PROVISIONAL`` are both "in circulation": at most one instance/Concept per
      identity (``cache_key`` or ``computed_node_class_name``) is ``OFFICIAL``, at most one is
      ``PROVISIONAL``; both are served and both are included in cascade/``needs_redo`` scope.
    - ``RETIRED`` is the only "no longer current" state, retained for audit/replay until an
      administrative sweep removes it.
    - There is no ``SUPERSEDES`` relationship: "current" is this status alone, never a rewired
      edge, and there is no separate ``DEPRECATED``/``SUPERSEDED`` split — evolving a node is
      mint-new + flip-prior-to-``RETIRED`` (``LIFECYCLE-MANAGE/NO-SUPERSESSION.md``).
    """

    OFFICIAL = 'official'
    PROVISIONAL = 'provisional'
    RETIRED = 'retired'


class GraphEdgeKind(StrEnum):
    """Lineage, provenance, and topology edge types for computed graph nodes."""

    DEPENDS_ON_DESIGN = "DEPENDS_ON_CONCEPT"
    COMPUTES_DESIGN = "COMPUTES_CONCEPT"
    FOR_SUBJECT = "FOR_SUBJECT"
    DEPENDS_ON = "DEPENDS_ON"


