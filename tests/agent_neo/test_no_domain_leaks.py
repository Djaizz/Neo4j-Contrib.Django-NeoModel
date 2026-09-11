"""Fail the suite if public agent_neo tree re-introduces domain brand leakage."""


from __future__ import annotations

from pathlib import Path

import pytest


_SCAN_ROOTS: tuple[Path, ...] = (
    Path('agent_neo'),
    Path('tests/agent_neo'),
)

_SCAN_SUFFIXES: frozenset[str] = frozenset({
    '.py',
    '.md',
    '.cypher',
    '.yml',
    '.yaml',
    '.toml',
    '.txt',
    '.rst',
})

# Brand / prior-consumer tokens and renamed soft-domain identifiers.
# Do NOT ban bare ``facility_name`` — that remains the legacy Neo4j property.
_DENYLIST: tuple[str, ...] = (
    'honeywell',
    'forge_odb',
    'forge-odb',
    'hfcodb',
    'nvidia-voyager',
    'dana-odb',
    'dana_odb',
    'facility_operating',
    'facility_timezone',
)


def _iter_scannable_files() -> list[Path]:
    files: list[Path] = []
    for root in _SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob('*'):
            if not path.is_file():
                continue
            if path.suffix.lower() not in _SCAN_SUFFIXES:
                continue
            if path.name == 'test_no_domain_leaks.py':
                continue
            files.append(path)
    return sorted(files)


@pytest.mark.parametrize('path', _iter_scannable_files(), ids=lambda path: str(path))
def test_no_domain_brand_leaks(path: Path) -> None:
    text = path.read_text(encoding='utf-8')
    lowered = text.lower()
    hits = [token for token in _DENYLIST if token in lowered]
    assert not hits, f'{path} contains denied domain tokens: {hits}'
