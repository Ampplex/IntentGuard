"""No float in the money path -- enforced, not asserted in prose.

Three checks, because the invariant has three ways to be broken: a float in the
money module, a float typed onto a money field, and a float written into a
fixture.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import re
import typing
from pathlib import Path

import pytest
from pydantic import BaseModel

import intentguard.core as core_pkg

CORE_DIR = Path(core_pkg.__file__).parent
TESTS_DIR = Path(__file__).parent

# Floats are legitimate for scores and durations. Money is never in this set.
FLOAT_ALLOWED_FIELDS = {"confidence", "score", "weight", "similarity"}


def _core_modules():
    for info in pkgutil.iter_modules([str(CORE_DIR)]):
        yield importlib.import_module(f"{core_pkg.__name__}.{info.name}")


def _models():
    seen = {}
    for module in _core_modules():
        for name, obj in vars(module).items():
            if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel:
                seen[obj] = name
    return seen


def _mentions_float(annotation) -> bool:
    if annotation is float:
        return True
    return any(_mentions_float(arg) for arg in typing.get_args(annotation))


def test_money_module_never_references_the_float_builtin() -> None:
    """Parsed, not grepped, so prose and comments cannot trip or hide it."""
    tree = ast.parse((CORE_DIR / "money.py").read_text(encoding="utf-8"))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "float" not in names | attrs

    literals = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, float)
    ]
    assert not literals, "float literal in the money module"


def test_no_money_field_is_typed_as_a_float() -> None:
    offenders = []
    for model, name in _models().items():
        for field_name, field in model.model_fields.items():
            if (
                _mentions_float(field.annotation)
                and field_name not in FLOAT_ALLOWED_FIELDS
                and not field_name.endswith("_ms")
            ):
                offenders.append(f"{name}.{field_name}")
    assert not offenders, f"float typed onto non-score fields: {offenders}"


def test_every_paise_field_is_an_integer() -> None:
    for model, name in _models().items():
        for field_name, field in model.model_fields.items():
            if field_name.endswith("_paise"):
                assert field.annotation is int, f"{name}.{field_name} is not int"


@pytest.mark.parametrize("path", sorted(TESTS_DIR.glob("*.py")), ids=lambda p: p.name)
def test_fixtures_never_write_money_as_a_decimal(path: Path) -> None:
    """The gate says no float in the money path including fixtures."""
    source = path.read_text(encoding="utf-8")
    bad = re.findall(r"(?:_paise|from_rupees)\s*[=(]\s*-?\d+\.\d", source)
    assert not bad, f"{path.name} writes money as a decimal: {bad}"
