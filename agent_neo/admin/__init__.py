"""Admin utilities for NeoModel Django integration."""


from __future__ import annotations

from typing import LiteralString

from agent_neo.admin.prefetch import (
    attach_prefetch_cache_to_filtered_queryset,
    format_prefetched_count_display,
    format_prefetched_list_display,
    format_prefetched_list_display_truncated,
    format_prefetched_scalar_display,
    run_prefetch,
    safe_list_from_row,
    safe_scalar_from_row,
    set_prefetch_attrs_from_entry,
)
from agent_neo.admin.search import apply_admin_search


__all__: tuple[LiteralString, ...] = (
    "apply_admin_search",
    "attach_prefetch_cache_to_filtered_queryset",
    "format_prefetched_count_display",
    "format_prefetched_list_display",
    "format_prefetched_list_display_truncated",
    "format_prefetched_scalar_display",
    "run_prefetch",
    "safe_list_from_row",
    "safe_scalar_from_row",
    "set_prefetch_attrs_from_entry",
)


