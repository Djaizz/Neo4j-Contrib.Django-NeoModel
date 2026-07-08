"""Neo4j cluster retry helpers."""


from __future__ import annotations

from typing import LiteralString

from agent_neo.graph._core import (
    NEO4J_CLUSTER_LEADER_SWITCH_BACKOFF_MULTIPLIER,
    NEO4J_CLUSTER_LEADER_SWITCH_MAX_ATTEMPTS,
    NEO4J_CLUSTER_LEADER_SWITCH_MAX_RETRY_DELAY_SECONDS,
    NEO4J_CLUSTER_LEADER_SWITCH_RETRY_DELAY_SECONDS,
    _retry_delay_for_attempt,
    is_transient_neo4j_error,
    retry_neo4j_cluster_operation,
)


__all__: tuple[LiteralString, ...] = (
    "NEO4J_CLUSTER_LEADER_SWITCH_BACKOFF_MULTIPLIER",
    "NEO4J_CLUSTER_LEADER_SWITCH_MAX_ATTEMPTS",
    "NEO4J_CLUSTER_LEADER_SWITCH_MAX_RETRY_DELAY_SECONDS",
    "NEO4J_CLUSTER_LEADER_SWITCH_RETRY_DELAY_SECONDS",
    "_retry_delay_for_attempt",
    "is_transient_neo4j_error",
    "retry_neo4j_cluster_operation",
)
