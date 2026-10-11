"""Packaged generic Cypher templates, and the loader for write-only statements."""


from __future__ import annotations

from pathlib import Path
from typing import LiteralString


__all__: tuple[LiteralString, ...] = (
    'COUNT_NODES_BY_PROPERTY_IN_KEYS',
    'DELETE_NODES_BY_PROPERTY_IN_KEYS',
    'load_query_text',
)


_CYPHER = Path(__file__).parent / 'cypher'


def load_query_text(cypher_file_path: Path) -> str:
    """Read a Cypher file (including write-only queries without RETURN)."""
    return cypher_file_path.read_text(encoding='utf-8').strip()


COUNT_NODES_BY_PROPERTY_IN_KEYS = load_query_text(_CYPHER / 'count-nodes-by-property-in-keys.cypher')
DELETE_NODES_BY_PROPERTY_IN_KEYS = load_query_text(_CYPHER / 'delete-nodes-by-property-in-keys.cypher')
