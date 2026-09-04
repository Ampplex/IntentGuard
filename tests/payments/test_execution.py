"""The stage 8 gates: no call on a block, and the timeout path.

The blocked-path tests use a client that raises when anything calls it. A client
that recorded calls instead would let a regression pass silently, and "gated"
means the rail is never reached rather than reached and undone.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from intentguard.audit import AuditLog
from intentguard.core import LedgerStatus, Offer, Outcome, from_rupees
from intentguard.gate import receive
from intentguard.payments import (
    MAX_RECEIPT_CHARS,
    MINIMUM_AMOUNT_PAISE,
    Execution,
    LiveKeyRefused,
    PaymentRefused,
    PaymentTimeout,
    RefusingClient,
    execute,
    receipt_for,
    reconcile,
)
from intentguard.payments.razorpay import HttpRazorpayClient
from tests.fixtures import CREATED_AT, a_ledger, a_trial_recurrence, an_offer

NOW = CREATED_AT + timedelta(minutes=5)


class FakeRazorpay:
    """Records what it was asked to do and answers as Razorpay documents."""

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.orders: list[dict[str, Any]] = []
        self.fetches: list[str] = []
        self.fail_with = fail_with
        self._by_receipt: dict[str, dict[str, Any]] = {}

    def create_order(self, **kwargs: Any) -> dict[str, Any]:
        self.orders.append(kwargs)
        if self.fail_with is not None:
            raise self.fail_with
        receipt = kwargs["receipt"]
        # receipt is documented as the idempotency key, so the same receipt
        # returns the same order rather than a second one.
        existing = self._by_receipt.get(receipt)
        if existing is not None:
            return existing
        order = {
            "id": f"order_{len(self._by_receipt) + 1:04d}",
            "entity": "order",
            "amount": kwargs["amount_paise"],
            "amount_paid": 0,
            "currency": kwargs["currency"],
            "receipt": receipt,
            "status": "created",
        }
        self._by_receipt[receipt] = order
        return order

    def fetch_order(self, order_id: str) -> dict[str, Any]:
        self.fetches.append(order_id)
        return {"id": order_id, "status": "created", "amount_paid": 0}

    def fetch_order_payments(self, order_id: str) -> dict[str, Any]:
        self.fetches.append(order_id)
        return {"entity": "collection", "count": 0, "items": []}


class SettledRazorpay(FakeRazorpay):
    def fetch_order_payments(self, order_id: str) -> dict[str, Any]:
        self.fetches.append(order_id)
        return {
            "entity": "collection",
            "count": 1,
            "items": [{"id": "pay_1", "status": "captured", "order_id": order_id}],
        }


def decide(offer: Offer | None = None, ledger=None):
    ledger = ledger or a_ledger()
    payload = (offer or an_offer()).model_dump(mode="json")
    decision, record = receive(ledger, payload, now=NOW)
    return ledger, decision, record


def over_budget() -> Offer:
    from intentguard.core import LineItem, LineItemKind

    return an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(9000), kind=LineItemKind.PRODUCT)
        ],
        total_paise=from_rupees(9000),
    )


def unjudgeable() -> Offer:
    offer = an_offer()
    return offer.model_copy(
        update={"product": offer.product.model_copy(update={"condition": "gently loved"})}
    )


# --- gate one: no call on a block -----------------------------------------


def test_a_blocked_decision_never_reaches_the_rail() -> None:
    ledger, decision, record = decide(over_budget())
    assert decision.decision is Outcome.BLOCK

    attempt, after = execute(ledger, record, RefusingClient(), now=NOW)
    assert attempt.outcome is Execution.NOT_AUTHORIZED
    assert attempt.reached_the_rail is False
    assert after is ledger, "a refused execution must not touch the mandate"


def test_an_escalated_decision_never_reaches_the_rail() -> None:
    """The invariant covers ESCALATE too, extended in Amendment 1."""
    ledger, decision, record = decide(unjudgeable())
    assert decision.decision is Outcome.ESCALATE
    attempt, _ = execute(ledger, record, RefusingClient(), now=NOW)
    assert attempt.outcome is Execution.NOT_AUTHORIZED


def test_the_refusing_client_really_does_raise() -> None:
    """Otherwise the two tests above pass for no reason at all."""
    with pytest.raises(RefusingClient.Called):
        RefusingClient().create_order(amount_paise=1, currency="INR", receipt="r", notes={})


def test_the_recurrence_trap_stops_before_the_rail() -> None:
    ledger, decision, record = decide(an_offer(recurring=[a_trial_recurrence()]))
    assert decision.decision is Outcome.BLOCK
    attempt, _ = execute(ledger, record, RefusingClient(), now=NOW)
    assert attempt.reached_the_rail is False


# --- the allowed path -----------------------------------------------------


def test_an_allowed_decision_places_an_order() -> None:
    ledger, decision, record = decide()
    client = FakeRazorpay()
    attempt, after = execute(ledger, record, client, now=NOW)

    assert decision.decision is Outcome.ALLOW
    assert attempt.outcome is Execution.PLACED
    assert attempt.order_id == "order_0001"
    assert after.status is LedgerStatus.SPENT


def test_the_amount_sent_is_the_amount_that_was_checked() -> None:
    """The caller cannot supply it. That is the EMI bypass one layer down.

    If an amount could be passed in here, everything the engine did to decide
    which figure to check could be undone by whoever calls the rail.
    """
    ledger, _, record = decide()
    client = FakeRazorpay()
    execute(ledger, record, client, now=NOW)
    assert client.orders[0]["amount_paise"] == record.checked_total_paise
    assert client.orders[0]["amount_paise"] == from_rupees(4200)


def test_the_amount_is_an_integer_number_of_paise() -> None:
    ledger, _, record = decide()
    client = FakeRazorpay()
    execute(ledger, record, client, now=NOW)
    amount = client.orders[0]["amount_paise"]
    assert isinstance(amount, int) and not isinstance(amount, bool)


def test_the_order_carries_the_intent_and_the_offer_hash() -> None:
    """So a Razorpay dashboard row can be traced back to the authorization."""
    ledger, _, record = decide()
    client = FakeRazorpay()
    execute(ledger, record, client, now=NOW)
    notes = client.orders[0]["notes"]
    assert notes["intent_id"] == record.intent_id
    assert notes["offer_hash"] == record.offer_hash


def test_an_amount_under_razorpays_minimum_is_refused_here() -> None:
    """Finding this out from a 400 would leave an order in an unknown state."""
    ledger, _, record = decide()
    tiny = record.model_copy(update={"checked_total_paise": MINIMUM_AMOUNT_PAISE - 1})
    attempt, _ = execute(ledger, tiny, RefusingClient(), now=NOW)
    assert attempt.outcome is Execution.BELOW_MINIMUM
    assert attempt.reached_the_rail is False


# --- idempotency ----------------------------------------------------------


def test_the_same_authorization_produces_the_same_receipt() -> None:
    ledger, _, record = decide()
    assert receipt_for(record.intent_id, record.offer_hash) == receipt_for(
        record.intent_id, record.offer_hash
    )


def test_a_different_cart_produces_a_different_receipt() -> None:
    _, _, first = decide()
    _, _, second = decide(an_offer(total_paise=from_rupees(4201), line_items=an_offer().line_items))
    assert first.offer_hash != second.offer_hash
    assert receipt_for(first.intent_id, first.offer_hash) != receipt_for(
        second.intent_id, second.offer_hash
    )


def test_the_receipt_fits_razorpays_documented_cap() -> None:
    receipt = receipt_for("int_" + "x" * 200, "sha256:" + "f" * 64)
    assert len(receipt) <= MAX_RECEIPT_CHARS
    assert receipt.isascii()


def test_executing_twice_does_not_create_two_orders() -> None:
    """The receipt is the idempotency key, so a repeat returns the same order."""
    ledger, _, record = decide()
    client = FakeRazorpay()
    first, _ = execute(ledger, record, client, now=NOW)
    second, _ = execute(ledger, record, client, now=NOW)
    assert first.order_id == second.order_id
    assert len({order["receipt"] for order in client.orders}) == 1


# --- gate two: the timeout path -------------------------------------------


def test_a_timeout_leaves_the_mandate_uncertain_rather_than_spent() -> None:
    """A failure means nothing happened. A timeout means nobody knows."""
    ledger, _, record = decide()
    client = FakeRazorpay(fail_with=PaymentTimeout("no answer"))
    attempt, after = execute(ledger, record, client, now=NOW)

    assert attempt.outcome is Execution.UNCERTAIN
    assert attempt.reached_the_rail is True
    assert after.status is LedgerStatus.EXECUTION_UNCERTAIN
    assert "never retry blind" in attempt.detail


def test_a_timeout_does_not_retry_by_itself() -> None:
    ledger, _, record = decide()
    client = FakeRazorpay(fail_with=PaymentTimeout("no answer"))
    execute(ledger, record, client, now=NOW)
    assert len(client.orders) == 1, "one request went out and none was repeated"


def test_the_attempt_is_recorded_before_the_request_leaves(tmp_path) -> None:
    """Otherwise a timeout leaves no evidence the attempt was ever made."""
    log = AuditLog(tmp_path / "audit.jsonl")
    ledger, _, record = decide()
    execute(ledger, record, FakeRazorpay(fail_with=PaymentTimeout("gone")), now=NOW, log=log)
    assert len(log) == 1
    assert log.verify_chain() is None


def test_reconciling_an_uncertain_attempt_finds_the_existing_order() -> None:
    ledger, _, record = decide()
    timing_out = FakeRazorpay(fail_with=PaymentTimeout("no answer"))
    attempt, uncertain = execute(ledger, record, timing_out, now=NOW)

    answering = FakeRazorpay()
    resolved, after = reconcile(attempt, uncertain, answering)
    assert resolved is not None
    assert resolved.order_id
    assert resolved.settled is False
    assert after.status is LedgerStatus.ACTIVE, "nothing was taken, so the mandate lives"


def test_reconciling_a_settled_payment_spends_the_mandate() -> None:
    ledger, _, record = decide()
    attempt, uncertain = execute(
        ledger, record, FakeRazorpay(fail_with=PaymentTimeout("no answer")), now=NOW
    )
    resolved, after = reconcile(attempt, uncertain, SettledRazorpay())
    assert resolved.settled is True
    assert resolved.payment_statuses == ["captured"]
    assert after.status is LedgerStatus.SPENT


def test_reconciling_uses_the_same_receipt_so_it_cannot_double_charge() -> None:
    """The order id is unknown after a timeout, which is the whole difficulty.

    Repeating the identical request is safe because the receipt is the
    idempotency key; guessing an order id would not be.
    """
    ledger, _, record = decide()
    attempt, uncertain = execute(
        ledger, record, FakeRazorpay(fail_with=PaymentTimeout("no answer")), now=NOW
    )
    answering = FakeRazorpay()
    reconcile(attempt, uncertain, answering)
    assert answering.orders[0]["receipt"] == attempt.receipt


def test_reconciling_anything_else_does_nothing() -> None:
    ledger, _, record = decide()
    attempt, _ = execute(ledger, record, FakeRazorpay(), now=NOW)
    resolved, after = reconcile(attempt, ledger, RefusingClient())
    assert resolved is None
    assert after is ledger


def test_a_refusal_is_not_an_uncertainty() -> None:
    ledger, _, record = decide()
    client = FakeRazorpay(fail_with=PaymentRefused("card declined"))
    attempt, after = execute(ledger, record, client, now=NOW)
    assert attempt.outcome is Execution.REFUSED
    assert after.status is ledger.status, "a clean no leaves the mandate as it was"


# --- test mode only -------------------------------------------------------


# Assembled at runtime rather than written out, so that the repository-wide scan
# for a committed live key in tests/structure has nothing to trip over here. A
# scanner that has to skip files is a scanner with a hole in it.
LIVE_KEY_SHAPE = "rzp_" + "live_" + "abc123"


def test_a_live_key_is_refused_at_construction() -> None:
    """The invariant is fail loudly at startup, not fail during a review."""
    with pytest.raises(LiveKeyRefused, match="test mode only"):
        HttpRazorpayClient(LIVE_KEY_SHAPE, "secret")


def test_a_test_key_is_accepted() -> None:
    client = HttpRazorpayClient("rzp_test_abc123", "secret")
    assert client.key_id.startswith("rzp_test_")


@pytest.mark.parametrize("key", ["", "abc123", "live_abc", "RZP_TEST_ABC"])
def test_anything_that_is_not_a_test_key_is_refused(key: str) -> None:
    with pytest.raises(LiveKeyRefused):
        HttpRazorpayClient(key, "secret")


# --- what the executor is handed, and by whom ------------------------------
# The audit record comes from inside the system and the response comes from
# Razorpay. Neither was checked, and three of the four gaps below were paths to
# a second charge.


class OddResponse(FakeRazorpay):
    """Answers with whatever it was given, however unhelpful."""

    def __init__(self, body: Any) -> None:
        super().__init__()
        self.body = body

    def create_order(self, **kwargs: Any) -> dict[str, Any]:
        self.orders.append(kwargs)
        return self.body


@pytest.mark.parametrize(
    "body",
    [{}, {"status": "created"}, {"id": None, "status": "created"}, {"id": ""}, []],
    ids=["empty", "no id", "null id", "blank id", "not a dict"],
)
def test_an_unidentifiable_order_is_uncertain_rather_than_placed(body: Any) -> None:
    """Calling this PLACED marked the mandate spent with no way to find the order.

    Something went out and something came back. Whether an order exists is
    unknown, which is exactly the state a timeout produces, so it gets the same
    answer: go and ask.
    """
    ledger, _, record = decide()
    attempt, after = execute(ledger, record, OddResponse(body), now=NOW)
    assert attempt.outcome is Execution.UNCERTAIN
    assert after.status is LedgerStatus.EXECUTION_UNCERTAIN
    assert attempt.order_id is None


@pytest.mark.parametrize(
    "status",
    [
        LedgerStatus.SPENT,
        LedgerStatus.EXPIRED,
        LedgerStatus.EXECUTION_UNCERTAIN,
        LedgerStatus.AWAITING_CONFIRMATION,
    ],
    ids=lambda s: s.value,
)
def test_a_mandate_that_is_not_live_cannot_be_spent(status: LedgerStatus) -> None:
    """A path to a second charge, and the engine is not on it.

    A caller holding an older ALLOW record could execute against a mandate that
    has since been spent. Idempotency does not save it: a different cart under
    the same mandate is a different receipt and therefore a different order.
    """
    ledger, _, record = decide()
    stale = ledger.model_copy(update={"status": status})
    attempt, after = execute(stale, record, RefusingClient(), now=NOW)
    assert attempt.outcome is Execution.MANDATE_NOT_LIVE
    assert attempt.reached_the_rail is False
    assert after.status is status


def test_a_decision_from_one_mandate_cannot_be_executed_against_another() -> None:
    """Confused deputy with a payment rail attached.

    The amount and receipt would come from the first mandate and the currency
    and state from the second.
    """
    ledger, _, record = decide()
    someone_else = ledger.model_copy(update={"intent_id": "int_someone_else"})
    attempt, _ = execute(someone_else, record, RefusingClient(), now=NOW)
    assert attempt.outcome is Execution.RECORD_MISMATCH
    assert attempt.reached_the_rail is False


def test_a_nonsense_amount_paid_does_not_enter_the_money_path() -> None:
    class OddPayments(FakeRazorpay):
        def fetch_order_payments(self, order_id: str) -> dict[str, Any]:
            return {"items": [{"status": "captured"}, "not a dict"]}

        def create_order(self, **kwargs: Any) -> dict[str, Any]:
            order = super().create_order(**kwargs)
            return {**order, "amount_paid": "lots"}

    ledger, _, record = decide()
    attempt, uncertain = execute(
        ledger, record, FakeRazorpay(fail_with=PaymentTimeout("no answer")), now=NOW
    )
    resolved, _ = reconcile(attempt, uncertain, OddPayments())
    assert resolved.amount_paid_paise == 0
    assert isinstance(resolved.amount_paid_paise, int)
    assert resolved.payment_statuses == ["captured"]
