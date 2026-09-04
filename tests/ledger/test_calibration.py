"""Does confidence actually correlate with correctness?

CLAUDE.md's stage 4 gate says to check this against the gold set.
SPEC-DECISIONS.md wins on contradiction and says gold is tuned on never and
scored once at the end. Both hold if the check runs against a development set
written for the purpose, which is what data/dev/calibration.json is.

Running this found two real defects in the scoring rather than a bad threshold:
vague terms were matched as substrings, so "refurbished" tripped the "ish" rule
and dragged a perfectly clear instruction under the bar; and the multi-unit
ambiguity penalty fired on "up to 3 reams, budget 1500", where a total reading
is the only natural one. Both are fixed, and both are what a calibration set is
for.
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


def weakest(instruction: str) -> float:
    proposal = build_ledger(
        instruction, EXTRACT.extract(instruction), created_at=NOW, threshold=0.0
    )
    return min(proposal.confidence.get(name, 0.0) for name in REQUIRED_FIELDS)


SCORED = [(case["instruction"], case["verdict"], weakest(case["instruction"])) for case in CASES]
USABLE = [score for _, verdict, score in SCORED if verdict == "USABLE"]
ASK = [score for _, verdict, score in SCORED if verdict == "ASK"]


def test_the_calibration_set_is_balanced_enough_to_mean_something() -> None:
    assert len(CASES) >= 40
    assert len(USABLE) >= 15 and len(ASK) >= 15


def test_confidence_separates_the_two_classes() -> None:
    """The correlation the gate asks for, stated as a gap rather than a coefficient."""
    assert min(USABLE) > max(ASK), (
        f"classes overlap: lowest usable {min(USABLE):.2f} <= highest ask {max(ASK):.2f}"
    )


@pytest.mark.parametrize(
    ("instruction", "verdict", "score"), SCORED, ids=[c["instruction"][:40] for c in CASES]
)
def test_every_case_falls_on_the_right_side_of_the_threshold(
    instruction: str, verdict: str, score: float
) -> None:
    accepted = score >= DEFAULT_THRESHOLD
    assert accepted == (verdict == "USABLE"), (
        f"{instruction!r} scored {score:.2f}, expected {verdict}"
    )


def test_the_threshold_sits_inside_the_separating_band() -> None:
    """0.85 was invented. The data says it is inside the valid range, not that it is special.

    Any threshold above the highest ASK score and at or below the lowest USABLE
    score classifies this set perfectly. 0.85 is one of many, chosen to sit near
    the conservative end, because asking one time too many costs a question and
    accepting one time too many costs money.
    """
    assert max(ASK) < DEFAULT_THRESHOLD <= min(USABLE)


def test_a_clearly_stated_instruction_scores_at_the_top() -> None:
    assert weakest("Buy me a pair of running shoes, budget 5000 rupees.") == 1.0


def test_the_word_boundary_fix_holds() -> None:
    """ "refurbished" contains "ish". Substring matching cost this case 0.55."""
    assert weakest("Buy a refurbished laptop under 40000.") == 1.0


def test_an_upper_bounded_count_is_not_treated_as_ambiguous() -> None:
    """ "up to 3 reams, budget 1500" reads as a total to any English speaker."""
    assert weakest("Get me up to 3 reams of paper, budget 1500.") == 1.0


def test_an_exact_count_with_an_unmarked_budget_still_is() -> None:
    assert weakest("Get me 3 shirts, budget 2000.") < DEFAULT_THRESHOLD
