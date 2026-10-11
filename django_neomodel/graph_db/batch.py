"""Batched Cypher execution helpers."""


from __future__ import annotations

from datetime import UTC, datetime
from typing import LiteralString

from django_neomodel.graph_db._core import GRAPH_DB_BATCH_SIZE, batched_cypher_execute


__all__: tuple[LiteralString, ...] = (
    "GRAPH_DB_BATCH_SIZE",
    "batched_cypher_execute",
    "neo4j_bulk_timestamps",
)


def neo4j_bulk_timestamps() -> dict[str, datetime]:
    """UTC datetimes for Cypher-created nodes (matches DjangoNeoModel save semantics)."""
    now = datetime.now(UTC)
    return {'created': now, 'updated': now}
