"""The boundary an untrusted document actually crosses.

These are the only tests that can exercise OFFER_MALFORMED and UNMODELLED_FIELD,
because both are raised by a payload that never becomes an Offer. Anything that
constructs one has already skipped the failure being tested.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from intentguard.audit import AuditLog
from intentguard.core import Outcome, ViolationCode, from_rupees, payload_hash
from intentguard.gate import receive, unknown_fields
from intentguard.merchant import Hostility, MerchantAgent, project
from tests.fixtures import CREATED_AT, a_ledger, an_offer

NOW = CREATED_AT + timedelta(minutes=5)


def wire(**overrides) -> dict:
    payload = an_offer().model_dump(mode="json")
    payload.update(overrides)
    return payload


def codes(decision) -> set[ViolationCode]:
    return {violation.code for violation in decision.violations}


def test_a_readable_offer_goes_through_the_normal_path() -> None:
    decision, record = receive(a_ledger(), wire(), now=NOW)
    assert decision.decision is Outcome.ALLOW
    assert record.checked_total_paise == from_rupees(4200)


def test_an_unknown_field_escalates_rather_than_blocking() -> None:
    """A lock-in is a real obligation with no slot. Refusing and allowing are both wrong."""
    decision, _ = receive(a_ledger(), wire(loyalty_lock_in_months=12), now=NOW)
    assert decision.decision is Outcome.ESCALATE
    assert ViolationCode.UNMODELLED_FIELD in codes(decision)


def test_the_unknown_field_is_named_in_the_answer() -> None:
    decision, _ = receive(a_ledger(), wire(auto_renew_contract=True), now=NOW)
    violation = next(v for v in decision.violations if v.code is ViolationCode.UNMODELLED_FIELD)
    assert "auto_renew_contract" in violation.observed
    assert "auto_renew_contract" in violation.explanation


def test_several_unknown_fields_are_all_named() -> None:
    decision, _ = receive(a_ledger(), wire(lock_in=1, data_sharing="required"), now=NOW)
    observed = next(
        v for v in decision.violations if v.code is ViolationCode.UNMODELLED_FIELD
    ).observed
    assert "lock_in" in observed and "data_sharing" in observed


def test_a_document_that_cannot_be_read_blocks() -> None:
    """A person cannot adjudicate an unreadable order, so refusing is the safe answer."""
    decision, _ = receive(a_ledger(), wire(total_paise="four thousand"), now=NOW)
    assert decision.decision is Outcome.BLOCK
    assert ViolationCode.OFFER_MALFORMED in codes(decision)


def test_a_missing_required_field_blocks() -> None:
    payload = wire()
    del payload["product"]
    decision, _ = receive(a_ledger(), payload, now=NOW)
    assert decision.decision is Outcome.BLOCK
    assert ViolationCode.OFFER_MALFORMED in codes(decision)


def test_both_kinds_of_problem_are_reported_together() -> None:
    """Report every violation, not the first, holds at the boundary too."""
    decision, _ = receive(a_ledger(), wire(mystery_term=True, quantity=-3), now=NOW)
    assert {ViolationCode.UNMODELLED_FIELD, ViolationCode.OFFER_MALFORMED} <= codes(decision)
    assert decision.decision is Outcome.BLOCK, "a definite fault outranks an uncertainty"


def test_a_refused_document_is_still_recorded_and_still_identifiable(tmp_path) -> None:
    """ "We refused something" is not an audit trail."""
    log = AuditLog(tmp_path / "a.jsonl")
    payload = wire(loyalty_lock_in_months=12)
    _, record = receive(a_ledger(), payload, now=NOW, log=log)
    assert len(log) == 1
    assert record.offer_hash == payload_hash(payload)
    assert log.verify_chain() is None


def test_the_recorded_total_is_the_merchant_claim_not_a_checked_figure() -> None:
    _, record = receive(a_ledger(), wire(loyalty_lock_in_months=12), now=NOW)
    assert record.checked_total_paise == from_rupees(4200)


def test_a_nonsense_total_does_not_poison_the_record() -> None:
    _, record = receive(a_ledger(), wire(total_paise="lots"), now=NOW)
    assert record.checked_total_paise == 0
    assert isinstance(record.checked_total_paise, int)


def test_an_escalation_at_the_boundary_asks_a_question() -> None:
    decision, _ = receive(a_ledger(), wire(surprise_clause="yes"), now=NOW)
    assert decision.escalation_question
    assert decision.escalation_question.endswith("?")


def test_the_hostile_merchants_unknown_field_now_reaches_a_decision() -> None:
    """Closes the gap stage 5 left open: this payload used to have nowhere to go."""
    ledger = a_ledger()
    payload = MerchantAgent(Hostility.UNMODELLED_FIELD).quote(project(ledger))
    decision, record = receive(ledger, payload, now=NOW)
    assert decision.decision is Outcome.ESCALATE
    assert ViolationCode.UNMODELLED_FIELD in codes(decision)
    assert record.offer_id == payload["offer_id"]


@pytest.mark.parametrize("payload", [{}, {"offer_id": "off_1"}, {"offer_id": 42}])
def test_a_hopeless_payload_still_produces_a_decision(payload: dict) -> None:
    """The boundary must be total. No input may return nothing."""
    decision, record = receive(a_ledger(), payload, now=NOW)
    assert decision.decision in {Outcome.BLOCK, Outcome.ESCALATE}
    assert record.offer_hash.startswith("sha256:")


def test_unknown_fields_helper_reports_nothing_for_a_clean_payload() -> None:
    from pydantic import ValidationError

    from intentguard.core import Offer

    try:
        Offer.model_validate(wire(total_paise="bad"))
    except ValidationError as error:
        assert unknown_fields(error) == []
