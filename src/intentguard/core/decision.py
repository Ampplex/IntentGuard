"""The decision record. This is what gets written to the audit trail.

Audit is cross-cutting from stage 2 onward, so this type is the thing every
later stage renders, hashes and files. It is frozen for that reason.

One note on UNMODELLED_FIELD. Because the offer models forbid extra fields, an
offer carrying an unknown key raises a pydantic ValidationError rather than
arriving as data. Those errors carry ``type == "extra_forbidden"`` and a ``loc``,
so the gate can translate them into an UNMODELLED_FIELD violation and escalate.
That translation belongs to the gate, not here -- but the frozen code list has
no code for "the offer failed schema validation for some other reason", which is
a real gap and is flagged rather than papered over.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from .base import StrictModel
from .enums import Outcome
from .violations import ViolationCode


class Violation(StrictModel):
    code: ViolationCode
    outcome: Outcome
    explanation: str
    field: str | None = None
    expected: str | None = None
    observed: str | None = None


class DriftItem(StrictModel):
    """A soft preference that was not met. Never blocks."""

    field: str
    requested: str | None = None
    offered: str | None = None
    weight: float = Field(default=0.0, ge=0.0, le=1.0)


class DriftReport(StrictModel):
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    items: list[DriftItem] = Field(default_factory=list)


class LatencyBreakdown(StrictModel):
    schema_ms: float = 0.0
    arithmetic_ms: float = 0.0
    semantic_ms: float = 0.0
    confidence_ms: float = 0.0
    drift_ms: float = 0.0
    total_ms: float = 0.0


class Decision(StrictModel):
    decision: Outcome
    intent_id: str
    offer_id: str
    violations: list[Violation] = Field(default_factory=list)
    drift: DriftReport = DriftReport()
    escalation_question: str | None = None
    latency_ms: LatencyBreakdown = LatencyBreakdown()
    checked_at: datetime

    @model_validator(mode="after")
    def _allow_carries_no_violations(self) -> Decision:
        if self.decision is Outcome.ALLOW and self.violations:
            raise ValueError("an ALLOW cannot carry violations")
        if self.decision is not Outcome.ALLOW and not self.violations:
            raise ValueError(f"a {self.decision.value} must say what was wrong")
        return self
