"""Graph database configuration."""


from __future__ import annotations

from typing import LiteralString

from django_neomodel.graph_db._core import GraphDbConfig


__all__: tuple[LiteralString, ...] = ("GraphDbConfig",)
