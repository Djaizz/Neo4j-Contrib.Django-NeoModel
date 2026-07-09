"""JSON-safe structures for Neo4j JSONProperty persistence."""


from __future__ import annotations

from datetime import date, datetime
from typing import Any, LiteralString
import json


__all__: tuple[LiteralString, ...] = ('coerce_metrics_mapping', 'json_safe_structure')


def coerce_metrics_mapping(metrics: Any) -> dict[str, Any]:
    """Normalize L1 ``metrics`` from NeoModel or raw Cypher (sometimes JSON string)."""
    if metrics is None:
        return {}
    if isinstance(metrics, dict):
        return metrics
    if isinstance(metrics, str):
        if not metrics.strip():
            return {}
        try:
            parsed = json.loads(metrics)
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
