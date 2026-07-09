"""Shared parallel-execution helpers for analytical KPI collection."""


from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any, LiteralString
import os

if TYPE_CHECKING:
    from agent_neo.analytical_product.populate_progress import PopulateProgress


__all__: tuple[LiteralString, ...] = (
    'DEFAULT_KPI_MAX_WORKERS',
    'DEFAULT_KPI_PARALLEL_ENABLED',
    'format_kpi_parallel_plan_clause',
    'kpi_parallel_enabled',
    'kpi_parallel_workers',
    'parallel_map_asset_rollups',
)


_FALSEY_ENV_VALUES = {'0', 'false', 'no', 'off'}
DEFAULT_KPI_PARALLEL_ENABLED = True


def _env_value(name: str, *, default: str = '') -> str:
    """Read ``AGENT_NEO_<name>`` with legacy ``FORGE_ODB_<name>`` fallback."""
    agent_value = os.environ.get(f'AGENT_NEO_{name}', '').strip()
    if agent_value:
        return agent_value
    legacy_value = os.environ.get(f'FORGE_ODB_{name}', '').strip()
    if legacy_value:
        return legacy_value
    return default


def _default_kpi_max_workers() -> int:
    return 32


DEFAULT_KPI_MAX_WORKERS = _default_kpi_max_workers()


def _kpi_parallel_env_var_name(layer_name: str | None) -> str:
    normalized_layer_name = ''.join(
        character if character.isalnum() else '_'
        for character in str(layer_name or '').strip().upper()
    ).strip('_')
    if not normalized_layer_name:
        return 'KPI_MAX_WORKERS'
    return f'KPI_MAX_WORKERS_{normalized_layer_name}'


def _configured_kpi_parallel_workers(
    *,
    layer_name: str | None,
    max_workers: int,
) -> int:
    for env_suffix in (_kpi_parallel_env_var_name(layer_name), 'KPI_MAX_WORKERS'):
        configured = _env_value(env_suffix)
        if not configured:
            continue
        try:
            return max(1, int(configured))
        except ValueError:
            continue
    return max(1, int(max_workers))


def kpi_parallel_enabled(*, default: bool = DEFAULT_KPI_PARALLEL_ENABLED) -> bool:
    """Return whether KPI parallel execution is enabled."""
    raw_value = _env_value('KPI_PARALLEL', default=str(int(default))).lower()
    return raw_value not in _FALSEY_ENV_VALUES


def kpi_parallel_workers(
    *,
    work_item_count: int,
    layer_name: str | None = None,
    parallel_enabled: bool = DEFAULT_KPI_PARALLEL_ENABLED,
    max_workers: int = DEFAULT_KPI_MAX_WORKERS,
) -> int:
    """Return a conservative worker count for KPI fan-out."""
    resolved_parallel_enabled = kpi_parallel_enabled(default=parallel_enabled)
    if work_item_count <= 1 or not resolved_parallel_enabled:
        return 1
    resolved = _configured_kpi_parallel_workers(layer_name=layer_name, max_workers=max_workers)
    return max(1, min(work_item_count, resolved))


def format_kpi_parallel_plan_clause(
    *,
    work_item_count: int,
    layer_name: str | None = None,
    parallel_enabled: bool = DEFAULT_KPI_PARALLEL_ENABLED,
    max_workers: int = DEFAULT_KPI_MAX_WORKERS,
) -> str:
    """Render parallel settings for electricity KPI plan lines."""
    if not kpi_parallel_enabled(default=parallel_enabled):
        return 'parallel=off'
    resolved_workers = kpi_parallel_workers(
        work_item_count=work_item_count,
        layer_name=layer_name,
        parallel_enabled=parallel_enabled,
        max_workers=max_workers,
    )
    if not layer_name:
        return f'parallel=on workers={resolved_workers:,}'
    return f'parallel=on workers[{layer_name}]={resolved_workers:,}'


def parallel_map_asset_rollups(
    *,
    asset_names: list[str],
    layer_name: str,
    compute_for_asset: Callable[[str], list[dict[str, Any]]],
    progress: PopulateProgress | None = None,
    progress_desc: str | None = None,
    max_workers: int = DEFAULT_KPI_MAX_WORKERS,
) -> list[dict[str, Any]]:
    """Fan out per-asset HVAC rollup work with conservative worker limits."""
    if not asset_names:
        return []
    resolved_progress_desc = progress_desc or layer_name.replace('_', ' ')
    resolved_workers = kpi_parallel_workers(
        work_item_count=len(asset_names),
        layer_name=layer_name,
        max_workers=max_workers,
    )
    if resolved_workers <= 1:
        rollups: list[dict[str, Any]] = []
        asset_iter = (
            progress.assets(asset_names, desc=resolved_progress_desc)
            if progress is not None
            else asset_names
        )
        for asset_name in asset_iter:
            rollups.extend(compute_for_asset(asset_name))
        return rollups

    rollups_by_asset: dict[str, list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(
        max_workers=resolved_workers,
        thread_name_prefix=layer_name.replace('_', '-')[:12] or 'hvac-rollup',
    ) as executor:
        futures = {
            executor.submit(compute_for_asset, asset_name): asset_name
            for asset_name in asset_names
        }
        completion_iter = as_completed(futures)
        if progress is not None:
            completion_iter = progress.iterate(
                completion_iter,
                desc=resolved_progress_desc,
                unit='asset',
                total=len(futures),
                leave=False,
                scope_desc=False,
            )
        for future in completion_iter:
            asset_name = futures[future]
            rollups_by_asset[asset_name] = future.result()
    return [
        rollup
        for asset_name in asset_names
        for rollup in rollups_by_asset.get(asset_name, [])
    ]
