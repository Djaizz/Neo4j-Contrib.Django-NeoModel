"""NeoModel base classes."""


from __future__ import annotations

from typing import LiteralString

from agent_neo.models.base import (
    DjangoNeoModelWithCreatedAndUpdatedProps,
    apply_neo4j_datetime_coercion_patch,
    coerce_to_fixed_offset_for_neo4j,
)


__all__: tuple[LiteralString, ...] = (
    "DjangoNeoModelWithCreatedAndUpdatedProps",
    "apply_neo4j_datetime_coercion_patch",
    "coerce_to_fixed_offset_for_neo4j",
)
