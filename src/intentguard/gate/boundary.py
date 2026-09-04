"""The boundary an untrusted offer actually crosses.

A merchant sends a document, not an object. Everything before this point in the
system assumes a parsed Offer, and something has to turn one into the other --
including when it cannot, which is the interesting case.

Two failures are distinguished, because they deserve different answers.

A key the schema has no slot for is not necessarily bad. A twelve month lock-in
is a real obligation the system has no way to judge, and refusing it outright
would block orders that were fine while approving it would authorize terms
nobody read. That escalates.

Anything else wrong with the document is a block. A person cannot usefully
adjudicate an order that could not be read, and refusing is safe.

Either way the payload is hashed and recorded. "We refused something" is not an
audit trail; "we refused this exact document, here is its hash" is.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import ValidationError

from ..audit.records import AuditRecord
from ..audit.store import AuditLog
from ..core.decision import Decision, LatencyBreakdown, Violation
from ..core.enums import Outcome
from ..core.hashing import content_hash, payload_hash
from ..core.intent import IntentLedger
from ..core.offer import Offer
from ..core.violations import DEFAULT_OUTCOME, ViolationCode, explain
from .orchestrator import escalation_question, run_gate

# Fields the schema knows about, so the unknown ones can be named in the answer.
KNOWN_OFFER_FIELDS = frozenset(Offer.model_fields)


def unknown_fields(error: ValidationError) -> list[str]:
    """The keys pydantic refused, in the order it found them."""
    found: list[str] = []
    for detail in error.errors():
        if detail["type"] == "extra_forbidden" and detail["loc"]:
            name = ".".join(str(part) for part in detail["loc"])
            if name not in found:
                found.append(name)
    return found


def _other_problems(error: ValidationError) -> list[str]:
    return [
        f"{'.'.join(str(part) for part in detail['loc']) or 'offer'}: {detail['msg']}"
        for detail in error.errors()
        if detail["type"] != "extra_forbidden"
    ]


def _violation(code: ViolationCode, observed: str) -> Violation:
    return Violation(
        code=code,
        outcome=DEFAULT_OUTCOME[code],
        explanation=explain(code, observed=observed),
        field="offer",
        observed=observed,
    )


def rejection_violations(error: ValidationError) -> list[Violation]:
    """Both kinds of problem, reported together rather than the first one found."""
    violations: list[Violation] = []
    unknown = unknown_fields(error)
    if unknown:
        violations.append(_violation(ViolationCode.UNMODELLED_FIELD, ", ".join(unknown)))
    others = _other_problems(error)
    if others:
        violations.append(_violation(ViolationCode.OFFER_MALFORMED, "; ".join(others[:3])))
    if not violations:
        violations.append(_violation(ViolationCode.OFFER_MALFORMED, "the order could not be read"))
    return violations


def receive(
    ledger: IntentLedger,
    payload: dict,
    *,
    now: datetime,
    log: AuditLog | None = None,
    human_confirmed: bool = False,
) -> tuple[Decision, AuditRecord]:
    """Take a merchant's document and answer it. The entry point for the wire."""
    try:
        offer = Offer.model_validate(payload)
    except ValidationError as error:
        return _refuse(ledger, payload, error, now=now, log=log, human_confirmed=human_confirmed)
    return run_gate(ledger, offer, now=now, log=log, human_confirmed=human_confirmed)


def _refuse(
    ledger: IntentLedger,
    payload: dict,
    error: ValidationError,
    *,
    now: datetime,
    log: AuditLog | None,
    human_confirmed: bool,
) -> tuple[Decision, AuditRecord]:
    violations = rejection_violations(error)
    outcome = (
        Outcome.BLOCK if any(v.outcome is Outcome.BLOCK for v in violations) else Outcome.ESCALATE
    )
    offer_id = payload.get("offer_id") if isinstance(payload.get("offer_id"), str) else "unparsed"
    stated_total = payload.get("total_paise")

    decision = Decision(
        decision=outcome,
        intent_id=ledger.intent_id,
        offer_id=offer_id,
        violations=violations,
        escalation_question=escalation_question(outcome, violations),
        latency_ms=LatencyBreakdown(),
        checked_at=now,
    )
    record = AuditRecord(
        record_id=f"aud_{uuid.uuid4().hex[:12]}",
        sequence=0,
        previous_hash="",
        intent_id=ledger.intent_id,
        offer_id=offer_id,
        mandate_hash=content_hash(ledger),
        offer_hash=payload_hash(payload),
        decision=outcome,
        violations=violations,
        # The merchant's own claim, recorded as claimed. Nothing was checked
        # against it, because the document it came in was not readable.
        checked_total_paise=stated_total if isinstance(stated_total, int) else 0,
        max_total_paise=ledger.hard.max_total_paise,
        latency_ms=LatencyBreakdown(),
        human_confirmed=human_confirmed,
        checked_at=now,
    )
    if log is not None:
        record = log.append(record)
    return decision, record
