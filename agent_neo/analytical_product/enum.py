"""Shared enums for computed graph nodes (lifecycle, lineage edges, layer kinds).

Cross-family building blocks so every computed node family shares identical layered-stack
vocabulary, lifecycle, and relationship-type enums. Enums only — ensure-on-read logic lives
in :mod:`agent_neo.analytical_product.abstract`.

Rationale: currency is ``lifecycle_status`` alone (no ``SUPERSEDES`` edge). Instance
dependency graphs use one graph type ``DEPENDS_ON`` even when Python splits managers
per NeoModel target class.
"""


from __future__ import annotations

from enum import StrEnum
from typing import LiteralString

from agent_neo.a3.product import Layer, LifecycleStatus

__all__: tuple[LiteralString, ...] = (
    'ComputedNodeLayer',
    'GraphEdgeKind',
    'NodeLifecycleStatus',
    )


# ----------------------------------------------------------------------------
# Layer and lifecycle vocabulary — defined once, at the algebra floor
# ----------------------------------------------------------------------------
# ``ComputedNodeLayer`` and ``NodeLifecycleStatus`` are the historical names of
# ``agent_neo.a3.product.Layer`` and ``agent_neo.a3.product.LifecycleStatus``. They are the
# same class objects (not copies), so member identity, ``.value``/``.name`` and
# ``choices`` dicts behave exactly as before. The dependency runs this way — interpreter
# imports algebra — and never the reverse.

ComputedNodeLayer = Layer
NodeLifecycleStatus = LifecycleStatus


class GraphEdgeKind(StrEnum):
    """Lineage, provenance, and topology edge types for computed graph nodes."""

    DEPENDS_ON_CONCEPT = "DEPENDS_ON_CONCEPT"
    COMPUTES_CONCEPT = "COMPUTES_CONCEPT"
    FOR_SUBJECT = "FOR_SUBJECT"
    DEPENDS_ON = "DEPENDS_ON"
