"""A swap partway through a negotiation, caught end to end.

This is the drift the problem statement describes: between the instruction and
the final cart the agents negotiate, and the thing being sold can change while
the price stays inside the mandate. No check that only sees the final offer can
notice, because the final offer is compliant. Only comparing it with what was
being negotiated reveals it.
"""

from __future__ import annotations

from datetime import timedelta

from intentguard.buyer import BuyerAgent
from intentguard.core import HardConstraints, Outcome, ViolationCode, from_rupees
from intentguard.gate import receive
from intentguard.merchant import Concession, Hostility, MerchantAgent
from tests.fixtures import CREATED_AT, a_ledger

NOW = CREATED_AT + timedelta(minutes=5)


def mandate(rupees: int = 5000):
    ledger = a_ledger()
    hard = HardConstraints.model_validate(
        {**ledger.hard.model_dump(), "max_total_paise": from_rupees(rupees)}
    )
    return ledger.model_copy(update={"hard": hard})


def codes(decision) -> set[ViolationCode]:
    return {violation.code for violation in decision.violations}


def test_a_swap_mid_negotiation_is_invisible_without_the_opening_quote() -> None:
    """The control. Judged on the final cart alone, the swap passes every check."""
    ledger = mandate()
    swapped = MerchantAgent(Hostility.SUBSTITUTION, Concession.MEET)
    negotiation = BuyerAgent(ledger).negotiate(swapped)

    decision, _ = receive(ledger, negotiation.final_payload, now=NOW)
    assert decision.decision is Outcome.ALLOW
    assert ViolationCode.PRODUCT_SUBSTITUTION not in codes(decision)


def test_the_same_swap_is_caught_when_the_opening_quote_is_supplied() -> None:
    ledger = mandate()
    honest_opening = MerchantAgent().quote(BuyerAgent(ledger).view)
    negotiation = BuyerAgent(ledger).negotiate(
        MerchantAgent(Hostility.SUBSTITUTION, Concession.MEET)
    )

    decision, _ = receive(
        ledger,
        negotiation.final_payload,
        now=NOW,
        negotiated_product=honest_opening["product"]["title"],
    )
    assert decision.decision is Outcome.ESCALATE
    assert ViolationCode.PRODUCT_SUBSTITUTION in codes(decision)
    assert decision.escalation_question


def test_an_unchanged_product_produces_no_escalation() -> None:
    """The case that matters more. A guard that questions every order is useless."""
    ledger = mandate()
    honest = MerchantAgent(concession=Concession.HAGGLE)
    negotiation = BuyerAgent(ledger).negotiate(honest)

    decision, _ = receive(
        ledger,
        negotiation.final_payload,
        now=NOW,
        negotiated_product=negotiation.final_payload["product"]["title"],
    )
    assert decision.decision is Outcome.ALLOW
    assert decision.violations == []


def test_a_semantic_escalation_cannot_override_a_definite_block() -> None:
    """A weaker signal must not soften a stronger one."""
    ledger = mandate(1000)
    negotiation = BuyerAgent(ledger).negotiate(MerchantAgent(concession=Concession.STUBBORN))
    decision, _ = receive(
        ledger, negotiation.final_payload, now=NOW, negotiated_product="Something Else Entirely"
    )
    assert decision.decision is Outcome.BLOCK
    assert {ViolationCode.TOTAL_EXCEEDS_MAX, ViolationCode.PRODUCT_SUBSTITUTION} <= codes(decision)


def test_drift_is_reported_on_every_decision() -> None:
    from intentguard.core import SoftPreferences

    ledger = mandate().model_copy(update={"soft": SoftPreferences(brand="Asics")})
    negotiation = BuyerAgent(ledger).negotiate(MerchantAgent(concession=Concession.MEET))
    decision, _ = receive(ledger, negotiation.final_payload, now=NOW)
    assert decision.drift is not None
    assert 0.0 <= decision.drift.score <= 1.0


def test_drift_alone_never_changes_the_outcome() -> None:
    """Soft preferences rank offers. They do not stop payments."""
    from intentguard.core import SoftPreferences

    ledger = mandate().model_copy(
        update={"soft": SoftPreferences(brand="Asics", colour="blue", delivery_speed="express")}
    )
    negotiation = BuyerAgent(ledger).negotiate(MerchantAgent(concession=Concession.MEET))
    decision, _ = receive(ledger, negotiation.final_payload, now=NOW)
    assert decision.decision is Outcome.ALLOW
    assert decision.drift.score > 0.0, "the preferences were genuinely missed"


def test_the_semantic_phase_is_timed_separately() -> None:
    ledger = mandate()
    negotiation = BuyerAgent(ledger).negotiate(MerchantAgent())
    decision, _ = receive(
        ledger, negotiation.final_payload, now=NOW, negotiated_product="Asics Gel-Contend 9"
    )
    assert decision.latency_ms.semantic_ms > 0
    assert decision.latency_ms.total_ms >= decision.latency_ms.arithmetic_ms


def test_the_shelf_reaches_the_check_through_the_gate() -> None:
    """Wiring, asserted rather than assumed.

    The parameter existed on both gate functions and was never passed to the
    check underneath, so the evasion still passed end to end while every unit
    test of the check itself was green. A signature is not a connection.
    """
    from intentguard.merchant import CATALOG

    payload = {
        "offer_id": "off_evasion",
        "product": {
            "product_id": "sku_x",
            "title": "Asics Gel-Contend 9 replacement, Nike Revolution",
            "category": "footwear",
            "condition": "new",
            "brand": None,
            "colour": None,
        },
        "quantity": 1,
        "currency": "INR",
        "line_items": [{"label": "shoe", "amount_paise": from_rupees(4100), "kind": "product"}],
        "total_paise": from_rupees(4100),
        "recurring": [],
        "emi": None,
        "raw_description": "",
    }
    ledger = mandate()

    without_shelf, _ = receive(ledger, payload, now=NOW, negotiated_product="Asics Gel-Contend 9")
    assert without_shelf.decision is Outcome.ALLOW

    with_shelf, _ = receive(
        ledger,
        payload,
        now=NOW,
        negotiated_product="Asics Gel-Contend 9",
        known_products=[item.title for item in CATALOG],
    )
    assert with_shelf.decision is Outcome.ESCALATE
    assert ViolationCode.PRODUCT_SUBSTITUTION in codes(with_shelf)
    assert "Nike Revolution 7" in with_shelf.violations[0].explanation
