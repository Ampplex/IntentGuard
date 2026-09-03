"""Import-graph walker.

CLAUDE.md makes this a stage 2 gate, where it will assert that policy/ imports
nothing from semantic/, ledger/ or a model client. It is built here at stage 1
so the constraint is enforced from the first commit rather than discovered
later, and so stage 2 only has to add a rule rather than a mechanism.

At stage 1 there is one rule: core/ depends on nothing but the standard library
and pydantic. A core that reaches for a database or an HTTP client is a core
that has stopped being schemas.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

import intentguard

SRC = Path(intentguard.__file__).parent

MODEL_CLIENTS = {"anthropic", "openai", "sentence_transformers", "transformers", "torch"}


def top_level_imports(path: Path) -> set[str]:
    """Every absolute top-level module a file imports. Relative imports are internal."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def package_imports(package: str) -> dict[Path, set[str]]:
    directory = SRC / package
    return {path: top_level_imports(path) for path in sorted(directory.rglob("*.py"))}


def _core_files():
    return sorted((SRC / "core").rglob("*.py"))


@pytest.mark.parametrize("path", _core_files(), ids=lambda p: p.name)
def test_core_imports_only_stdlib_and_pydantic(path: Path) -> None:
    allowed = set(sys.stdlib_module_names) | {"pydantic", "intentguard"}
    assert top_level_imports(path) <= allowed, path.name


@pytest.mark.parametrize("path", _core_files(), ids=lambda p: p.name)
def test_core_touches_no_model_client(path: Path) -> None:
    assert not top_level_imports(path) & MODEL_CLIENTS, path.name


def test_the_walker_actually_sees_imports() -> None:
    """A test that always passes because it found nothing is not a test."""
    found = package_imports("core")
    assert any(imports for imports in found.values())
    assert "pydantic" in set().union(*found.values())
