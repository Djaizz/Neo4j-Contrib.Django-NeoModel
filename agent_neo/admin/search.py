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


# ---------------------------------------------------------------------------
# Admin / ViewSet prefetch utilities (batch Cypher to avoid N+1)
# ---------------------------------------------------------------------------
# See: .ai/rules/database/db-N+1-problem.md
#
# Background: When listing nodes (Django Admin changelist or DRF list/retrieve), each row
# often displays related data (e.g. "point roles" for an AssetType). If that data is loaded
# lazily per node, we get one Cypher query per row (N+1). These helpers run a single batch
# Cypher query that returns one row per node with relationship data in columns, then we
# attach that data to the node instances (and store it in a cache on the admin/viewset)
# so list and detail views can read it without further DB hits.
#
# The "key" (uri, name, or uuid) identifies the node in both the Cypher parameter list
# and the RETURN row. node_key_name is the Python attribute on the node (e.g. node.uri);
# result_row_key_column_name is the RETURN column name in the query (e.g. 'asset_type_uri').


type CypherQueryResultRow = list[Any]
type PrefetchEntry = dict[str, Any]


