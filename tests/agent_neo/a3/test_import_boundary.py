"""``agent_neo.a3`` is the storage-agnostic floor: it must import with no Django, neomodel
or Neo4j driver present, and its modules may import only the standard library and each other.
Both are enforced here rather than by convention, because the eventual package split depends
on them staying true."""


from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
A3_DIR = REPO_ROOT / "agent_neo" / "a3"

_MASK_STORAGE_AND_IMPORT_A3 = """
import sys
for name in ("django", "django_neomodel", "neomodel", "neo4j"):
    sys.modules[name] = None  # any import of these now raises ImportError
import agent_neo.a3 as a3
import agent_neo.a3.algebra, agent_neo.a3.operators, agent_neo.a3.product, agent_neo.a3.gates, agent_neo.a3.lattice, agent_neo.a3.bridge, agent_neo.a3.laws, agent_neo.a3.term
print("ok", len(a3.__all__))
"""


def test_a3_imports_without_any_storage_backend_installed() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", _MASK_STORAGE_AND_IMPORT_A3],
        cwd=REPO_ROOT,
        env={"PYTHONPATH": str(REPO_ROOT), "PATH": "", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.startswith("ok "), completed.stdout


def test_a3_modules_import_only_stdlib_and_a3() -> None:
    violations: list[str] = []
    for path in sorted(A3_DIR.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules = [node.module]
            else:
                continue
            for module in modules:
                top = module.split(".")[0]
                inside_a3 = module == "agent_neo.a3" or module.startswith("agent_neo.a3.")
                if top not in sys.stdlib_module_names and not inside_a3:
                    violations.append(f"{path.name}:{node.lineno}: {module}")
    assert not violations, "a3 may import only the stdlib and itself:\n" + "\n".join(violations)
