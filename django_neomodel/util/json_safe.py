"""JSON-safe structures for Neo4j JSONProperty persistence."""


from __future__ import annotations

from datetime import date, datetime
from typing import Any, LiteralString
import json


__all__: tuple[LiteralString, ...] = ('coerce_json_mapping', 'json_safe_structure')


def coerce_json_mapping(value: Any) -> dict[str, Any]:
    """Normalize a JSON mapping read back from NeoModel (a dict) or raw Cypher (sometimes its JSON string)."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        if not value.strip():
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def json_safe_structure(value: Any) -> Any:
    """Recursively convert datetimes (and similar) for JSONProperty / Neo4j storage."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe_structure(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe_structure(item) for item in value]
    if isinstance(value, set):
        return sorted(json_safe_structure(item) for item in value)
    return value
