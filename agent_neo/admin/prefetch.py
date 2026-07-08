"""Batch Cypher prefetch helpers for Django Admin and DRF."""


from __future__ import annotations

from typing import Any, Callable, LiteralString, Optional, TYPE_CHECKING

from django_neomodel.admin import DjangoNeoModelAdmin
from neomodel.integration.pandas import to_dataframe
from neomodel.sync_.database import db
from neomodel.sync_.node import StructuredNode

from agent_neo.graph.queries import GraphDbQueryAndReturnHeaderList

if TYPE_CHECKING:
    from rest_framework.viewsets import ReadOnlyModelViewSet


type CypherQueryResultRow = list[Any]
type PrefetchEntry = dict[str, Any]


__all__: tuple[LiteralString, ...] = (
    "run_prefetch","safe_list_from_row","safe_scalar_from_row",
    "format_prefetched_count_display","format_prefetched_list_display",
    "format_prefetched_list_display_truncated","format_prefetched_scalar_display",
    "set_prefetch_attrs_from_entry","attach_prefetch_cache_to_filtered_queryset",
)


def run_prefetch(
    admin_or_viewset: DjangoNeoModelAdmin | ReadOnlyModelViewSet,
    *,
    queryset: NodeSet,
    query_obj: GraphDbQueryAndReturnHeaderList,
    cypher_param_name_for_node_keys: str,
    result_row_key_column_name: str,
    node_key_name: str,
    build_prefetch_entry_from_row: Callable[
        [CypherQueryResultRow, GraphDbQueryAndReturnHeaderList], PrefetchEntry
    ],
    attach_prefetch_entry_to_node: Callable[[StructuredNode, PrefetchEntry], None],
) -> None:
    """Run a single batch Cypher prefetch, fill _prefetch_cache on the admin/viewset, and attach data to each node.

    Used by Django Admin (get_queryset / get_search_results) and DRF ViewSets (get_queryset)
    to load relationship data for a NodeSet in one query instead of N+1.

    Mechanics:
    ----------
    1. Keys: We collect the node identifier (e.g. uri, name, uuid) from every node in
       `queryset` using `node_key_name`. This list is passed to Cypher under the
       parameter name `cypher_param_name_for_node_keys` (e.g. {'asset_type_uris': [uri1, uri2, ...]}).

    2. One query: We run query_obj.query once with that parameter. The query must
       RETURN one row per requested node, with the node's key in a column named
       `result_row_key_column_name` (so we can match rows back to nodes). Other columns
       hold relationship data (lists, scalars) that build_prefetch_entry_from_row turns into a dict.

    3. build_prefetch_entry_from_row(row, query_obj) -> dict: For each result row, this
       callable extracts the relationship columns (using query_obj.get_column_index(...)
       for stable indices) and returns a dict. Callers typically use safe_list_from_row
       and safe_scalar_from_row for list/scalar columns. The dict is stored under the
       row's key in prefetch_cache.

    4. _prefetch_cache: We merge prefetch_cache into admin_or_viewset._prefetch_cache.
       Django Admin and DRF sometimes instantiate new node objects (e.g. after
       filtering or when rendering a row). Those new instances don't have the
       prefetched attributes we attach below; they can still read from the
       admin/viewset's _prefetch_cache using the node's key (e.g. obj.uri).

    5. attach_prefetch_entry_to_node(node, entry): For each node in the queryset we
       look up its entry and call this callable. It sets attributes on the node
       (e.g. node._prefetched_point_role_uris = entry['point_role_uris']) so
       list_display methods or serializers can read them without hitting the DB.

    Note: node_key_name has no default (e.g. not 'uri'). Callers must pass the
    attribute name used to key nodes in this model (e.g. 'uri', 'name', 'uuid').

    Parameters:
    -----------
    admin_or_viewset : Admin or ViewSet instance that has (or will have) _prefetch_cache.
    queryset : NodeSet of nodes to prefetch for (e.g. AssetType.nodes, or filtered subset).
    query_obj : Batch Cypher query object (.query string and .get_column_index(column_name)).
    cypher_param_name_for_node_keys : Cypher parameter name that receives the list of node keys (e.g. 'asset_type_uris').
    result_row_key_column_name : RETURN column name that contains the node key in each row (e.g. 'asset_type_uri').
    node_key_name : Node attribute used as key (e.g. 'uri', 'name', 'uuid'). No default; callers must specify.
    build_prefetch_entry_from_row : (row, query_obj) -> dict; builds the prefetch entry for one result row.
    attach_prefetch_entry_to_node : (node, entry) -> None; sets node._prefetched_* attributes from entry.
    """
    keys = [getattr(node, node_key_name) for node in queryset]

    if not keys:
        return

    results, _ = db.cypher_query(
        query_obj.query, {cypher_param_name_for_node_keys: keys}
    )

    # Column order matches query_obj.return_headers so get_column_index stays valid in build_prefetch_entry_from_row
    df = to_dataframe(query_results=(results, query_obj.return_headers))

    prefetch_cache: dict[str, PrefetchEntry] = {}
    for _, row in df.iterrows():
        key = row[result_row_key_column_name]
        prefetch_cache[key] = build_prefetch_entry_from_row(row.tolist(), query_obj)

    if not hasattr(admin_or_viewset, '_prefetch_cache'):
        admin_or_viewset._prefetch_cache = {}

    admin_or_viewset._prefetch_cache.update(prefetch_cache)

    for node in queryset:
        attach_prefetch_entry_to_node(
            node, prefetch_cache.get(getattr(node, node_key_name), {})
        )


def safe_list_from_row(
    row: CypherQueryResultRow,
    query_obj: GraphDbQueryAndReturnHeaderList,
    column_name: str,
    *,
    row_len_check: bool = True,
) -> list[str]:
    """Return a list of non-None values from a Cypher result row column.

    Used inside row_parser callbacks for run_prefetch to read list-typed RETURN columns
    (e.g. collect(...) of relationship targets). Neo4j returns list columns as Python
    lists; OPTIONAL MATCH or missing collect() can yield None or [null], so we treat
    None as [] and filter out None elements from the list.

    Parameters:
    -----------
    row : Single result row (list of values; indices match query RETURN order).
    query_obj : Object with .get_column_index(name) so we resolve column_name to an index
                without hardcoding positions (stable if RETURN clause order changes).
    column_name : Logical name of the column in the query's RETURN (e.g. 'asset_type_has_point_role_uris').
    row_len_check : If True (default), we avoid IndexError when row has fewer columns than
                    the requested index by treating that as None -> [].

    Returns:
    --------
    List of non-None strings (e.g. URIs or names). Empty if column is None or all nulls.

    Raises:
    -------
    TypeError : If the column value is not a list (e.g. scalar or dict); helps catch query/schema mismatch.
    """
    idx = query_obj.get_column_index(column_name)
    raw = row[idx] if (not row_len_check or len(row) > idx) and row[idx] is not None else []
    if not isinstance(raw, list):
        raise TypeError(
            f"Expected {column_name} to be a list, got {type(raw).__name__}: {raw}"
        )
    return [x for x in raw if x is not None]


def safe_scalar_from_row(
    row: CypherQueryResultRow,
    query_obj: GraphDbQueryAndReturnHeaderList,
    column_name: str,
) -> Optional[str]:
    """Return a scalar string from a Cypher result row column; empty string becomes None.

    Used inside row_parser callbacks for run_prefetch to read single-value RETURN columns
    (e.g. a related node's uri or name from an OPTIONAL MATCH). Neo4j can return
    empty string for missing or blank properties; we normalize '' to None so callers
    can use "if value:" consistently.

    Parameters:
    -----------
    row : Single result row (list of values).
    query_obj : Object with .get_column_index(name) for stable column lookup.
    column_name : Logical name of the column in the query's RETURN (e.g. 'aspect_type_uri').

    Returns:
    --------
    The column value as a string, or None if missing, empty string, or out-of-range index.
    """
    idx = query_obj.get_column_index(column_name)
    v = row[idx] if len(row) > idx and row[idx] else None
    return None if v == '' else v


def format_prefetched_list_display(
    obj: Any,
    admin_or_viewset: DjangoNeoModelAdmin | ReadOnlyModelViewSet,
    node_key: Any,
    attr_name: str,
    cache_entry_key: str,
    *,
    default: str = '-',
    sep: str = '   |   ',
) -> str:
    """Format a prefetched list for Django Admin list_display (obj → cache fallback, join or default).

    Use in list_display methods that show a list of URIs/names from prefetch. Reads from
    obj._prefetched_<attr_name> first, then from admin/viewset._prefetch_cache[node_key][cache_entry_key].
    """
    values = getattr(obj, attr_name, None)
    if values is None:
        cache = getattr(admin_or_viewset, '_prefetch_cache', {})
        values = cache.get(node_key, {}).get(cache_entry_key, [])
    if not isinstance(values, list):
        raise TypeError(f"Expected {cache_entry_key} to be a list, got {type(values).__name__}: {values}")
    if not values:
        return default
    return sep.join(values)


def format_prefetched_scalar_display(
    obj: Any,
    admin_or_viewset: DjangoNeoModelAdmin | ReadOnlyModelViewSet,
    node_key: Any,
    attr_name: str,
    cache_entry_key: str,
    *,
    default: str = '-',
) -> str:
    """Format a prefetched scalar for Django Admin list_display (obj → cache fallback, or default)."""
    value = getattr(obj, attr_name, None)
    if value is None:
        cache = getattr(admin_or_viewset, '_prefetch_cache', {})
        value = cache.get(node_key, {}).get(cache_entry_key)
    if not value or value == '':
        return default
    return value


def format_prefetched_list_display_truncated(
    obj: Any,
    admin_or_viewset: DjangoNeoModelAdmin | ReadOnlyModelViewSet,
    node_key: Any,
    attr_name: str,
    cache_entry_key: str,
    *,
    default: str = '-',
    sep: str = '   |   ',
    max_items: int = 5,
    overflow_suffix: str = ' sessions',
) -> str:
    """Format a prefetched list for list_display, showing up to max_items or 'N overflow_suffix'."""
    values = getattr(obj, attr_name, None)
    if values is None:
        cache = getattr(admin_or_viewset, '_prefetch_cache', {})
        values = cache.get(node_key, {}).get(cache_entry_key, [])
    if not isinstance(values, list):
        raise TypeError(
            f"Expected {cache_entry_key} to be a list, got {type(values).__name__}: {values}"
        )
    if not values:
        return default
    if len(values) > max_items:
        return f"{len(values)}{overflow_suffix}"
    return sep.join(values[:max_items])


def format_prefetched_count_display(
    obj: Any,
    admin_or_viewset: DjangoNeoModelAdmin | ReadOnlyModelViewSet,
    node_key: Any,
    attr_name: str,
    cache_entry_key: str,
) -> int:
    """Return the length of a prefetched list for Django Admin list_display (obj → cache fallback)."""
    values = getattr(obj, attr_name, None)
    if values is None:
        cache = getattr(admin_or_viewset, '_prefetch_cache', {})
        values = cache.get(node_key, {}).get(cache_entry_key, [])
    if not isinstance(values, list):
        raise TypeError(
            f"Expected {cache_entry_key} to be a list, got {type(values).__name__}: {values}"
        )
    return len(values)


def set_prefetch_attrs_from_entry(
    node: StructuredNode,
    entry: PrefetchEntry,
    attr_to_key_and_default: dict[str, tuple[str, Any]],
) -> None:
    """Set node._prefetched_* attributes from a prefetch entry using a mapping of attr_name -> (entry_key, default)."""
    for attr_name, (entry_key, default) in attr_to_key_and_default.items():
        setattr(node, attr_name, entry.get(entry_key, default))


def attach_prefetch_cache_to_filtered_queryset(
    viewset: ReadOnlyModelViewSet,
    queryset: NodeSet,
    node_key_name: str,
    set_attrs_from_entry: Callable[[StructuredNode, PrefetchEntry], None],
) -> NodeSet:
    """Re-attach prefetched data from viewset._prefetch_cache onto each node in a filtered queryset.

    DRF filter_queryset returns a subset of instances that may not have _prefetched_* set.
    Call this after super().filter_queryset(queryset) to apply cache entries to each node.
    set_attrs_from_entry(node, entry) should set node._prefetched_* from entry (same as
    attach_prefetch_entry_to_node used in run_prefetch).
    """
    if not hasattr(viewset, '_prefetch_cache'):
        return queryset
    cache = viewset._prefetch_cache
    for node in queryset:
        key = getattr(node, node_key_name)
        entry = cache.get(key, {})
        set_attrs_from_entry(node, entry)
    return queryset
