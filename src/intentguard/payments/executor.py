"""Executing an authorization, and surviving not knowing whether it worked.

Three rules, in the order they matter.

**The rail is reached only on ALLOW.** Not reached and rolled back -- not
reached. A BLOCK and an ESCALATE both stop here, and the test for it is a client
that raises when anything calls it, because a client that quietly records calls
would let a regression pass.

**The amount comes from the audit record, never from the caller.** The record
holds the figure the engine actually checked. Letting a caller pass an amount
would reintroduce the bug that let bogus instalment terms lower the number
compared against the ceiling, one layer further down where nothing is checking
any more.

**A timeout is not a failure.** A failure means nothing happened. A timeout
means nobody knows, and the difference is a double charge. The ledger moves to
EXECUTION_UNCERTAIN, the attempt is recorded before the request goes out, and
the next step is to ask Razorpay what happened rather than to try again.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from ..audit.records import AuditRecord
from ..audit.store import AuditLog
from ..core.base import StrictModel
from ..core.enums import LedgerStatus, Outcome
from ..core.intent import IntentLedger
from .idempotency import receipt_for
from .razorpay import MINIMUM_AMOUNT_PAISE, PaymentRefused, PaymentTimeout, RazorpayClient


class Execution(StrEnum):
    NOT_AUTHORIZED = "not_authorized"
    MANDATE_NOT_LIVE = "mandate_not_live"
    RECORD_MISMATCH = "record_mismatch"
    BELOW_MINIMUM = "below_minimum"
    PLACED = "placed"
    REFUSED = "refused"
    UNCERTAIN = "uncertain"


class PaymentAttempt(StrictModel):
    """What was tried, and what is known about it afterwards."""

    outcome: Execution
    receipt: str
    intent_id: str
    offer_id: str
    amount_paise: int
    order_id: str | None = None
    order_status: str | None = None
    detail: str = ""
    reached_the_rail: bool = False
    ledger_status: LedgerStatus | None = None


class ReconciledPayment(StrictModel):
    order_id: str
    order_status: str
    amount_paid_paise: int = 0
    payment_statuses: list[str] = Field(default_factory=list)
    settled: bool = False


def execute(
    ledger: IntentLedger,
    record: AuditRecord,
    client: RazorpayClient,
    *,
    now: datetime,
    log: AuditLog | None = None,
) -> tuple[PaymentAttempt, IntentLedger]:
    """Turn an allowed decision into a Razorpay order, or refuse to.

    Returns the attempt and the ledger as it now stands. The ledger is returned
    rather than mutated because it is frozen, and because a caller holding the
    old one should not be able to act on a mandate that has since been spent.
    """
    amount = record.checked_total_paise
    receipt = receipt_for(record.intent_id, record.offer_hash)
    base = {
        "receipt": receipt,
        "intent_id": record.intent_id,
        "offer_id": record.offer_id,
        "amount_paise": amount,
    }

    if record.intent_id != ledger.intent_id:
        # A decision record names the mandate it was made against. Executing one
        # against a different mandate takes the amount and receipt from the first
        # and the currency and state from the second, which is a confused deputy
        # with a payment rail attached.
        return (
            PaymentAttempt(
                outcome=Execution.RECORD_MISMATCH,
                detail=(
                    f"the decision was made against {record.intent_id} "
                    f"and this mandate is {ledger.intent_id}"
                ),
                **base,
            ),
            ledger,
        )

    if ledger.status is not LedgerStatus.ACTIVE:
        # The engine refuses a spent mandate, but the engine is not on this path:
        # a caller holding an older ALLOW record could otherwise execute against a
        # mandate that has since been spent or expired. Idempotency does not save
        # it, because a different cart under the same mandate is a different
        # receipt and therefore a second charge.
        return (
            PaymentAttempt(
                outcome=Execution.MANDATE_NOT_LIVE,
                detail=(
                    f"the mandate is {ledger.status.value}; only an ACTIVE mandate can be spent"
                ),
                ledger_status=ledger.status,
                **base,
            ),
            ledger,
        )

    if record.decision is not Outcome.ALLOW:
        return (
            PaymentAttempt(
                outcome=Execution.NOT_AUTHORIZED,
                detail=(
                    f"the decision was {record.decision.value}; the rail is reached only on ALLOW"
                ),
                **base,
            ),
            ledger,
        )

    if amount < MINIMUM_AMOUNT_PAISE:
        # Razorpay's own floor. Finding this out from a 400 after the fact would
        # leave an order in an unknown state for a reason known in advance.
        return (
            PaymentAttempt(
                outcome=Execution.BELOW_MINIMUM,
                detail=f"{amount} paise is under Razorpay's minimum of {MINIMUM_AMOUNT_PAISE}",
                **base,
            ),
            ledger,
        )

    if log is not None:
        # Written before the request goes out, so that a timeout leaves evidence
        # that the attempt was made. An attempt recorded afterwards is a record
        # of the attempts that came back.
        log.append(record.model_copy(update={"record_id": f"{record.record_id}_exec"}))

    try:
        order = client.create_order(
            amount_paise=amount,
            currency=ledger.hard.currency,
            receipt=receipt,
            notes={"intent_id": record.intent_id, "offer_hash": record.offer_hash},
        )
    except PaymentTimeout as error:
        uncertain = ledger.model_copy(update={"status": LedgerStatus.EXECUTION_UNCERTAIN})
        return (
            PaymentAttempt(
                outcome=Execution.UNCERTAIN,
                detail=f"{error}; reconcile before doing anything else, never retry blind",
                reached_the_rail=True,
                ledger_status=LedgerStatus.EXECUTION_UNCERTAIN,
                **base,
            ),
            uncertain,
        )
    except PaymentRefused as error:
        return (
            PaymentAttempt(
                outcome=Execution.REFUSED,
                detail=str(error),
                reached_the_rail=True,
                ledger_status=ledger.status,
                **base,
            ),
            ledger,
        )

    order_id = order.get("id") if isinstance(order, dict) else None
    if not isinstance(order_id, str) or not order_id:
        # Something came back and it cannot be identified. Calling that PLACED
        # would mark the mandate spent while leaving no way to find the order,
        # so the honest state is the same one a timeout produces: it may exist,
        # go and ask.
        uncertain = ledger.model_copy(update={"status": LedgerStatus.EXECUTION_UNCERTAIN})
        return (
            PaymentAttempt(
                outcome=Execution.UNCERTAIN,
                detail=(
                    "the response carried no usable order id; reconcile before doing "
                    "anything else, never retry blind"
                ),
                reached_the_rail=True,
                ledger_status=LedgerStatus.EXECUTION_UNCERTAIN,
                **base,
            ),
            uncertain,
        )

    spent = ledger.model_copy(update={"status": LedgerStatus.SPENT})
    return (
        PaymentAttempt(
            outcome=Execution.PLACED,
            order_id=order_id,
            order_status=order.get("status"),
            reached_the_rail=True,
            ledger_status=LedgerStatus.SPENT,
            **base,
        ),
        spent,
    )


def reconcile(
    attempt: PaymentAttempt,
    ledger: IntentLedger,
    client: RazorpayClient,
) -> tuple[ReconciledPayment | None, IntentLedger]:
    """Ask Razorpay what actually happened after a timeout.

    The order id is unknown after a timeout, which is the whole difficulty.
    Razorpay documents `receipt` as acting as the idempotency key, so creating
    the order again with the same receipt returns the existing one rather than a
    second: the safe way to discover the outcome is to repeat the identical
    request, not to guess an id.
    """
    if attempt.outcome is not Execution.UNCERTAIN:
        return None, ledger

    order = client.create_order(
        amount_paise=attempt.amount_paise,
        currency=ledger.hard.currency,
        receipt=attempt.receipt,
        notes={"intent_id": attempt.intent_id, "reconciling": "true"},
    )
    order_id = order.get("id") if isinstance(order, dict) else None
    if not isinstance(order_id, str) or not order_id:
        # Still unidentifiable. The mandate stays uncertain rather than being
        # quietly resolved in either direction.
        return None, ledger

    payments = client.fetch_order_payments(order_id)
    items = payments.get("items", []) if isinstance(payments, dict) else []
    statuses = [item.get("status", "") for item in items if isinstance(item, dict)]
    settled = any(status in {"captured", "authorized"} for status in statuses)

    # Money is integer paise everywhere, including when it arrives from someone
    # else. A string, a float or a bool here would be the one place a non-integer
    # entered the money path from outside the system.
    reported = order.get("amount_paid", 0)
    paid = reported if isinstance(reported, int) and not isinstance(reported, bool) else 0

    resolved = ReconciledPayment(
        order_id=order_id,
        order_status=order.get("status", ""),
        amount_paid_paise=paid,
        payment_statuses=statuses,
        settled=settled,
    )
    # A settled payment consumes the mandate. An unsettled one leaves it active,
    # so the user can try again without a second charge hanging over them.
    status = LedgerStatus.SPENT if settled else LedgerStatus.ACTIVE
    return resolved, ledger.model_copy(update={"status": status})
