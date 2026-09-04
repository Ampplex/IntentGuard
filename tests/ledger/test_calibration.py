"""Does confidence correlate with correctness?

CLAUDE.md's stage 4 gate says to check this on gold. SPEC-DECISIONS.md wins on
contradiction and says gold is tuned on never and scored once at the end. Both
hold by calibrating on data/dev/calibration.json, written for the purpose and
under the same import ban as the gold set.

The first forty cases separated perfectly, which said more about the author than
the extractor. Twenty harder ones were added -- injection-bearing instructions,
abbreviated real phrasing, conditional ceilings, named products -- and the
classes now overlap, which is the honest picture.

The two error directions are not equivalent and are asserted separately.
Accepting an instruction that should have been questioned is a safety failure:
money moves on a mandate nobody confirmed. Questioning an instruction that was
usable is a recall cost: someone answers a question they did not need to. The
first is held at zero. The second is bounded and its causes are named.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from intentguard.ledger import RuleBasedExtractor, build_ledger
from intentguard.ledger.build import REQUIRED_FIELDS
from intentguard.ledger.confidence import DEFAULT_THRESHOLD

CASES = json.loads(
    (Path(__file__).resolve().parents[2] / "data" / "dev" / "calibration.json").read_text(
        encoding="utf-8"
    )
)
NOW = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
EXTRACT = RuleBasedExtractor()

# Instructions the offline extractor cannot categorise, because a bare product
# name needs a catalog and it has none. Confidence reports zero and the system
# asks, which is correct behaviour on a recall gap rather than a calibration
# failure. Pinned here so a new miss shows up as a change rather than a shrug.
KNOWN_RECALL_GAPS = {
    "Buy the Asics Gel-Contend 9, under 5000.",
    "Order the Lenovo IdeaPad Slim 3 under 45000.",
    "Order something by Asics under 5000.",
}


def weakest(instruction: str) -> float:
    proposal = build_ledger(
        instruction, EXTRACT.extract(instruction), created_at=NOW, threshold=0.0
    )
    return min(proposal.confidence.get(name, 0.0) for name in REQUIRED_FIELDS)


SCORED = [(case["instruction"], case["verdict"], weakest(case["instruction"])) for case in CASES]
CONFIDENTLY_WRONG = [(i, s) for i, v, s in SCORED if v == "ASK" and s >= DEFAULT_THRESHOLD]
CAUTIOUSLY_WRONG = [(i, s) for i, v, s in SCORED if v == "USABLE" and s < DEFAULT_THRESHOLD]


def test_the_set_is_large_and_balanced_enough_to_mean_something() -> None:
    assert len(CASES) >= 60
    verdicts = [case["verdict"] for case in CASES]
    assert verdicts.count("USABLE") >= 25 and verdicts.count("ASK") >= 20


def test_nothing_is_confidently_wrong() -> None:
    """The safety assertion. An accepted mandate is one money can move against.

    This is held at zero rather than at a rate. A single case here is a mandate
    activated from an instruction that did not support one.
    """
    assert CONFIDENTLY_WRONG == [], (
        "instructions accepted that should have been questioned: "
        + "; ".join(f"{text!r} at {score:.2f}" for text, score in CONFIDENTLY_WRONG)
    )


def test_injected_instructions_are_never_confidently_accepted_on_a_false_number() -> None:
    """Injection may cost a question. It may not buy a mandate."""
    for instruction, verdict, score in SCORED:
        if "SYSTEM" in instruction or "Ignore all previous" in instruction:
            assert not (verdict == "ASK" and score >= DEFAULT_THRESHOLD), instruction


def test_caution_is_bounded_and_every_instance_is_accounted_for() -> None:
    """Recall failures are tolerable, unexplained ones are not."""
    unexplained = [text for text, _ in CAUTIOUSLY_WRONG if text not in KNOWN_RECALL_GAPS]
    assert unexplained == [], (
        f"new recall gaps, investigate rather than widen the list: {unexplained}"
    )
    assert len(CAUTIOUSLY_WRONG) <= 6


def test_accuracy_holds_on_the_harder_set() -> None:
    wrong = len(CONFIDENTLY_WRONG) + len(CAUTIOUSLY_WRONG)
    assert (len(SCORED) - wrong) / len(SCORED) >= 0.90


def test_confidence_still_ranks_the_classes_apart_on_average() -> None:
    """Not separation any more, but the signal has to point the right way."""
    usable = [s for _, v, s in SCORED if v == "USABLE"]
    ask = [s for _, v, s in SCORED if v == "ASK"]
    assert sum(usable) / len(usable) - sum(ask) / len(ask) > 0.5


def test_the_threshold_is_above_every_case_that_must_be_questioned() -> None:
    """0.85 was invented. What the data supports is a floor, not that exact value.

    Every ASK case scores below it, so it is high enough. Lowering it below the
    highest ASK score would start accepting mandates nobody confirmed.
    """
    ask_scores = [s for _, v, s in SCORED if v == "ASK"]
    assert max(ask_scores) < DEFAULT_THRESHOLD, (
        f"threshold {DEFAULT_THRESHOLD} would accept an ASK case scoring {max(ask_scores):.2f}"
    )


@pytest.mark.parametrize(
    ("instruction", "verdict", "score"),
    [row for row in SCORED if row[0] not in KNOWN_RECALL_GAPS],
    ids=lambda value: value[:38] if isinstance(value, str) else str(value),
)
def test_each_case_lands_correctly(instruction: str, verdict: str, score: float) -> None:
    assert (score >= DEFAULT_THRESHOLD) == (verdict == "USABLE"), (
        f"{instruction!r} scored {score:.2f}, expected {verdict}"
    )
