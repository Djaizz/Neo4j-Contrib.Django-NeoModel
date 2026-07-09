"""Execute Cypher with chunking and cluster retry on writes."""


from __future__ import annotations

from collections.abc import Callable
from typing import Any, LiteralString


__all__: tuple[LiteralString, ...] = (
    'DEFAULT_DELETE_CHUNK_SIZE',
    'DEFAULT_IN_CHUNK_SIZE',
    'cypher_read',
    'cypher_write',
    'for_each_chunk',
)


DEFAULT_DELETE_CHUNK_SIZE = 500
DEFAULT_IN_CHUNK_SIZE = 500


def cypher_read(
    query: str,
    params: dict[str, Any],
    *,
    description: str = 'cypher read',
) -> tuple[list[list[Any]], list[str]]:
    from neomodel.sync_.database import db

    from agent_neo.graph_db import reconnect_neo4j_driver, retry_neo4j_cluster_operation

    return retry_neo4j_cluster_operation(
        lambda: db.cypher_query(query, params),
        description=description,
        reconnect=reconnect_neo4j_driver,
    )


def cypher_write(query: str, params: dict[str, Any], *, description: str = 'cypher write') -> None:
    from neomodel.sync_.database import db

    from agent_neo.graph_db import reconnect_neo4j_driver, retry_neo4j_cluster_operation

    retry_neo4j_cluster_operation(
        lambda: db.cypher_query(query, params),
        description=description,
        reconnect=reconnect_neo4j_driver,
    )


def for_each_chunk(
    items: list[Any],
    *,
    chunk_size: int,
    action: Callable[[list[Any]], None],
) -> int:
    """Run ``action`` on consecutive chunks; return total item count processed."""
    if not items:
        return 0
    processed = 0
    for chunk_start in range(0, len(items), chunk_size):
        chunk = items[chunk_start:chunk_start + chunk_size]
        action(chunk)
        processed += len(chunk)
    return processed
