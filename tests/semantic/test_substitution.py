"""Substitution detection, and the rule that it may never block.

The stage 7 gate in CLAUDE.md says the gold substitution cases should be
classified correctly. SPEC-DECISIONS.md holds gold out until the final run and
wins on contradiction, so the threshold is derived from
data/dev/substitutions.json instead and gold stays untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from intentguard.core import Outcome, ViolationCode
from intentguard.semantic import (
    DEFAULT_SUBSTITUTION_THRESHOLD,
    assess_substitution,
    product_match_score,
)

PAIRS = json.loads(
    (Path(__file__).resolve().parents[2] / "data" / "dev" / "substitutions.json").read_text(
        encoding="utf-8"
    )
)


def _flagged(case: dict) -> bool:
    """What the detector actually concludes, not what one component scores.

    Coverage is half of it. The other half is whether the description names
    something else on the merchant's shelf, and a calibration measuring only the
    first half reports the evasion pairs as missed swaps when they are caught.
    """
    return bool(
        assess_substitution(
            case["negotiated"], case["delivered"], alternatives=case["alternatives"]
        )
    )


SCORED = [
    (
        case["negotiated"],
        case["delivered"],
        case["verdict"],
        product_match_score(case["negotiated"], case["delivered"]),
        _flagged(case),
    )
    for case in PAIRS
]

# Two pairs the measure cannot place, and both are genuinely arguable: a listing
# that adds a model year and one that adds a capacity could each be a different
# SKU. They escalate, which costs a question rather than a wrong purchase.
KNOWN_OVER_CAUTIOUS = {
    ("Asics Gel-Contend 9", "Asics Gel-Contend 9 (2024)"),
    ("Laptop Backpack", "Laptop Backpack 25L"),
}


# --- the rule that matters ------------------------------------------------


def test_substitution_never_blocks() -> None:
    """A similarity score moving money is the thing this project argues against.

    The deterministic half of substitution -- an exact mismatch against a pinned
    product_ref -- does block, and lives in policy/. This half cannot.
    """
    for negotiated, delivered, *_ in SCORED:
        for violation in assess_substitution(negotiated, delivered):
            assert violation.outcome is Outcome.ESCALATE
            assert violation.outcome is not Outcome.BLOCK


def test_the_code_is_named_even_though_the_outcome_is_downgraded() -> None:
    """The code says what was noticed; the outcome says how well it is known."""
    violations = assess_substitution("Asics Gel-Contend 9", "Nike Revolution 7")
    assert violations[0].code is ViolationCode.PRODUCT_SUBSTITUTION
    assert violations[0].outcome is Outcome.ESCALATE


# --- calibration ----------------------------------------------------------


def test_no_swap_is_missed() -> None:
    """The direction that costs money. A missed swap is a different product bought."""
    missed = [(n, d) for n, d, v, _, flagged in SCORED if v == "DIFFERENT" and not flagged]
    assert missed == [], f"substitutions that would have passed: {missed}"


def test_over_caution_is_bounded_and_named() -> None:
    over = {(n, d) for n, d, v, _, flagged in SCORED if v == "SAME" and flagged}
    assert over == KNOWN_OVER_CAUTIOUS, f"unexplained escalations: {over - KNOWN_OVER_CAUTIOUS}"


def test_accuracy_on_the_calibration_set() -> None:
    correct = sum(1 for _, _, v, _, flagged in SCORED if flagged == (v == "DIFFERENT"))
    assert correct / len(SCORED) >= 0.90


# --- the measure ----------------------------------------------------------


@pytest.mark.parametrize(
    ("negotiated", "delivered"),
    [
        ("Midnight's Children", "Midnight's Children by Salman Rushdie"),
        ("Electric Kettle", "Electric Kettle, stainless steel"),
        ("boAt Airdopes 141", "boAt Airdopes 141 Bluetooth earbuds"),
        ("Lenovo IdeaPad Slim 3", "Lenovo IdeaPad Slim 3 laptop"),
    ],
)
def test_extra_description_costs_nothing(negotiated: str, delivered: str) -> None:
    """A retailer describing the same item more fully has not changed the item.

    A symmetric overlap punished exactly this, which is why the measure is
    coverage rather than similarity.
    """
    assert product_match_score(negotiated, delivered) == 1.0
    assert assess_substitution(negotiated, delivered) == []


@pytest.mark.parametrize(
    ("negotiated", "delivered"),
    [
        ("Electric Kettle", "Electric Kettle 1.5L Pro"),
        ("Sony WH-1000XM5", "Sony WH-1000XM4"),
        ("Asics Gel-Contend 9", "Asics Gel-Kayano 30"),
    ],
)
def test_an_added_or_altered_identifier_is_noticed(negotiated: str, delivered: str) -> None:
    """A model number, a capacity or a tier names a different thing to buy."""
    assert product_match_score(negotiated, delivered) < DEFAULT_SUBSTITUTION_THRESHOLD
    assert assess_substitution(negotiated, delivered)


def test_a_wholly_different_product_scores_nothing() -> None:
    assert product_match_score("Asics Gel-Contend 9", "Nike Revolution 7") == 0.0


def test_case_and_punctuation_are_not_a_substitution() -> None:
    assert product_match_score("Asics Gel-Contend 9", "ASICS GEL-CONTEND 9") == 1.0


def test_an_empty_description_is_not_judged() -> None:
    assert assess_substitution("", "Nike Revolution 7") == []
    assert assess_substitution("Asics Gel-Contend 9", "   ") == []
    assert product_match_score("", "anything") == 0.0


def test_a_custom_similarity_can_be_supplied() -> None:
    class AlwaysDifferent:
        def score(self, left: str, right: str) -> float:
            return 0.0

    assert assess_substitution("a shoe", "a shoe", similarity=AlwaysDifferent())


# --- what an untrusted merchant controls ----------------------------------


def test_a_very_long_description_cannot_inflate_gate_latency() -> None:
    """Product text comes from the merchant and nothing upstream bounds it.

    A two hundred thousand word title took twenty-three milliseconds to score,
    against a whole-decision budget measured in microseconds. No real product
    name approaches the cap.
    """
    import time

    huge = "word " * 200_000
    started = time.perf_counter()
    product_match_score("Asics Gel-Contend 9", huge)
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert elapsed_ms < 5.0, f"scoring took {elapsed_ms:.1f} ms"


def test_padding_with_the_agreed_name_does_not_hide_a_swap() -> None:
    """Repeating the agreed name around a different product is still caught."""
    for delivered in (
        "Asics Gel-Contend 9 Nike Revolution 7",
        "asics gel contend 9 -- actually Nike Revolution 7",
        "Asics Gel Contend 9 " * 20 + "Nike Revolution 7",
    ):
        assert assess_substitution("Asics Gel-Contend 9", delivered), delivered


def test_the_shelf_closes_the_evasion_coverage_cannot_see() -> None:
    """This was a pinned known miss, and it is now caught.

    Appending another product's name without any digit keeps coverage at one,
    because everything agreed really is still in the text. Coverage alone cannot
    tell that the description now also describes something else. Knowing what
    else the merchant sells can.
    """
    evasion = "Asics Gel-Contend 9 replacement, Nike Revolution"
    assert product_match_score("Asics Gel-Contend 9", evasion) == 1.0
    assert assess_substitution("Asics Gel-Contend 9", evasion) == [], "still invisible alone"

    caught = assess_substitution("Asics Gel-Contend 9", evasion, alternatives=["Nike Revolution 7"])
    assert caught
    assert "Nike Revolution 7" in caught[0].observed
    assert caught[0].outcome is Outcome.ESCALATE


def test_shared_brand_words_do_not_make_every_offer_suspicious() -> None:
    """The test is the alternative's distinctive words, not its whole name.

    "Asics Gel-Kayano 30" shares "asics" and "gel" with "Asics Gel-Contend 9",
    and those shared words say nothing about which shoe arrived. Comparing whole
    names would fire on every product from the same brand.
    """
    assert (
        assess_substitution(
            "Asics Gel-Contend 9",
            "Asics Gel-Contend 9, mesh upper",
            alternatives=["Asics Gel-Kayano 30", "Nike Revolution 7"],
        )
        == []
    )


def test_an_alternative_identical_to_the_agreed_product_is_ignored() -> None:
    """It has no distinctive words, so its presence cannot mean anything."""
    assert (
        assess_substitution(
            "Asics Gel-Contend 9",
            "Asics Gel-Contend 9",
            alternatives=["Asics Gel-Contend 9"],
        )
        == []
    )


def test_the_alternative_that_was_found_is_named_to_the_user() -> None:
    caught = assess_substitution(
        "boAt Airdopes 141", "boAt Airdopes 141 / boAt Rockerz", alternatives=["boAt Rockerz 255"]
    )
    assert "boAt Rockerz 255" in caught[0].explanation
