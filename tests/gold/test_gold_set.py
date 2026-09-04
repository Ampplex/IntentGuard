"""The gold set is well formed and internally consistent.

This module deliberately does not import intentguard.policy. The stage 3 gate is
that the set exists and was labelled without running the engine, and a test file
that scored gold against the engine would quietly spend the one piece of
held-out evidence the project has.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from intentguard.core import IntentLedger, Offer, Outcome

CASES_PATH = Path(__file__).resolve().parents[2] / "data" / "gold" / "cases.json"

# Gold cases are written relative to an anchor rather than wall-clock time, so
# the TTL cases mean the same thing whenever they are run.
GOLD_EPOCH = datetime(2026, 9, 4, 10, 0, 0, tzinfo=UTC)

EXPECTED_KINDS = {
    "valid",
    "price",
    "hidden_cost",
    "recurrence",
    "addon",
    "quantity",
    "substitution",
    "currency",
    "emi",
    "discount",
    "shipping_upgrade",
    "bundle",
    "ambiguous_intent",
    "injection",
    "unmodelled",
    "total_mismatch",
    "negative_total",
    "condition",
    "category",
    "ledger_state",
    "exclusion",
}

CASES = json.loads(CASES_PATH.read_text(encoding="utf-8"))
BY_ID = {case["case_id"]: case for case in CASES}


def ledger_for(case: dict) -> IntentLedger:
    return IntentLedger.model_validate({**case["ledger"], "created_at": GOLD_EPOCH})


def now_for(case: dict) -> datetime:
    return GOLD_EPOCH + timedelta(seconds=case["now_offset_seconds"])


def test_there_are_exactly_one_hundred_cases() -> None:
    assert len(CASES) == 100


def test_case_ids_are_unique() -> None:
    assert len({case["case_id"] for case in CASES}) == 100


def test_every_label_is_a_real_outcome() -> None:
    for case in CASES:
        assert case["label"] in {o.value for o in Outcome}, case["case_id"]


def test_every_kind_is_represented() -> None:
    assert {case["kind"] for case in CASES} == EXPECTED_KINDS


def test_all_three_outcomes_are_represented_in_useful_numbers() -> None:
    counts = {outcome.value: 0 for outcome in Outcome}
    for case in CASES:
        counts[case["label"]] += 1
    for outcome, count in counts.items():
        assert count >= 10, f"only {count} {outcome} cases is too thin to measure"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["case_id"])
def test_every_mandate_is_a_valid_ledger(case: dict) -> None:
    ledger_for(case)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["case_id"])
def test_every_offer_parses_unless_it_is_meant_not_to(case: dict) -> None:
    if case["offer_carries_unknown_field"]:
        with pytest.raises(ValidationError) as caught:
            Offer.model_validate(case["offer"])
        assert any(error["type"] == "extra_forbidden" for error in caught.value.errors())
    else:
        Offer.model_validate(case["offer"])


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["case_id"])
def test_money_is_always_whole_paise(case: dict) -> None:
    offer = case["offer"]
    amounts = [offer["total_paise"], case["ledger"]["hard"]["max_total_paise"]]
    amounts += [item["amount_paise"] for item in offer["line_items"]]
    amounts += [charge["amount_paise"] for charge in offer["recurring"]]
    if offer["emi"]:
        amounts.append(offer["emi"]["installment_paise"])
    for amount in amounts:
        assert isinstance(amount, int) and not isinstance(amount, bool), case["case_id"]


def test_unmodelled_cases_all_escalate() -> None:
    """A field with no slot cannot be judged, so it is asked about."""
    for case in CASES:
        if case["kind"] == "unmodelled":
            assert case["label"] == "ESCALATE", case["case_id"]


def test_ambiguous_intent_cases_all_escalate() -> None:
    for case in CASES:
        if case["kind"] == "ambiguous_intent":
            assert case["label"] == "ESCALATE", case["case_id"]


def test_injection_cases_have_a_twin_with_the_same_label() -> None:
    """The whole injection experiment is this equality. Without twins it proves nothing."""
    injections = [case for case in CASES if case["kind"] == "injection"]
    assert injections
    for case in injections:
        twin_id = case["injection_of"]
        assert twin_id in BY_ID, case["case_id"]
        twin = BY_ID[twin_id]
        assert case["label"] == twin["label"], f"{case['case_id']} diverges from {twin_id}"
        assert case["offer"]["raw_description"], "an injection case needs hostile text"
        assert twin["kind"] != "injection"


def test_injection_covers_both_directions() -> None:
    """Injection that only appears on blocked cases cannot show it does not flip an allow."""
    labels = {BY_ID[c["injection_of"]]["label"] for c in CASES if c["kind"] == "injection"}
    assert {"ALLOW", "BLOCK"} <= labels


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["case_id"])
def test_every_case_carries_a_rationale(case: dict) -> None:
    assert len(case["rationale"]) > 40, "a one-word rationale is not a label from the prose"


def test_flagged_cases_explain_themselves() -> None:
    for case in CASES:
        if case["ambiguous"]:
            assert case["ambiguity_note"], case["case_id"]
        if case["schema_gap"]:
            assert len(case["schema_gap"]) > 20, case["case_id"]


def test_the_review_file_is_in_step_with_the_cases() -> None:
    review = (CASES_PATH.parent / "REVIEW.md").read_text(encoding="utf-8")
    for case in CASES:
        assert case["case_id"] in review, f"{case['case_id']} missing from the review file"


def test_ttl_cases_actually_exercise_the_boundary() -> None:
    offsets = {c["case_id"]: (c["now_offset_seconds"], c["ledger"]["ttl_seconds"]) for c in CASES}
    assert any(now > ttl for now, ttl in offsets.values()), "no case is past its TTL"
    assert any(now < ttl for now, ttl in offsets.values()), "no case is inside its TTL"


def test_the_time_anchor_resolves() -> None:
    for case in CASES:
        assert now_for(case) >= GOLD_EPOCH
        assert ledger_for(case).created_at == GOLD_EPOCH
