"""Checking a receipt and a trail after the fact.

A compliance receipt is only evidence if somebody other than the system that
issued it can check it. These functions take the receipt, the offer it refers
to, and nothing else: no database, no service, no trust in the issuer. A
merchant holding the JSON can recompute the hash and see for themselves.

That is the difference between a receipt and a claim. "We checked this order"
is a claim. "Here is the order, here is its hash, here is the receipt naming
that hash and the constraints checked" is something a dispute can turn on.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from ..core.base import StrictModel
from ..core.enums import Outcome
from ..core.hashing import content_hash, offer_hash
from ..core.intent import IntentLedger
from ..core.offer import Offer
from .records import AuditRecord, ComplianceReceipt
from .store import GENESIS, AuditLog


class ReceiptProblem(StrEnum):
    OFFER_DOES_NOT_MATCH = "offer_does_not_match"
    MANDATE_DOES_NOT_MATCH = "mandate_does_not_match"
    NOT_AN_AUTHORIZATION = "not_an_authorization"
    NO_CONSTRAINTS_NAMED = "no_constraints_named"


class ReceiptVerdict(StrictModel):
    valid: bool
    problems: list[ReceiptProblem] = Field(default_factory=list)
    checked_offer_hash: str | None = None


def verify_receipt(
    receipt: ComplianceReceipt,
    offer: Offer,
    ledger: IntentLedger | None = None,
) -> ReceiptVerdict:
    """Does this receipt actually describe this order?

    The offer is re-hashed from scratch rather than compared field by field,
    because a field-by-field comparison has to know which fields matter and the
    hash does not. Any change to the cart, including in the untrusted
    description, produces a different hash.
    """
    problems: list[ReceiptProblem] = []
    recomputed = offer_hash(offer)

    if recomputed != receipt.offer_hash:
        problems.append(ReceiptProblem.OFFER_DOES_NOT_MATCH)
    if ledger is not None and content_hash(ledger) != receipt.mandate_hash:
        problems.append(ReceiptProblem.MANDATE_DOES_NOT_MATCH)
    if receipt.decision is not Outcome.ALLOW:
        problems.append(ReceiptProblem.NOT_AN_AUTHORIZATION)
    if not receipt.constraints_checked:
        # A receipt claiming everything was checked without saying what is worth
        # nothing to whoever has to defend the charge.
        problems.append(ReceiptProblem.NO_CONSTRAINTS_NAMED)

    return ReceiptVerdict(valid=not problems, problems=problems, checked_offer_hash=recomputed)


class TrailVerdict(StrictModel):
    intact: bool
    records: int
    first_broken_sequence: int | None = None
    decisions: dict[str, int] = Field(default_factory=dict)


def verify_trail(log: AuditLog) -> TrailVerdict:
    """Is the whole log unbroken, and what does it contain?

    Reports the counts alongside the integrity check because the two questions
    are always asked together: whether the trail can be trusted, and what it
    says.
    """
    broken = log.verify_chain()
    counts: dict[str, int] = {}
    total = 0
    for record in log.read_all():
        total += 1
        counts[record.decision.value] = counts.get(record.decision.value, 0) + 1
    return TrailVerdict(
        intact=broken is None,
        records=total,
        first_broken_sequence=broken,
        decisions=dict(sorted(counts.items())),
    )


def find(
    log: AuditLog,
    *,
    intent_id: str | None = None,
    offer_id: str | None = None,
    offer_hash_value: str | None = None,
) -> list[AuditRecord]:
    """Pull decisions back out of the trail.

    "Every decision inspectable" means being able to answer "what happened to
    this order" months later, from the identifiers a person actually has: an
    intent, an offer id from a dashboard, or the hash off a receipt.
    """
    found = []
    for record in log.read_all():
        if intent_id is not None and record.intent_id != intent_id:
            continue
        if offer_id is not None and record.offer_id != offer_id:
            continue
        if offer_hash_value is not None and record.offer_hash != offer_hash_value:
            continue
        found.append(record)
    return found


def chain_head(log: AuditLog) -> str:
    """The hash the next record will chain onto. GENESIS for an empty log."""
    _, previous = log.head()
    return previous or GENESIS
