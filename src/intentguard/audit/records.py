"""What gets written for every decision, and the receipt a merchant keeps.

Audit is cross-cutting rather than a late stage: every decision writes a record
from the moment a decision exists. The track's bar asks to see the audit trail,
and a trail that only starts once the dashboard is built is not a trail.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from ..core.base import StrictModel
from ..core.decision import LatencyBreakdown, Violation
from ..core.enums import Outcome

ENGINE_VERSION = "0.1.0"


class AuditRecord(StrictModel):
    """One decision, in full, as evidence.

    Carries both hashes so a record can be tied back to the exact mandate and the
    exact offer it judged. previous_hash chains records together: see store.py
    for why that matters.
    """

    record_id: str
    sequence: int = Field(ge=0)
    previous_hash: str
    intent_id: str
    offer_id: str
    mandate_hash: str
    offer_hash: str
    decision: Outcome
    violations: list[Violation] = Field(default_factory=list)
    checked_total_paise: int
    max_total_paise: int
    latency_ms: LatencyBreakdown
    human_confirmed: bool = False
    engine_version: str = ENGINE_VERSION
    checked_at: datetime


class ComplianceReceipt(StrictModel):
    """Issued on ALLOW. This is the merchant's dispute evidence.

    It is the answer to "how does this grow revenue": a merchant holding one of
    these can show that an agent-initiated order was checked against a signed
    mandate before any money moved, and exactly which constraints were checked.
    """

    receipt_id: str
    intent_id: str
    offer_id: str
    mandate_hash: str
    offer_hash: str
    decision: Outcome
    constraints_checked: tuple[str, ...]
    amount_authorized_paise: int
    human_confirmed: bool
    engine_version: str = ENGINE_VERSION
    issued_at: datetime
