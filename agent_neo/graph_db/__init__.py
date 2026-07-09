"""Graph database helpers."""


from __future__ import annotations

from typing import LiteralString

from agent_neo.graph_db._core import (
    GRAPH_DB_BATCH_SIZE,
    NEO4J_CLUSTER_LEADER_SWITCH_BACKOFF_MULTIPLIER,
    NEO4J_CLUSTER_LEADER_SWITCH_MAX_ATTEMPTS,
    NEO4J_CLUSTER_LEADER_SWITCH_MAX_RETRY_DELAY_SECONDS,
    NEO4J_CLUSTER_LEADER_SWITCH_RETRY_DELAY_SECONDS,
    GraphDbConfig,
    GraphDbQueryAndReturnHeaderList,
    batched_cypher_execute,
    connect_graph_db,
    is_graph_db_connected,
    is_transient_neo4j_error,
    load_query,
    reconnect_graph_db_if_needed,
    reconnect_neo4j_driver,
    retry_neo4j_cluster_operation,
    set_label_install_callback,
)
from agent_neo.graph_db.execute import (
    DEFAULT_DELETE_CHUNK_SIZE,
    DEFAULT_IN_CHUNK_SIZE,
    cypher_read,
    cypher_write,
    for_each_chunk,
)


__all__: tuple[LiteralString, ...] = (
    "DEFAULT_DELETE_CHUNK_SIZE",
    "DEFAULT_IN_CHUNK_SIZE",
    "GRAPH_DB_BATCH_SIZE",
    "NEO4J_CLUSTER_LEADER_SWITCH_BACKOFF_MULTIPLIER",
    "NEO4J_CLUSTER_LEADER_SWITCH_MAX_ATTEMPTS",
    "NEO4J_CLUSTER_LEADER_SWITCH_MAX_RETRY_DELAY_SECONDS",
    "NEO4J_CLUSTER_LEADER_SWITCH_RETRY_DELAY_SECONDS",
    "GraphDbConfig",
    "GraphDbQueryAndReturnHeaderList",
    "batched_cypher_execute",
    "connect_graph_db",
    "cypher_read",
    "cypher_write",
    "for_each_chunk",
    "is_graph_db_connected",
    "is_transient_neo4j_error",
    "load_query",
    "reconnect_graph_db_if_needed",
    "reconnect_neo4j_driver",
    "retry_neo4j_cluster_operation",
    "set_label_install_callback",
)
