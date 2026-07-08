"""Graph database connection helpers."""


from __future__ import annotations

from typing import LiteralString

from agent_neo.graph._core import (
    connect_graph_db,
    is_graph_db_connected,
    reconnect_graph_db_if_needed,
    reconnect_neo4j_driver,
    set_label_install_callback,
)

__all__: tuple[LiteralString, ...] = (
    "connect_graph_db",
    "is_graph_db_connected",
    "reconnect_graph_db_if_needed",
    "reconnect_neo4j_driver",
    "set_label_install_callback",
)
