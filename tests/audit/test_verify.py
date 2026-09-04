"""Verifying a receipt without trusting the system that issued it.

The point of a compliance receipt is that somebody else can check it. These
tests take the receipt, the offer, and nothing else: no service, no database, no
trust in the issuer.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from intentguard.audit import (
    AuditLog,
    ReceiptProblem,
    chain_head,
    find,
    verify_receipt,
    verify_trail,
)
from intentguard.core import LineItem, LineItemKind, Outcome, from_rupees
from intentguard.gate import issue_receipt, receive
from tests.fixtures import CREATED_AT, a_ledger, an_offer

NOW = CREATED_AT + timedelta(minutes=5)


def allowed(ledger=None, offer=None):
    ledger = ledger or a_ledger()
    offer = offer or an_offer()
    _, record = receive(ledger, offer.model_dump(mode="json"), now=NOW)
    return ledger, offer, record


def test_a_receipt_verifies_against_the_order_it_describes() -> None:
    ledger, offer, record = allowed()
    verdict = verify_receipt(issue_receipt(record), offer, ledger)
    assert verdict.valid
    assert verdict.problems == []


def test_a_receipt_does_not_verify_against_a_different_order() -> None:
    """The property that makes it evidence rather than a claim."""
    ledger, _, record = allowed()
    other = an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(9999), kind=LineItemKind.PRODUCT)
        ],
        total_paise=from_rupees(9999),
    )
    verdict = verify_receipt(issue_receipt(record), other, ledger)
    assert not verdict.valid
    assert ReceiptProblem.OFFER_DOES_NOT_MATCH in verdict.problems


def test_altering_a_single_paisa_breaks_verification() -> None:
    ledger, offer, record = allowed()
    tampered = offer.model_copy(update={"total_paise": offer.total_paise + 1})
    assert not verify_receipt(issue_receipt(record), tampered, ledger).valid


def test_altering_only_the_untrusted_description_breaks_verification() -> None:
    """The description is part of what the merchant put in front of the user.

    A receipt that survived edits to it would let a merchant show one thing at
    checkout and attest to another afterwards.
    """
    ledger, offer, record = allowed()
    reworded = offer.model_copy(update={"raw_description": "Actually, terms have changed."})
    assert not verify_receipt(issue_receipt(record), reworded, ledger).valid


def test_a_receipt_does_not_verify_against_a_different_mandate() -> None:
    ledger, offer, record = allowed()
    other_mandate = a_ledger(intent_id="int_someone_else")
    verdict = verify_receipt(issue_receipt(record), offer, other_mandate)
    assert ReceiptProblem.MANDATE_DOES_NOT_MATCH in verdict.problems


def test_the_mandate_is_optional_because_a_merchant_never_holds_one() -> None:
    """A merchant has the cart and the receipt, never the user's mandate."""
    _, offer, record = allowed()
    assert verify_receipt(issue_receipt(record), offer).valid


def test_a_receipt_names_what_was_actually_checked() -> None:
    """ "We checked everything" is worth nothing to whoever defends the charge."""
    _, _, record = allowed()
    receipt = issue_receipt(record)
    assert len(receipt.constraints_checked) >= 10
    assert {"totals", "recurrence", "currency", "exclusions"} <= set(receipt.constraints_checked)


def test_a_receipt_is_only_ever_issued_for_an_authorization() -> None:
    offer = an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(9000), kind=LineItemKind.PRODUCT)
        ],
        total_paise=from_rupees(9000),
    )
    decision, record = receive(a_ledger(), offer.model_dump(mode="json"), now=NOW)
    assert decision.decision is Outcome.BLOCK
    with pytest.raises(ValueError, match="attests"):
        issue_receipt(record)


# --- the trail ------------------------------------------------------------


def test_an_intact_trail_reports_what_it_contains(tmp_path) -> None:
    log = AuditLog(tmp_path / "a.jsonl")
    ledger = a_ledger()
    receive(ledger, an_offer().model_dump(mode="json"), now=NOW, log=log)
    over = an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(9000), kind=LineItemKind.PRODUCT)
        ],
        total_paise=from_rupees(9000),
    )
    receive(ledger, over.model_dump(mode="json"), now=NOW, log=log)

    verdict = verify_trail(log)
    assert verdict.intact
    assert verdict.records == 2
    assert verdict.decisions == {"ALLOW": 1, "BLOCK": 1}


def test_a_tampered_trail_reports_where_it_broke(tmp_path) -> None:
    import json

    log = AuditLog(tmp_path / "a.jsonl")
    ledger = a_ledger()
    for _ in range(4):
        receive(ledger, an_offer().model_dump(mode="json"), now=NOW, log=log)

    lines = log.path.read_text(encoding="utf-8").splitlines()
    edited = json.loads(lines[1])
    edited["decision"] = "BLOCK"
    lines[1] = json.dumps(edited)
    log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    verdict = verify_trail(log)
    assert not verdict.intact
    assert verdict.first_broken_sequence == 2


def test_a_decision_can_be_found_again_months_later(tmp_path) -> None:
    """Inspectable means answerable from the identifiers a person actually has."""
    log = AuditLog(tmp_path / "a.jsonl")
    ledger = a_ledger()
    _, record = receive(ledger, an_offer().model_dump(mode="json"), now=NOW, log=log)

    # A second mandate quoting the same cart. The offer id differs because two
    # quotes are two quotes; the hash is the same because the cart is the same,
    # which is exactly the distinction the two lookups exist to make.
    twin = an_offer(offer_id="off_002")
    receive(a_ledger(intent_id="int_other"), twin.model_dump(mode="json"), now=NOW, log=log)

    assert len(find(log, intent_id=record.intent_id)) == 1
    assert len(find(log, offer_id=record.offer_id)) == 1
    assert len(find(log, offer_id="off_002")) == 1
    assert len(find(log, offer_hash_value=record.offer_hash)) == 1, (
        "the offer id is part of the cart, so a different id is a different hash"
    )
    assert find(log, intent_id="nobody") == []


def test_the_head_of_an_empty_trail_is_genesis(tmp_path) -> None:
    from intentguard.audit import GENESIS

    assert chain_head(AuditLog(tmp_path / "empty.jsonl")) == GENESIS
