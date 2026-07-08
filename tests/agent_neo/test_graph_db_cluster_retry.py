"""Tests for agent_neo graph cluster retry helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_neo.graph_db._core import (
    NEO4J_CLUSTER_LEADER_SWITCH_BACKOFF_MULTIPLIER,
    NEO4J_CLUSTER_LEADER_SWITCH_MAX_ATTEMPTS,
    NEO4J_CLUSTER_LEADER_SWITCH_MAX_RETRY_DELAY_SECONDS,
    NEO4J_CLUSTER_LEADER_SWITCH_RETRY_DELAY_SECONDS,
    GraphDbConfig,
    _retry_delay_for_attempt,
    is_graph_db_connected,
    is_transient_neo4j_error,
    reconnect_neo4j_driver,
    retry_neo4j_cluster_operation,
)
import agent_neo.graph_db._core as graph_core


def test_is_transient_neo4j_error_leader_messages() -> None:
    assert is_transient_neo4j_error(Exception("No Leader Found"))
    assert is_transient_neo4j_error(Exception("not the leader of the cluster"))


def test_is_transient_neo4j_error_non_transient() -> None:
    assert not is_transient_neo4j_error(ValueError("bad cache key"))


def test_retry_neo4j_cluster_operation_recovers_after_transient(capsys: object) -> None:
    calls = {"count": 0}

    def flaky() -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            raise Exception("No Leader Found")
        return "ok"

    with patch("agent_neo.graph_db._core.time.sleep"):
        result = retry_neo4j_cluster_operation(
            flaky,
            description="test op",
            max_attempts=3,
            retry_delay_seconds=60.0,
        )

    assert result == "ok"
    assert calls["count"] == 2


def test_retry_delay_for_attempt_uses_bounded_backoff() -> None:
    assert _retry_delay_for_attempt(
        1,
        base_delay_seconds=30.0,
        backoff_multiplier=2.0,
        max_retry_delay_seconds=120.0,
    ) == 30.0
    assert _retry_delay_for_attempt(
        4,
        base_delay_seconds=30.0,
        backoff_multiplier=2.0,
        max_retry_delay_seconds=120.0,
    ) == 120.0


def _graph_db_config() -> GraphDbConfig:
    return GraphDbConfig(
        uri="bolt://localhost:7687",
        username="neo4j",
        password="secret",
        database="neo4j",
    )


def test_connect_db_default_skips_label_install() -> None:
    graph_core._active_database_url = None
    graph_core._labels_installed_for_url = None
    config = _graph_db_config()

    with (
        patch("agent_neo.graph_db._core.retry_neo4j_cluster_operation") as mock_retry,
        patch("agent_neo.graph_db._core.db") as mock_db,
        patch("agent_neo.graph_db._core.get_config") as mock_get_config,
        patch("agent_neo.graph_db._core.is_graph_db_connected", return_value=False),
        patch("agent_neo.graph_db._core._install_labels") as mock_install,
    ):
        mock_get_config.return_value = MagicMock()
        mock_retry.side_effect = lambda operation, **kwargs: operation()
        config.connect_db()

    mock_install.assert_not_called()
    mock_db.set_connection.assert_called_once()


def test_is_graph_db_connected_clears_stale_active_url_on_ping_failure() -> None:
    graph_core._active_database_url = "bolt://neo4j:secret@localhost:7687/neo4j"
    with patch("agent_neo.graph_db._core.db") as mock_db:
        mock_db.cypher_query.side_effect = OSError("defunct connection")
        assert is_graph_db_connected() is False
    assert graph_core._active_database_url is None


def test_default_retry_constants() -> None:
    assert NEO4J_CLUSTER_LEADER_SWITCH_MAX_ATTEMPTS == 5
    assert NEO4J_CLUSTER_LEADER_SWITCH_RETRY_DELAY_SECONDS == 30.0
    assert NEO4J_CLUSTER_LEADER_SWITCH_BACKOFF_MULTIPLIER == 2.0
    assert NEO4J_CLUSTER_LEADER_SWITCH_MAX_RETRY_DELAY_SECONDS == 120.0
