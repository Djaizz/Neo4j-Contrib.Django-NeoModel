"""Environment placeholder resolution for graph configuration."""


from __future__ import annotations

from typing import LiteralString
import os
import re


__all__: tuple[LiteralString, ...] = (
    "is_env_placeholder",
    "parse_env_placeholder_names",
    "resolve_env_placeholder",
)


# Flexible whitespace: ``${ env : VAR | ALT }``, ``${env:VAR|ALT}``, etc.
_ENV_PLACEHOLDER_PATTERN = re.compile(
    r"^\$\{\s*env\s*:\s*(?P<names>[^}]+?)\s*\}$",
    re.IGNORECASE,
)
_ENV_NAME_SEPARATOR_PATTERN = re.compile(r"\s*\|\s*")


def _normalize_config_text(value: str) -> str:
    return " ".join(str(value).split())


def parse_env_placeholder_names(value: str) -> list[str] | None:
    """Return ordered env var names from a ``${env:...}`` placeholder, or ``None``."""
    text = _normalize_config_text(value)
    match = _ENV_PLACEHOLDER_PATTERN.match(text)
    if not match:
        return None
    return [
        name
        for name in (
            segment.strip()
            for segment in _ENV_NAME_SEPARATOR_PATTERN.split(match.group("names"))
        )
        if name
    ]


def is_env_placeholder(value: str) -> bool:
    """Return whether ``value`` is a ``${env:...}`` placeholder."""
    return parse_env_placeholder_names(value) is not None


def resolve_env_placeholder(value: str, *, default: str = "") -> str:
    """Resolve a config value, including multi-name ``${env: A | B }`` fallbacks."""
    raw_text = str(value).strip()
    environment_variable_names = parse_env_placeholder_names(raw_text)
    if environment_variable_names is None:
        return raw_text
    for environment_variable_name in environment_variable_names:
        resolved = os.environ.get(environment_variable_name)
        if resolved:
            return resolved
    return default
