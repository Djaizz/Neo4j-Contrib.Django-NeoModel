"""Tests for environment placeholder resolution."""

from __future__ import annotations

import os

from agent_neo.util.env import resolve_env_placeholder


def test_resolve_env_placeholder_single_name(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_NEO_TEST_VAR", "resolved")
    assert resolve_env_placeholder("${env:AGENT_NEO_TEST_VAR}") == "resolved"


def test_resolve_env_placeholder_fallback_chain(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_NEO_PRIMARY", raising=False)
    monkeypatch.setenv("AGENT_NEO_FALLBACK", "from-fallback")
    assert (
        resolve_env_placeholder("${env:AGENT_NEO_PRIMARY | AGENT_NEO_FALLBACK}")
        == "from-fallback"
    )


def test_resolve_env_placeholder_passthrough_for_literal() -> None:
    assert resolve_env_placeholder("bolt://localhost:7687") == "bolt://localhost:7687"
