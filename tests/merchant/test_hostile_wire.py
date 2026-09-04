"""Hostile quotes, over the wire, caught on arrival.

The merchant emits a plain dictionary. Nothing here constructs a valid Offer and
hands it to the engine: the payload is serialised, parsed, and only then judged,
which is the only way a forbidden key can be part of the test at all.

This is also the first point where the whole path runs together: instruction ->
extraction -> mandate -> bounded projection -> merchant quote -> gate -> audit.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from intentguard.audit import AuditLog
from intentguard.core import Offer, Outcome, ViolationCode
from intentguard.gate import run_gate
from intentguard.ledger import RuleBasedExtractor, build_ledger
from intentguard.merchant import Hostility, MerchantAgent, project

NOW = datetime(2026, 9, 4, 10, 5, tzinfo=UTC)
CREATED = NOW - timedelta(minutes=5)
# Sized so that each hostile behaviour is genuinely the cause of its block.
# The cheapest matching shoe is Rs 4,100; a looser ceiling would let hidden
# shipping through and the test would pass for the wrong reason.
INSTRUCTION = "Buy me a pair of new running shoes, budget 4300 rupees. No subscriptions."


def mandate():
    extractor = RuleBasedExtractor()
    proposal = build_ledger(INSTRUCTION, extractor.extract(INSTRUCTION), created_at=CREATED)
    assert proposal.ledger is not None, "the fixture instruction must be extractable"
    return proposal.ledger


def over_the_wire(payload: dict) -> dict:
    """Round-trip through JSON, because that is what actually happens."""
    return json.loads(json.dumps(payload))


def quote(hostility: Hostility) -> dict:
    ledger = mandate()
    payload = MerchantAgent(hostility).quote(project(ledger))
    assert payload is not None
    return over_the_wire(payload)


def judge(payload: dict, ledger=None):
    ledger = ledger or mandate()
    return run_gate(ledger, Offer.model_validate(payload), now=NOW)


def test_an_honest_merchant_gets_through() -> None:
    """The case that matters most. A gate that blocks everything is useless."""
    decision, _ = judge(quote(Hostility.NONE))
    assert decision.decision is Outcome.ALLOW
    assert decision.violations == []


@pytest.mark.parametrize(
    ("hostility", "expected_code"),
    [
        (Hostility.HIDDEN_SHIPPING, ViolationCode.TOTAL_EXCEEDS_MAX),
        (Hostility.TRIAL_SUBSCRIPTION, ViolationCode.RECURRING_NOT_AUTHORIZED),
        (Hostility.PAID_ADDON, ViolationCode.ADDON_NOT_AUTHORIZED),
        (Hostility.CURRENCY_SWAP, ViolationCode.CURRENCY_MISMATCH),
        (Hostility.QUANTITY_INFLATION, ViolationCode.QUANTITY_MISMATCH),
        (Hostility.TOTAL_MISMATCH, ViolationCode.TOTAL_MISMATCH),
    ],
    ids=lambda value: value.value if hasattr(value, "value") else str(value),
)
def test_hostile_quotes_are_blocked_on_arrival(hostility, expected_code) -> None:
    decision, record = judge(quote(hostility))
    assert decision.decision is Outcome.BLOCK
    assert expected_code in {v.code for v in decision.violations}
    assert record.decision is Outcome.BLOCK


def test_an_unknown_field_cannot_be_constructed_away() -> None:
    """The reason quotes are dictionaries. A fixture building an Offer could not do this."""
    payload = quote(Hostility.UNMODELLED_FIELD)
    assert payload["loyalty_lock_in_months"] == 12
    with pytest.raises(ValidationError) as caught:
        Offer.model_validate(payload)
    assert any(error["type"] == "extra_forbidden" for error in caught.value.errors())


def test_injection_arrives_intact_and_changes_nothing() -> None:
    """The description carries hostile text across the wire and the decision holds.

    Stated precisely: nothing reads raw_description today, so this shows the text
    survives transport and the deterministic path ignores it. It becomes evidence
    about a model only once a model reads that field, at stage 7.
    """
    clean, _ = judge(quote(Hostility.NONE))
    injected_payload = quote(Hostility.INJECTION)
    assert "decision=ALLOW" in injected_payload["raw_description"]
    injected, _ = judge(injected_payload)
    assert injected.decision is clean.decision
    assert [v.code for v in injected.violations] == [v.code for v in clean.violations]


def test_a_substitution_is_caught_only_when_a_product_was_named() -> None:
    """Brand preference alone must not block; a pinned product must."""
    loose = "Buy running shoes under 5000, I like Asics."
    pinned = "Buy the Asics Gel-Contend 9, under 5000."
    extractor = RuleBasedExtractor()

    loose_ledger = build_ledger(loose, extractor.extract(loose), created_at=CREATED).ledger
    swapped = over_the_wire(MerchantAgent(Hostility.SUBSTITUTION).quote(project(loose_ledger)))
    decision, _ = judge(swapped, loose_ledger)
    assert ViolationCode.PRODUCT_SUBSTITUTION not in {v.code for v in decision.violations}

    pinned_extract = extractor.extract(pinned)
    assert pinned_extract.product_ref, "the instruction names a product"


def test_an_excluded_material_is_caught() -> None:
    instruction = "Buy boots under 6000, nothing in leather."
    extractor = RuleBasedExtractor()
    ledger = build_ledger(instruction, extractor.extract(instruction), created_at=CREATED).ledger
    payload = over_the_wire(MerchantAgent(Hostility.EXCLUDED_MATERIAL).quote(project(ledger)))
    decision, _ = judge(payload, ledger)
    assert ViolationCode.EXCLUDED_ITEM in {v.code for v in decision.violations}


def test_the_merchant_cannot_price_to_a_ceiling_it_never_saw() -> None:
    """The reason the ceiling is withheld, stated as a test.

    The same merchant, quoting against two mandates that differ only in budget,
    quotes the same price. A merchant that could see the ceiling would quote just
    under each one.
    """
    from intentguard.core import HardConstraints, from_rupees

    def priced_for(rupees: int) -> int:
        ledger = mandate()
        hard = HardConstraints.model_validate(
            {**ledger.hard.model_dump(), "max_total_paise": from_rupees(rupees)}
        )
        payload = MerchantAgent().quote(project(ledger.model_copy(update={"hard": hard})))
        return payload["total_paise"]

    assert priced_for(5000) == priced_for(500_000)


def test_every_hostile_mode_is_recorded_in_the_audit_trail(tmp_path) -> None:
    """A blocked transaction has to be explainable afterwards, not just refused."""
    log = AuditLog(tmp_path / "audit.jsonl")
    ledger = mandate()
    for hostility in Hostility:
        payload = MerchantAgent(hostility).quote(project(ledger))
        if hostility is Hostility.UNMODELLED_FIELD:
            continue  # never parses, so the gate records it at stage 8's boundary
        run_gate(ledger, Offer.model_validate(over_the_wire(payload)), now=NOW, log=log)
    assert len(log) == len(Hostility) - 1
    assert log.verify_chain() is None
