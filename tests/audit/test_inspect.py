"""The stage 10 gate: every decision is inspectable.

A JSONL file is technically inspectable and practically is not. The person who
needs to read one of these is a merchant asking why an order was refused, or a
support agent asking what the user actually authorized, so these tests are about
whether the rendering answers those questions.
"""

from __future__ import annotations

from datetime import timedelta

from intentguard.audit import (
    AuditLog,
    render_decision,
    render_receipt,
    render_record,
    render_trail,
)
from intentguard.core import LineItem, LineItemKind, Outcome, SoftPreferences, from_rupees
from intentguard.gate import issue_receipt, receive
from tests.fixtures import CREATED_AT, a_ledger, a_trial_recurrence, an_offer

NOW = CREATED_AT + timedelta(minutes=5)


def over_budget():
    return an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(9000), kind=LineItemKind.PRODUCT)
        ],
        total_paise=from_rupees(9000),
    )


def decide(offer=None, ledger=None, log=None):
    return receive(
        ledger or a_ledger(), (offer or an_offer()).model_dump(mode="json"), now=NOW, log=log
    )


def test_a_refused_order_says_why_in_the_first_few_lines() -> None:
    """The merchant's actual question is "why was this refused", not "what fields"."""
    _, record = decide(over_budget())
    text = render_record(record)
    head = "\n".join(text.splitlines()[:6])
    assert "BLOCK" in head
    assert "TOTAL_EXCEEDS_MAX" in text
    assert "you authorized at most" in text


def test_money_is_shown_in_rupees_not_paise() -> None:
    """Nobody reads 900000 and thinks nine thousand rupees."""
    _, record = decide(over_budget())
    text = render_record(record)
    assert "₹9,000.00" in text
    assert "₹5,000.00" in text
    assert "900000" not in text


def test_the_record_says_how_far_over_or_under_the_limit_it_was() -> None:
    _, record = decide(over_budget())
    assert "over by ₹4,000.00" in render_record(record)

    _, allowed = decide()
    assert "headroom ₹800.00" in render_record(allowed)


def test_an_allowed_order_says_so_rather_than_showing_nothing() -> None:
    """An empty findings list reads as a missing section unless it is named."""
    _, record = decide()
    assert "no findings" in render_record(record)


def test_every_finding_carries_its_explanation() -> None:
    _, record = decide(an_offer(recurring=[a_trial_recurrence()]))
    text = render_record(record)
    assert "RECURRING_NOT_AUTHORIZED" in text
    assert "converts later" in text


def test_the_record_shows_the_hashes_and_the_chain() -> None:
    _, record = decide()
    text = render_record(record)
    assert record.offer_hash in text
    assert record.mandate_hash in text
    assert record.previous_hash in text


def test_the_record_shows_what_it_cost_to_decide() -> None:
    _, record = decide()
    assert "decided in" in render_record(record)
    assert "arithmetic" in render_record(record)


def test_a_human_confirmation_is_visible_as_a_distinct_kind_of_evidence() -> None:
    ledger = a_ledger()
    _, record = receive(ledger, an_offer().model_dump(mode="json"), now=NOW, human_confirmed=True)
    assert "confirmed   by the user" in render_record(record)


def test_a_whole_trail_renders_in_order(tmp_path) -> None:
    log = AuditLog(tmp_path / "a.jsonl")
    ledger = a_ledger()
    decide(ledger=ledger, log=log)
    decide(over_budget(), ledger=ledger, log=log)

    text = render_trail(list(log.read_all()))
    assert text.index("ALLOW") < text.index("BLOCK")


def test_an_empty_trail_says_so() -> None:
    assert render_trail([]) == "the trail is empty"


# --- the decision as the caller saw it ------------------------------------


def test_an_escalation_shows_the_question_being_asked() -> None:
    offer = an_offer()
    unjudgeable = offer.model_copy(
        update={"product": offer.product.model_copy(update={"condition": "gently loved"})}
    )
    decision, _ = decide(unjudgeable)
    text = render_decision(decision)
    assert decision.decision is Outcome.ESCALATE
    assert "question:" in text
    question = next(line for line in text.splitlines() if "question:" in line)
    assert question.rstrip().endswith("?")


def test_drift_is_shown_with_what_was_asked_and_what_arrived() -> None:
    ledger = a_ledger().model_copy(update={"soft": SoftPreferences(brand="Asics")})
    offer = an_offer()
    other_brand = offer.model_copy(
        update={"product": offer.product.model_copy(update={"brand": "Nike"})}
    )
    decision, _ = decide(other_brand, ledger=ledger)
    text = render_decision(decision)
    assert "drift" in text
    assert "asked Asics" in text and "got Nike" in text


# --- the receipt ----------------------------------------------------------


def test_the_receipt_lists_the_constraints_by_name() -> None:
    _, record = decide()
    text = render_receipt(issue_receipt(record))
    for constraint in ("totals", "recurrence", "currency", "exclusions"):
        assert f"- {constraint}" in text


def test_the_receipt_tells_the_reader_how_to_check_it() -> None:
    """A receipt nobody knows how to verify is a receipt nobody verifies."""
    _, record = decide()
    text = render_receipt(issue_receipt(record))
    assert "To verify" in text
    assert "sorted keys" in text


def test_the_receipt_shows_the_authorized_amount_in_rupees() -> None:
    _, record = decide()
    assert "₹4,200.00" in render_receipt(issue_receipt(record))


def test_the_receipt_records_whether_a_human_confirmed() -> None:
    """A human approval is a different class of evidence from an engine ALLOW."""
    _, record = decide()
    assert "human confirmed  no" in render_receipt(issue_receipt(record))
