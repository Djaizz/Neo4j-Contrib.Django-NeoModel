"""Batch cache lookups for period rollups — generic N+1 prefetch pattern."""


from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, LiteralString, TypeVar


__all__: tuple[LiteralString, ...] = (
    'PeriodCacheCoreMixin',
    'is_duplicate_cache_key_error',
    'sanitize_label_for_attr',
)


_NeoRollupNode = TypeVar('_NeoRollupNode')


def sanitize_label_for_attr(label: str) -> str:
    return label.replace(':', '_').replace('-', '_')


def is_duplicate_cache_key_error(exc: BaseException, *, cache_key: str) -> bool:
    from neomodel.exceptions import UniqueProperty

    if isinstance(exc, UniqueProperty):
        return True
    message = str(exc).lower()
    return (
        'already exists' in message
        and 'cache_key' in message
        and str(cache_key).lower() in message
    )


class PeriodCacheCoreMixin:
    """Generic spine-window and ``cache_key IN`` batch reads for populate / ensure-on-read."""

    @staticmethod
    def _node_or_row_attr(source: Any, name: str) -> Any:
        if isinstance(source, dict):
            return source.get(name)
        return getattr(source, name)

    def _clear_period_cache_bulk_indexes(
        self,
        *,
        period_index_prefix: str = '_period_bulk_index_',
        hourly_index_prefix: str = '_hourly_bulk_index_',
    ) -> None:
        """Drop instance-scoped bulk indexes (call at start/end of each populate day)."""
        for attr_name in list(vars(self)):
            if attr_name.startswith(period_index_prefix) or attr_name.startswith(hourly_index_prefix):
                delattr(self, attr_name)

    def _period_bulk_index_or_none(self, label: str, *, index_prefix: str = '_period_bulk_index_') -> dict[str, dict[str, Any]] | None:
        return getattr(self, f'{index_prefix}{sanitize_label_for_attr(label)}', None)

    def _period_rollup_rows_by_cache_keys(
        self,
        label: str,
        cache_keys: list[str],
        *,
        fetch_by_keys: Callable[[str, list[str]], dict[str, dict[str, Any]]],
        index_prefix: str = '_period_bulk_index_',
    ) -> dict[str, dict[str, Any]]:
        """Resolve rollup rows: populate bulk index first, else chunked ``IN $keys`` fetch."""
        if not cache_keys:
            return {}
        bulk_index = self._period_bulk_index_or_none(label, index_prefix=index_prefix)
        if bulk_index is not None:
            return {key: bulk_index[key] for key in cache_keys if key in bulk_index}
        return fetch_by_keys(label, cache_keys)

    def _partition_period_rollup_cache(
        self,
        *,
        label: str,
        period_windows: list[tuple[datetime, datetime]],
        cache_key_for_window: Callable[[datetime, datetime], str],
        serialize_row: Callable[[dict[str, Any]], dict[str, Any]],
        fetch_by_keys: Callable[[str, list[str]], dict[str, dict[str, Any]]],
        index_prefix: str = '_period_bulk_index_',
    ) -> tuple[dict[str, dict[str, Any]], list[tuple[datetime, datetime, str]]]:
        """Batch-resolve cached period rollups; return hits and missing window triples."""
        cache_keys: list[str] = []
        windows_by_key: dict[str, tuple[datetime, datetime]] = {}
        for local_period_start, local_period_end in period_windows:
            cache_key = cache_key_for_window(local_period_start, local_period_end)
            cache_keys.append(cache_key)
            windows_by_key[cache_key] = (local_period_start, local_period_end)

        rows_by_key = self._period_rollup_rows_by_cache_keys(
            label,
            cache_keys,
            fetch_by_keys=fetch_by_keys,
            index_prefix=index_prefix,
        )
        rollups_by_cache_key: dict[str, dict[str, Any]] = {}
        missing_period_windows: list[tuple[datetime, datetime, str]] = []
        for cache_key in cache_keys:
            row = rows_by_key.get(cache_key)
            if row is None:
                local_period_start, local_period_end = windows_by_key[cache_key]
                missing_period_windows.append((local_period_start, local_period_end, cache_key))
                continue
            rollups_by_cache_key[cache_key] = serialize_row(row)
        return rollups_by_cache_key, missing_period_windows
