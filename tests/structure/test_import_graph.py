"""Import-graph walker.

CLAUDE.md makes this a stage 2 gate, where it will assert that policy/ imports
nothing from semantic/, ledger/ or a model client. It is built here at stage 1
so the constraint is enforced from the first commit rather than discovered
later, and so stage 2 only has to add a rule rather than a mechanism.

Two rules now.

core/ depends on nothing but the standard library and pydantic. A core that
reaches for a database or an HTTP client is a core that has stopped being
schemas.

policy/ imports nothing from semantic/, ledger/ or any model client, and never
reads a clock. The first half is what CLAUDE.md asks for and proves the decision
cannot be argued with by a model. The second half matters just as much and the
original gate does not mention it: an engine that calls datetime.now() is not
deterministic either, it is just deterministic in a way you cannot test.
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


POLICY_MAY_NOT_IMPORT = {
    "semantic",
    "ledger",
    "gate",
    "payments",
    "merchant",
    "buyer",
    "bench",
    "audit",
    "metrics",
}

CLOCK_READERS = {
    ("datetime", "now"),
    ("datetime", "today"),
    ("datetime", "utcnow"),
    ("time", "time"),
}


def _policy_files():
    return sorted((SRC / "policy").rglob("*.py"))


def sibling_packages_reached(path: Path) -> set[str]:
    """Which intentguard subpackages this file imports, relative or absolute.

    Relative imports have to be resolved against the importing module's own
    package. Every import inside this codebase is written relatively, so a
    checker that only understood absolute imports would pass while policy/ was
    importing ledger/ on the line above it.
    """
    parts = list(path.relative_to(SRC.parent).with_suffix("").parts)
    package = parts[:-1]
    reached: set[str] = set()

    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        targets: list[list[str]] = []
        if isinstance(node, ast.Import):
            targets = [alias.name.split(".") for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                targets = [node.module.split(".")] if node.module else []
            else:
                base = package[: len(package) - (node.level - 1)]
                targets = [base + (node.module.split(".") if node.module else [])]

        for target in targets:
            if len(target) > 1 and target[0] == "intentguard":
                reached.add(target[1])
    return reached


@pytest.mark.parametrize("path", _policy_files(), ids=lambda p: p.name)
def test_policy_imports_no_sibling_package(path: Path) -> None:
    assert not sibling_packages_reached(path) & POLICY_MAY_NOT_IMPORT, path.name


def test_the_sibling_resolver_understands_relative_imports() -> None:
    """The checker above is worthless if it cannot see the imports actually used."""
    engine = SRC / "policy" / "engine.py"
    assert "core" in sibling_packages_reached(engine)


@pytest.mark.parametrize("path", _policy_files(), ids=lambda p: p.name)
def test_policy_touches_no_model_client(path: Path) -> None:
    assert not top_level_imports(path) & MODEL_CLIENTS, path.name


@pytest.mark.parametrize("path", _policy_files(), ids=lambda p: p.name)
def test_policy_never_reads_the_clock(path: Path) -> None:
    """now is a parameter. An engine that asks the OS what time it is is not testable."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            assert (node.value.id, node.attr) not in CLOCK_READERS, f"{path.name} reads the clock"


def test_the_policy_walker_found_files() -> None:
    assert _policy_files(), "the policy rules are vacuous if there are no policy files"


DATA_DIR = SRC.parent.parent / "data"
GOLD_DIR = DATA_DIR / "gold"


@pytest.mark.parametrize("path", sorted(GOLD_DIR.glob("*.py")), ids=lambda p: p.name)
def test_dataset_authoring_cannot_reach_the_implementation(path: Path) -> None:
    """A dataset's only value is independence from the code it judges.

    A labelling script that can import intentguard can be tuned against it,
    whether or not anyone meant to. Removing the possibility is cheaper than
    trusting the intention.
    """
    assert "intentguard" not in top_level_imports(path), path.name


def test_the_dataset_directories_were_actually_found() -> None:
    found = sorted(DATA_DIR.rglob("*.py"))
    assert found, "the dataset import rule is vacuous with no files"
    assert {p.parent.name for p in found} >= {"gold", "dev"}


def _metrics_files():
    return sorted((SRC / "metrics").rglob("*.py"))


@pytest.mark.parametrize("path", _metrics_files(), ids=lambda p: p.name)
def test_metrics_does_not_import_the_thing_it_measures(path: Path) -> None:
    """Measurement takes observations, not an engine.

    A metrics module that can call the engine can quietly re-run a case until the
    number looks better, and a reader cannot tell from the report that it did.
    Keeping it to pure functions over recorded outcomes removes the option.
    """
    assert "policy" not in sibling_packages_reached(path), path.name


@pytest.mark.parametrize("path", _metrics_files(), ids=lambda p: p.name)
def test_metrics_does_no_file_io(path: Path) -> None:
    """Reports are computed, not read from somewhere convenient."""
    forbidden = {"open", "requests", "sqlite3", "urllib"}
    assert not top_level_imports(path) & forbidden, path.name


def _merchant_files():
    return sorted((SRC / "merchant").rglob("*.py"))


@pytest.mark.parametrize("path", _merchant_files(), ids=lambda p: p.name)
def test_the_merchant_cannot_reach_the_mandate_or_the_engine(path: Path) -> None:
    """The untrusted side gets a projection, not the objects behind it.

    A merchant module that can import IntentLedger can read a ceiling out of one,
    and the bounded view becomes decorative. It may import core schemas it needs
    to build an offer, and nothing else.
    """
    forbidden = {"policy", "gate", "ledger", "audit", "payments", "metrics"}
    assert not sibling_packages_reached(path) & forbidden, path.name


@pytest.mark.parametrize("path", _merchant_files(), ids=lambda p: p.name)
def test_the_merchant_never_reads_the_ceiling(path: Path) -> None:
    """No merchant file accesses .max_total_paise on anything.

    Parsed rather than grepped, because projection.py explains at length why the
    ceiling is withheld and a text search cannot tell prose from a leak. The
    string is allowed to appear; reading the attribute is not.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    reads = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "max_total_paise"
    ]
    assert not reads, f"{path.name} reads the ceiling off an object"


def test_the_merchant_walker_found_files() -> None:
    assert _merchant_files()


def test_every_violation_code_has_something_that_raises_it() -> None:
    """A code nobody raises is a claim in a table with no behaviour behind it.

    This found three at the point it was written: OFFER_MALFORMED and
    UNMODELLED_FIELD had no producer because nothing accepted a raw wire payload,
    and LOW_CONFIDENCE had none because no check read the stored scores. All
    three were live gaps rather than spare vocabulary.
    """
    from intentguard.core import ViolationCode

    sources = {
        path: path.read_text(encoding="utf-8")
        for path in SRC.rglob("*.py")
        if path.name != "violations.py"
    }
    orphans = [
        code.name
        for code in ViolationCode
        if not any(f"ViolationCode.{code.name}" in text for text in sources.values())
    ]
    assert not orphans, f"codes defined but never raised: {orphans}"


def test_no_module_defines_the_confidence_threshold_twice() -> None:
    """One number, one home. Two copies drift and nobody notices which is live."""
    literal = "0.85"
    defining = [
        path.name
        for path in SRC.rglob("*.py")
        for line in path.read_text(encoding="utf-8").splitlines()
        if literal in line and "=" in line and not line.strip().startswith("#")
    ]
    assert defining == ["violations.py"], f"threshold defined in {defining}"


def _buyer_files():
    return sorted((SRC / "buyer").rglob("*.py"))


@pytest.mark.parametrize("path", _buyer_files(), ids=lambda p: p.name)
def test_negotiation_contains_no_unbounded_loop(path: Path) -> None:
    """The structural half of "terminates, always".

    A `while` with an exit condition is a promise that the condition is always
    eventually met, and an adversarial counterparty is exactly the thing that
    breaks such promises. A `for` over a fixed range is a proof instead: no
    merchant response can extend it.

    `while True` is refused outright; any other `while` is refused too, because
    reviewing which ones are safe is the work this test exists to avoid.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    loops = [node for node in ast.walk(tree) if isinstance(node, ast.While)]
    assert not loops, f"{path.name} uses a while loop in a negotiation path"


@pytest.mark.parametrize("path", _buyer_files(), ids=lambda p: p.name)
def test_the_buyer_does_not_reach_the_engine(path: Path) -> None:
    """The buyer is the user's agent, and the gate still does not trust it.

    A buyer that could call the engine could decide its own offer was acceptable,
    and the check that matters would be happening on the wrong side of the
    boundary.
    """
    forbidden = {"policy", "gate", "audit", "payments", "metrics"}
    assert not sibling_packages_reached(path) & forbidden, path.name


def test_the_buyer_walker_found_files() -> None:
    assert _buyer_files()
