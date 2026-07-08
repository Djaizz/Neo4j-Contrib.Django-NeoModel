"""Graph database helpers."""


from __future__ import annotations

from typing import LiteralString

from agent_neo.graph._core import (
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


__all__: tuple[LiteralString, ...] = (
    "GRAPH_DB_BATCH_SIZE",
    "NEO4J_CLUSTER_LEADER_SWITCH_BACKOFF_MULTIPLIER",
    "NEO4J_CLUSTER_LEADER_SWITCH_MAX_ATTEMPTS",
    "NEO4J_CLUSTER_LEADER_SWITCH_MAX_RETRY_DELAY_SECONDS",
    "NEO4J_CLUSTER_LEADER_SWITCH_RETRY_DELAY_SECONDS",
    "GraphDbConfig",
    "GraphDbQueryAndReturnHeaderList",
    "batched_cypher_execute",
    "connect_graph_db",
    "is_graph_db_connected",
    "is_transient_neo4j_error",
    "load_query",
    "reconnect_graph_db_if_needed",
    "reconnect_neo4j_driver",
    "retry_neo4j_cluster_operation",
    "set_label_install_callback",
)


