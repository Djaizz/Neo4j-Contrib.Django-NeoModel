"""Agent graph utilities for Django + NeoModel applications.

The top-level names resolve lazily (PEP 562) so that the storage-agnostic
subpackages — ``agent_neo.a3`` in particular — import without Django, neomodel
or a Neo4j driver installed. ``from agent_neo import <name>`` still works; the
Django-bound module is loaded on first access, not at package import.
"""


from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, LiteralString

if TYPE_CHECKING:
    from agent_neo.util.django_neomodel.models import (
        DjangoNeoModelWithCreatedAndUpdatedProps,
        apply_neo4j_datetime_coercion_patch,
    )


__all__: tuple[LiteralString, ...] = (
    "DjangoNeoModelWithCreatedAndUpdatedProps",
    "apply_neo4j_datetime_coercion_patch",
)


_LAZY_EXPORTS: dict[str, str] = {
    "DjangoNeoModelWithCreatedAndUpdatedProps": "agent_neo.util.django_neomodel.models",
    "apply_neo4j_datetime_coercion_patch": "agent_neo.util.django_neomodel.models",
}


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value  # cache: subsequent access bypasses __getattr__
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
