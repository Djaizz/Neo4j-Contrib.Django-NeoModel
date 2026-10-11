# AGENTS.md — `django_neomodel.util`

Generic utilities for Django + neomodel applications, one concern per module. Parent
context: [../AGENTS.md](../AGENTS.md) — what counts as generic, and the open-source rule.

## What lives here

| Module | Holds | Needs |
| --- | --- | --- |
| `json_safe.py` | `json_safe_structure` — a value made storable by a neomodel `JSONProperty`: datetimes and dates as ISO strings, sets as sorted lists, keys as strings, recursively; `coerce_json_mapping` — the mapping such a property reads back as, whether neomodel hands a dict or raw Cypher its JSON string | — |
| `neo4j_datetime.py` | `coerce_to_fixed_offset_for_neo4j` — a `zoneinfo` / `pytz` datetime the Neo4j driver can serialize without crashing CPython's zoneinfo extension, its zone name kept; `apply_neo4j_datetime_coercion_patch` — routes `DateTimeNeo4jFormatProperty.deflate` through it: idempotent, never applied on import, so call it once at startup | — |
| `openapi.py` | `DjangoNeoModelAutoSchema` — a drf-spectacular `AutoSchema` that gives every `DjangoField` a string schema | drf-spectacular |
| `admin/prefetch.py` | Batch Cypher prefetch for admin changelists and DRF viewsets, one query per page instead of N+1: `run_prefetch`; the row readers `safe_list_from_row` / `safe_scalar_from_row`; the `format_prefetched_*` list-display helpers, whose `strict=True` tells a prefetch that never ran (`PrefetchNotRunError`) from an absent value; `set_prefetch_attrs_from_entry`; `attach_prefetch_cache_to_filtered_queryset`; and `CypherQueryAndReturnHeaders`, the query shape they read (the text, its RETURN headers, a column lookup) | pandas, through neomodel's pandas integration |
| `admin/search.py` | `apply_admin_search` — the admin's `?q=` over a `NodeSet`, as a neomodel `Q` (an OR of `icontains` across the search fields) | — |

## Conventions

- **No `__init__.py`, anywhere under `util/`.** Every import names the module it comes
  from, in full: `from django_neomodel.util.admin.prefetch import run_prefetch`. Nothing
  is re-exported.
- A module that needs an optional dependency imports it itself, so only code that imports
  that module needs it installed; type-only imports go under `TYPE_CHECKING`.
- A helper takes the surface it works on as an argument (an admin, a viewset, a query
  object) rather than asking applications to inherit a base class.
- Names, defaults and examples carry no application vocabulary; examples use neutral words
  (books, shelves, libraries).
- `__all__` is a `tuple[LiteralString, ...]`.
- Tests: `tests/django_neomodel/`.
