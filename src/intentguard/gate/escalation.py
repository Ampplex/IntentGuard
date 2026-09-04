"""Pausing to ask a person, and resuming afterwards.

The failure this project promises to handle gracefully is an instruction the
extractor cannot turn into a defensible mandate. "Get me a decent laptop,
nothing too pricey" has no ceiling in it, and the system neither guesses one nor
silently passes: it stops, says what it could not work out, and waits.

Two shapes of question, and they resume differently.

A **mandate question** is asked before any offer exists, because the instruction
itself was unclear. Answering it produces a live mandate with a fresh clock.

An **offer question** is asked about a specific cart the engine could not judge
-- a condition outside the enum, a field with no slot. Answering it re-runs the
decision rather than overriding it.

**A human answer resolves uncertainty. It never overrides a definite
violation.** Approving an offer re-runs the whole decision with the approval
recorded, and if that re-run finds a real breach -- the mandate expired while
the person was deciding, or the merchant changed the cart -- the block stands.
Otherwise the answer to "is this allowed" would be "someone clicked yes", which
is the property the whole system exists to replace.

**The TTL restarts rather than resuming.** Time somebody spent deciding is not
time the authorization was live, and expiring a transaction a person was
mid-approval of is a bad product and a worse demo.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from ..audit.records import AuditRecord
from ..audit.store import AuditLog
from ..core.base import StrictModel
from ..core.decision import Decision
from ..core.enums import LedgerStatus, Outcome
from ..core.intent import IntentLedger
from ..ledger.build import LedgerProposal, confirm
from .boundary import receive


class QuestionKind(StrEnum):
    MANDATE = "mandate"
    OFFER = "offer"


class Resolution(StrEnum):
    CONFIRMED = "confirmed"
    DECLINED = "declined"
    OVERTAKEN = "overtaken"


class PendingQuestion(StrictModel):
    """A question waiting on a person. Persisted so it can outlive the process."""

    question_id: str
    kind: QuestionKind
    intent_id: str
    question: str
    asked_at: datetime
    offer_id: str | None = None
    weak_fields: tuple[str, ...] = ()


class Answer(StrictModel):
    question_id: str
    approved: bool
    answered_at: datetime
    note: str = ""


class ResolvedEscalation(StrictModel):
    resolution: Resolution
    question_id: str
    decision: Decision | None = None
    ledger: IntentLedger | None = None
    detail: str = ""


def ask_about_mandate(proposal: LedgerProposal, *, now: datetime) -> PendingQuestion | None:
    """Turn an unusable extraction into a question. None if nothing needs asking."""
    if proposal.question is None:
        return None
    intent_id = proposal.ledger.intent_id if proposal.ledger else "int_unbuilt"
    return PendingQuestion(
        question_id=f"q_{uuid.uuid4().hex[:12]}",
        kind=QuestionKind.MANDATE,
        intent_id=intent_id,
        question=proposal.question,
        asked_at=now,
        weak_fields=proposal.weak_fields,
    )


def pause(ledger: IntentLedger) -> IntentLedger:
    """Stop the mandate's clock while a person is being asked.

    Without this the TTL keeps running while somebody decides, and an answer six
    hours later arrives against an expired mandate. The specification is
    explicit that a slow human must not produce LEDGER_EXPIRED on a transaction
    they were mid-approval of, and leaving the mandate ACTIVE did exactly that.
    """
    if ledger.status is not LedgerStatus.ACTIVE:
        return ledger
    return ledger.model_copy(update={"status": LedgerStatus.AWAITING_CONFIRMATION})


def ask_about_offer(
    decision: Decision, ledger: IntentLedger, *, now: datetime
) -> tuple[PendingQuestion | None, IntentLedger]:
    """Turn an escalated decision into a question, and stop the clock.

    Returns the mandate alongside the question because raising one changes the
    other: a mandate waiting on a person is not a mandate ticking down. When
    nothing needs asking, the mandate comes back untouched.
    """
    if decision.decision is not Outcome.ESCALATE or not decision.escalation_question:
        return None, ledger
    question = PendingQuestion(
        question_id=f"q_{uuid.uuid4().hex[:12]}",
        kind=QuestionKind.OFFER,
        intent_id=decision.intent_id,
        offer_id=decision.offer_id,
        question=decision.escalation_question,
        asked_at=now,
    )
    return question, pause(ledger)


def resolve_mandate(
    question: PendingQuestion,
    answer: Answer,
    proposal: LedgerProposal,
    *,
    now: datetime,
    ttl_seconds: int | None = None,
) -> ResolvedEscalation:
    """A person answered a question about their own instruction."""
    if answer.question_id != question.question_id:
        return ResolvedEscalation(
            resolution=Resolution.OVERTAKEN,
            question_id=question.question_id,
            detail="the answer refers to a different question",
        )
    if not answer.approved:
        return ResolvedEscalation(
            resolution=Resolution.DECLINED,
            question_id=question.question_id,
            detail="the user declined the reading that was proposed to them",
        )
    if proposal.ledger is None:
        # Nothing was extractable enough to confirm. Approving a mandate that
        # does not exist would invent constraints nobody stated.
        return ResolvedEscalation(
            resolution=Resolution.DECLINED,
            question_id=question.question_id,
            detail="there was no mandate to confirm; the instruction needs restating",
        )
    return ResolvedEscalation(
        resolution=Resolution.CONFIRMED,
        question_id=question.question_id,
        ledger=confirm(proposal.ledger, now=now, ttl_seconds=ttl_seconds),
        detail="confirmed by the user; the clock restarts from now",
    )


def resolve_offer(
    question: PendingQuestion,
    answer: Answer,
    ledger: IntentLedger,
    payload: dict,
    *,
    now: datetime,
    log: AuditLog | None = None,
) -> tuple[ResolvedEscalation, AuditRecord | None]:
    """A person answered a question about a specific cart.

    The decision is re-run rather than overridden. An approval clears an
    escalation and nothing else: if the re-run finds a definite violation, the
    block stands and the approval is recorded against it.
    """
    if answer.question_id != question.question_id:
        return (
            ResolvedEscalation(
                resolution=Resolution.OVERTAKEN,
                question_id=question.question_id,
                detail="the answer refers to a different question",
            ),
            None,
        )

    if not answer.approved:
        return (
            ResolvedEscalation(
                resolution=Resolution.DECLINED,
                question_id=question.question_id,
                detail="the user declined; nothing was charged",
            ),
            None,
        )

    # A mandate paused for a question is not live, and the engine would refuse it
    # on that ground alone. The person answering has just made it live, so the
    # clock restarts before the re-run.
    live = (
        confirm(ledger, now=now) if ledger.status is LedgerStatus.AWAITING_CONFIRMATION else ledger
    )
    decision, record = receive(live, payload, now=now, log=log, human_confirmed=True)

    if decision.decision is Outcome.BLOCK:
        return (
            ResolvedEscalation(
                resolution=Resolution.OVERTAKEN,
                question_id=question.question_id,
                decision=decision,
                ledger=live,
                detail=(
                    "the order broke a hard constraint on re-check, so the approval "
                    "does not apply; a person can resolve an uncertainty and not a breach"
                ),
            ),
            record,
        )

    approved = decision.model_copy(
        update={"decision": Outcome.ALLOW, "violations": [], "escalation_question": None}
    )
    return (
        ResolvedEscalation(
            resolution=Resolution.CONFIRMED,
            question_id=question.question_id,
            decision=approved,
            ledger=live,
            detail="the user resolved the uncertainty the engine could not",
        ),
        record.model_copy(update={"decision": Outcome.ALLOW, "human_confirmed": True}),
    )


class EscalationBook:
    """Questions waiting on people, persisted as JSONL.

    A question that only exists in memory cannot be answered tomorrow, and a
    person asked to confirm a purchase does not always answer within a request.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def ask(self, question: PendingQuestion) -> PendingQuestion:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(question.model_dump_json() + "\n")
        return question

    def pending(self) -> Iterator[PendingQuestion]:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield PendingQuestion.model_validate_json(line)

    def find(self, question_id: str) -> PendingQuestion | None:
        for question in self.pending():
            if question.question_id == question_id:
                return question
        return None

    def for_intent(self, intent_id: str) -> list[PendingQuestion]:
        return [q for q in self.pending() if q.intent_id == intent_id]

    def __len__(self) -> int:
        return sum(1 for _ in self.pending())


def render_question(question: PendingQuestion) -> str:
    """What a person is actually shown."""
    lines = [f"IntentGuard needs your confirmation ({question.question_id})", "", question.question]
    if question.weak_fields:
        readable = ", ".join(
            field.replace("_paise", "").replace("_", " ") for field in question.weak_fields
        )
        lines += ["", f"Unclear: {readable}"]
    lines += ["", "Reply yes to go ahead, or no to stop. Nothing has been charged."]
    return "\n".join(lines)


def _json(model: StrictModel) -> str:  # pragma: no cover - convenience for demos
    return json.dumps(json.loads(model.model_dump_json()), indent=2)
