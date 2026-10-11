"""Execute Cypher with chunking and cluster retry on writes."""


from __future__ import annotations

from collections.abc import Callable
from typing import Any, LiteralString
import logging


__all__: tuple[LiteralString, ...] = (
    'DEFAULT_DELETE_CHUNK_SIZE',
    'DEFAULT_IN_CHUNK_SIZE',
    'cypher_read',
    'cypher_write',
    'for_each_chunk',
    'safe_connect_relationship',
)


log = logging.getLogger(__name__)


DEFAULT_DELETE_CHUNK_SIZE = 500
DEFAULT_IN_CHUNK_SIZE = 500


def cypher_read(
    query: str,
    params: dict[str, Any],
    *,
    description: str = 'cypher read',
) -> tuple[list[list[Any]], list[str]]:
    from neomodel.sync_.database import db

    from django_neomodel.graph_db import reconnect_neo4j_driver, retry_neo4j_cluster_operation

    return retry_neo4j_cluster_operation(
        lambda: db.cypher_query(query, params),
        description=description,
        reconnect=reconnect_neo4j_driver,
    )


def cypher_write(query: str, params: dict[str, Any], *, description: str = 'cypher write') -> None:
    from neomodel.sync_.database import db

    from django_neomodel.graph_db import reconnect_neo4j_driver, retry_neo4j_cluster_operation

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


def safe_connect_relationship(
    connect_callable: Any,
    *,
    description: str,
    reraise_cardinality: bool = True,
) -> None:
    """Run a NeoModel ``.connect()`` with cluster leader retries on transient errors."""
    from django_neomodel.graph_db import reconnect_neo4j_driver, retry_neo4j_cluster_operation

    try:
        retry_neo4j_cluster_operation(
            connect_callable,
            description=description,
            reconnect=reconnect_neo4j_driver,
        )
    except Exception as exc:
        if reraise_cardinality:
            try:
                from neomodel.exceptions import CardinalityViolation  # noqa: PLC0415

                if isinstance(exc, CardinalityViolation):
                    raise
            except ImportError:
                pass
        log.warning(
            '%s: relationship connect failed (%s): %s',
            description,
            type(exc).__name__,
            exc,
        )
