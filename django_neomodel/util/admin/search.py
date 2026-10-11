"""Django Admin search helpers for NeoModel NodeSets."""


from __future__ import annotations

from typing import LiteralString

from neomodel.match_q import Q
from neomodel.sync_.match import NodeSet


__all__: tuple[LiteralString, ...] = ("apply_admin_search",)


def apply_admin_search(
    queryset: NodeSet,
    search_term: str,
    search_fields: tuple[str, ...],
) -> NodeSet:
    """Apply admin search to a NodeSet using neomodel Q (OR across search_fields with icontains).

    Use at the start of get_search_results so that ?q=... filters the changelist even when
    the base django-neomodel get_search_results does not apply (e.g. different package version).
    """
    if not search_term or not search_fields:
        return queryset
    search_kwargs = {f"{f}__icontains": search_term for f in search_fields}
    search_q = Q(_connector=Q.OR, **search_kwargs)
    return queryset.filter(search_q)
