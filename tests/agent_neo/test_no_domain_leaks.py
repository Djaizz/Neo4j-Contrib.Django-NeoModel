"""Keep the public tree free of any one consumer's identity and private references.

``agent_neo`` is extracted from, and shared with, applications that are not public.
These checks keep what those applications are called — and what their private
design documents contain — out of this repository. None of them names a consumer:
a public list of names to avoid would itself publish those names.

1. **Private denylist.** Brand, customer, site and consumer-namespace tokens live
   outside this repository. Point ``AGENT_NEO_PRIVATE_DENYLIST`` at a file of them,
   or put one at ``~/.config/agent_neo/private-denylist.txt``. One Python regex per
   line, matched case-insensitively; blank lines and ``#`` comments are ignored.
   With neither present the check is *skipped with a reason*, never passed.
2. **Fingerprint shapes.** Requirement-ID shapes (``WORD-WORD-WORD``), ADR-ID
   shapes (``ABC-1234``) and design-element citations (``(E<n>/E<m>)``) are how a
   private design corpus gets cited.
3. **Dangling pointers.** Every ``*.md`` path a shipped file cites must exist here,
   and every ``_private`` name it cites in backticks must be defined in
   ``agent_neo`` — a pointer into someone else's repository is a leak no keyword
   list catches.
4. **Import boundary.** ``agent_neo`` imports only the standard library, its
   declared third-party dependencies, and itself.
"""


from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_TEXT_SUFFIXES = frozenset({
    '.py', '.md', '.cypher', '.yml', '.yaml', '.toml', '.txt', '.rst', '.cfg', '.ini', '.json',
})
_SHIPPED_SUFFIXES = frozenset({'.py', '.md', '.cypher'})

_PRIVATE_DENYLIST_ENV = 'AGENT_NEO_PRIVATE_DENYLIST'
_PRIVATE_DENYLIST_DEFAULT = Path.home() / '.config' / 'agent_neo' / 'private-denylist.txt'

_REQUIREMENT_ID_SHAPE = re.compile(r'\b[A-Z]{3,}(?:-[A-Z0-9]{2,}){2,}\b')
_ADR_ID_SHAPE = re.compile(r'\b[A-Z]{3,}-\d{4}\b')
_DESIGN_ELEMENT_SHAPE = re.compile(r'\(E\d{1,2}\b(?:\s*[/+,]\s*E\d{1,2}\b)*|\bE\d{1,2}\s*[/+]\s*E\d{1,2}\b')

_CITED_PRIVATE_NAME = re.compile(r'``(_[A-Za-z][A-Za-z0-9_]*)``|(?<!`)`(_[A-Za-z][A-Za-z0-9_]*)`(?!`)')
_CITED_MD_PATH = re.compile(r'[\w.!/-]*[\w-]+\.md\b')

#: Private names this package deliberately cites from *other* libraries.
_EXTERNAL_PRIVATE_NAMES = frozenset({
    '_zoneinfo',  # CPython's C accelerator module, named in the tz-coercion rationale
    '_install_node',  # neomodel internals wrapped by the label-install precheck
    '_install_relationship',
})

#: Third-party top-level packages ``agent_neo`` may import. Adding one is a
#: dependency decision, which is exactly why it has to be made here, on purpose.
_ALLOWED_THIRD_PARTY = frozenset({
    'agent_neo',
    'colorama',
    'django',
    'django_neomodel',
    'drf_spectacular',
    'neo4j',
    'neomodel',
    'rest_framework',
    'tqdm',
})


@cache
def _tracked_text_files() -> tuple[Path, ...]:
    """Every tracked text file — or, outside a git checkout, the package trees."""
    try:
        listed = subprocess.run(
            ['git', 'ls-files'],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        candidates = [REPO_ROOT / name for name in listed]
    except (OSError, subprocess.CalledProcessError):
        candidates = [
            path
            for top in ('agent_neo', 'tests', 'django_neomodel')
            for path in (REPO_ROOT / top).rglob('*')
        ]
    files = tuple(
        path for path in candidates
        if path.is_file() and path.suffix.lower() in _TEXT_SUFFIXES
    )
    assert files, f'no files found to scan under {REPO_ROOT} — the guard would pass vacuously'
    return files


def _shipped_files() -> tuple[Path, ...]:
    return tuple(
        path for path in _tracked_text_files()
        if path.suffix in _SHIPPED_SUFFIXES and path.relative_to(REPO_ROOT).parts[0] == 'agent_neo'
    )


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _private_denylist() -> list[re.Pattern[str]] | None:
    configured = os.environ.get(_PRIVATE_DENYLIST_ENV)
    source = Path(configured).expanduser() if configured else _PRIVATE_DENYLIST_DEFAULT
    if not source.is_file():
        if configured:
            pytest.fail(f'{_PRIVATE_DENYLIST_ENV} points at {source}, which does not exist')
        return None
    patterns = [
        line.strip()
        for line in source.read_text(encoding='utf-8').splitlines()
        if line.strip() and not line.lstrip().startswith('#')
    ]
    return [re.compile(pattern, re.IGNORECASE) for pattern in patterns]


def test_no_private_denylist_token_appears() -> None:
    patterns = _private_denylist()
    if patterns is None:
        pytest.skip(
            f'no private denylist: set {_PRIVATE_DENYLIST_ENV} or create '
            f'{_PRIVATE_DENYLIST_DEFAULT} to enable this check',
        )
    assert patterns, 'the private denylist is empty'
    hits = [
        f'{_relative(path)}:{line_number}: /{pattern.pattern}/'
        for path in _tracked_text_files()
        for line_number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1)
        for pattern in patterns
        if pattern.search(line)
    ]
    assert not hits, 'private tokens in the public tree:\n' + '\n'.join(hits)


def test_no_design_corpus_citation_shapes_in_shipped_files() -> None:
    hits = [
        f'{_relative(path)}:{line_number}: {match.group()}'
        for path in _shipped_files()
        for line_number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1)
        for shape in (_REQUIREMENT_ID_SHAPE, _ADR_ID_SHAPE, _DESIGN_ELEMENT_SHAPE)
        for match in shape.finditer(line)
    ]
    assert not hits, 'citations of an external design corpus:\n' + '\n'.join(hits)


def _names_defined_in_agent_neo() -> set[str]:
    names: set[str] = set()
    for path in _shipped_files():
        if path.suffix != '.py':
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            for attribute in ('name', 'id', 'attr', 'arg'):
                value = getattr(node, attribute, None)
                if isinstance(value, str):
                    names.add(value)
    return names


def test_cited_private_names_are_defined_here() -> None:
    defined = _names_defined_in_agent_neo() | _EXTERNAL_PRIVATE_NAMES
    dangling = []
    for path in _shipped_files():
        for line_number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            for match in _CITED_PRIVATE_NAME.finditer(line):
                name = match.group(1) or match.group(2)
                if name not in defined and not name.startswith('__'):
                    dangling.append(f'{_relative(path)}:{line_number}: {name}')
    assert not dangling, 'cited names that are not defined in agent_neo:\n' + '\n'.join(dangling)


def test_cited_markdown_paths_exist_here() -> None:
    tracked = {_relative(path) for path in _tracked_text_files()}
    dangling = []
    for path in _shipped_files():
        here = PurePosixPath(_relative(path)).parent
        for line_number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            for match in _CITED_MD_PATH.finditer(line):
                cited = match.group().lstrip('./')
                resolvable = (
                    cited in tracked
                    or str(here / cited) in tracked
                    or any(name.endswith('/' + cited) for name in tracked)
                )
                if not resolvable:
                    dangling.append(f'{_relative(path)}:{line_number}: {match.group()}')
    assert not dangling, 'cited documents that do not exist in this repository:\n' + '\n'.join(dangling)


def test_agent_neo_imports_only_declared_packages() -> None:
    violations = []
    for path in _shipped_files():
        if path.suffix != '.py':
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            else:
                continue
            for module in modules:
                top_level = module.split('.')[0]
                if top_level not in sys.stdlib_module_names and top_level not in _ALLOWED_THIRD_PARTY:
                    violations.append(f'{_relative(path)}:{node.lineno}: {module}')
    assert not violations, 'imports outside the declared dependency set:\n' + '\n'.join(violations)
