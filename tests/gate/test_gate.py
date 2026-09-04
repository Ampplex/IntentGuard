"""The gate assembles the decision, times it, and records it."""

from __future__ import annotations

from datetime import timedelta

import pytest

from intentguard.audit import AuditLog
from intentguard.core import LineItem, LineItemKind, Outcome, ViolationCode, from_rupees
from intentguard.gate import escalation_question, issue_receipt, run_gate
from tests.fixtures import CREATED_AT, a_ledger, a_trial_recurrence, an_offer

NOW = CREATED_AT + timedelta(minutes=5)


def over_budget():
    return an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(9000), kind=LineItemKind.PRODUCT)
        ],
        total_paise=from_rupees(9000),
    )


def unjudgeable():
    offer = an_offer()
    return offer.model_copy(
        update={"product": offer.product.model_copy(update={"condition": "gently loved"})}
    )


def test_an_allow_produces_a_decision_and_a_record(tmp_path) -> None:
    log = AuditLog(tmp_path / "a.jsonl")
    decision, record = run_gate(a_ledger(), an_offer(), now=NOW, log=log)
    assert decision.decision is Outcome.ALLOW
    assert record.decision is Outcome.ALLOW
    assert len(log) == 1


def test_a_block_is_recorded_just_as_an_allow_is(tmp_path) -> None:
    """A trail that only records approvals cannot answer why something was refused."""
    log = AuditLog(tmp_path / "a.jsonl")
    decision, record = run_gate(a_ledger(), over_budget(), now=NOW, log=log)
    assert decision.decision is Outcome.BLOCK
    assert record.violations
    assert log.verify_chain() is None


def test_the_record_carries_both_hashes(tmp_path) -> None:
    _, record = run_gate(a_ledger(), an_offer(), now=NOW)
    assert record.mandate_hash.startswith("sha256:")
    assert record.offer_hash.startswith("sha256:")


def test_latency_is_measured_without_the_engine_reading_a_clock() -> None:
    _, record = run_gate(a_ledger(), an_offer(), now=NOW)
    assert record.latency_ms.total_ms > 0
    assert record.latency_ms.arithmetic_ms > 0
    assert record.latency_ms.total_ms >= record.latency_ms.arithmetic_ms


def test_timing_does_not_make_the_decision_vary() -> None:
    """Observability must not cost determinism."""
    first, _ = run_gate(a_ledger(), over_budget(), now=NOW)
    second, _ = run_gate(a_ledger(), over_budget(), now=NOW)
    assert first.decision is second.decision
    assert [v.code for v in first.violations] == [v.code for v in second.violations]


def test_an_escalation_asks_a_question_built_from_the_violations() -> None:
    decision, _ = run_gate(a_ledger(), unjudgeable(), now=NOW)
    assert decision.decision is Outcome.ESCALATE
    assert decision.escalation_question
    assert "gently loved" in decision.escalation_question
    assert decision.escalation_question.endswith("?")


def test_a_block_asks_nothing() -> None:
    decision, _ = run_gate(a_ledger(), over_budget(), now=NOW)
    assert decision.escalation_question is None


def test_a_receipt_is_issued_only_on_allow() -> None:
    _, allowed = run_gate(a_ledger(), an_offer(), now=NOW)
    receipt = issue_receipt(allowed)
    assert receipt.amount_authorized_paise == from_rupees(4200)
    assert "exclusions" in receipt.constraints_checked
    assert receipt.offer_hash == allowed.offer_hash


@pytest.mark.parametrize("offer_factory", [over_budget, unjudgeable], ids=["block", "escalate"])
def test_no_receipt_without_an_authorization(offer_factory) -> None:
    _, record = run_gate(a_ledger(), offer_factory(), now=NOW)
    with pytest.raises(ValueError, match="attests"):
        issue_receipt(record)


def test_the_receipt_names_what_was_actually_checked() -> None:
    """A merchant defending a chargeback needs the list, not the phrase "all checks"."""
    _, record = run_gate(a_ledger(), an_offer(), now=NOW)
    checked = issue_receipt(record).constraints_checked
    assert {"totals", "recurrence", "currency", "quantity", "condition"} <= set(checked)


def test_the_trap_case_end_to_end(tmp_path) -> None:
    log = AuditLog(tmp_path / "a.jsonl")
    decision, record = run_gate(
        a_ledger(), an_offer(recurring=[a_trial_recurrence()]), now=NOW, log=log
    )
    assert decision.decision is Outcome.BLOCK
    assert ViolationCode.RECURRING_NOT_AUTHORIZED in {v.code for v in decision.violations}
    assert log.verify_chain() is None


def test_escalation_question_is_none_for_non_escalations() -> None:
    assert escalation_question(Outcome.ALLOW, []) is None
    assert escalation_question(Outcome.BLOCK, []) is None
