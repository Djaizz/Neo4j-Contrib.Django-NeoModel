"""Tests for electricity KPI parallel execution helpers."""


from __future__ import annotations

import pytest

from agent_neo.analytical_product.kpi_parallel import (
    _default_kpi_max_workers,
    format_kpi_parallel_plan_clause,
    kpi_parallel_workers,
    parallel_map_asset_rollups,
)


class _DummyProgress:
    def __init__(self) -> None:
        self.asset_descs: list[str] = []
        self.iterate_descs: list[str] = []

    def assets(self, asset_names: list[str], *, desc: str):
        self.asset_descs.append(desc)
        for asset_name in asset_names:
            yield asset_name

    def iterate(self, iterable, *, desc: str, unit: str = 'it', total: int | None = None, leave: bool = False, use_tqdm: bool | None = None, scope_desc: bool = True):
        self.iterate_descs.append(desc)
        for item in iterable:
            yield item


def test_default_kpi_max_workers_returns_fixed_default_worker_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('agent_neo.analytical_product.kpi_parallel.os.cpu_count', lambda: 24)
    assert _default_kpi_max_workers() == 32

    monkeypatch.setattr('agent_neo.analytical_product.kpi_parallel.os.cpu_count', lambda: 6)
    assert _default_kpi_max_workers() == 32


def test_format_kpi_parallel_plan_clause_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('FORGE_ODB_KPI_PARALLEL', raising=False)
    assert format_kpi_parallel_plan_clause(work_item_count=328, parallel_enabled=False) == 'parallel=off'


def test_format_kpi_parallel_plan_clause_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('FORGE_ODB_KPI_PARALLEL', raising=False)
    monkeypatch.delenv('FORGE_ODB_KPI_MAX_WORKERS', raising=False)
    assert format_kpi_parallel_plan_clause(work_item_count=328, parallel_enabled=True, max_workers=6) == 'parallel=on workers=6'


def test_format_kpi_parallel_plan_clause_respects_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('FORGE_ODB_KPI_PARALLEL', '1')
    monkeypatch.setenv('FORGE_ODB_KPI_MAX_WORKERS', '5')
    assert format_kpi_parallel_plan_clause(work_item_count=328) == 'parallel=on workers=5'


def test_format_kpi_parallel_plan_clause_respects_layer_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('FORGE_ODB_KPI_MAX_WORKERS', raising=False)
    monkeypatch.setenv('FORGE_ODB_KPI_MAX_WORKERS_METER', '8')
    assert (
        format_kpi_parallel_plan_clause(work_item_count=328, layer_name='meter')
        == 'parallel=on workers[meter]=8'
    )


def test_kpi_parallel_workers_caps_to_work_items(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('FORGE_ODB_KPI_PARALLEL', raising=False)
    monkeypatch.delenv('FORGE_ODB_KPI_MAX_WORKERS', raising=False)
    assert kpi_parallel_workers(work_item_count=2, max_workers=8) == 2


def test_kpi_parallel_workers_prefers_layer_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('FORGE_ODB_KPI_MAX_WORKERS', '4')
    monkeypatch.setenv('FORGE_ODB_KPI_MAX_WORKERS_FLOOR', '7')
    assert kpi_parallel_workers(work_item_count=20, layer_name='floor') == 7


def test_kpi_parallel_workers_falls_back_from_invalid_layer_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('FORGE_ODB_KPI_MAX_WORKERS', '5')
    monkeypatch.setenv('FORGE_ODB_KPI_MAX_WORKERS_AHU', 'not-an-int')
    assert kpi_parallel_workers(work_item_count=20, layer_name='ahu') == 5


def test_parallel_map_asset_rollups_preserves_asset_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('FORGE_ODB_KPI_MAX_WORKERS_HVAC_AHU_SNAPSHOT', '4')

    def _compute(asset_name: str) -> list[dict[str, object]]:
        return [{'asset_name': asset_name, 'value': len(asset_name)}]

    rows = parallel_map_asset_rollups(
        asset_names=['9A_1F_AHU1', '9A_2F_AHU2', '9A_3F_AHU3'],
        layer_name='hvac_ahu_snapshot',
        compute_for_asset=_compute,
    )
    assert [row['asset_name'] for row in rows] == ['9A_1F_AHU1', '9A_2F_AHU2', '9A_3F_AHU3']


def test_parallel_map_asset_rollups_uses_progress_iterate_for_parallel_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('FORGE_ODB_KPI_MAX_WORKERS_HVAC_ZONE_COMFORT', '3')
    progress = _DummyProgress()

    def _compute(asset_name: str) -> list[dict[str, object]]:
        return [{'asset_name': asset_name}]

    rows = parallel_map_asset_rollups(
        asset_names=['9A_1F_VAV1', '9A_2F_VAV2', '9A_3F_VAV3'],
        layer_name='hvac_zone_comfort',
        compute_for_asset=_compute,
        progress=progress,
        progress_desc='HVAC daily zone comfort',
    )

    assert progress.iterate_descs == ['HVAC daily zone comfort']
    assert progress.asset_descs == []
    assert [row['asset_name'] for row in rows] == ['9A_1F_VAV1', '9A_2F_VAV2', '9A_3F_VAV3']


def test_parallel_map_asset_rollups_uses_progress_assets_for_serial_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('FORGE_ODB_KPI_PARALLEL', '0')
    progress = _DummyProgress()

    def _compute(asset_name: str) -> list[dict[str, object]]:
        return [{'asset_name': asset_name}]

    rows = parallel_map_asset_rollups(
        asset_names=['9A_AHU1', '9A_AHU2'],
        layer_name='hvac_co2_compliance',
        compute_for_asset=_compute,
        progress=progress,
        progress_desc='HVAC daily CO2 compliance',
    )

    assert progress.asset_descs == ['HVAC daily CO2 compliance']
    assert progress.iterate_descs == []
    assert [row['asset_name'] for row in rows] == ['9A_AHU1', '9A_AHU2']
