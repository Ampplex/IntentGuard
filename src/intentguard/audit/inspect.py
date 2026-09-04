"""Rendering a decision so a person can read it.

The stage gate is that every decision is inspectable. A JSONL file is
technically inspectable and practically is not, and the person who needs to read
one of these is usually a merchant asking why an order was refused or a support
agent asking what the user actually authorized.

So the rendering leads with the answer and the reason, puts the money in rupees,
and shows the hashes last. Nothing here decides anything; it reads a record that
was written when the decision was made.
"""

from __future__ import annotations

from ..core.decision import Decision
from ..core.money import format_paise
from .records import AuditRecord, ComplianceReceipt

_RULE = "-" * 72

# A record that has not been appended to a trail has no predecessor yet. A
# blank there reads as a missing hash rather than as an unwritten record.
NOT_YET_WRITTEN = "(not yet written to a trail)"


def render_record(record: AuditRecord) -> str:
    """One decision, in full, for a person."""
    headroom = record.max_total_paise - record.checked_total_paise
    lines = [
        _RULE,
        f"  {record.decision.value}   {record.checked_at.isoformat()}",
        _RULE,
        f"  intent      {record.intent_id}",
        f"  offer       {record.offer_id}",
        f"  amount      {format_paise(record.checked_total_paise)} checked against a "
        f"{format_paise(record.max_total_paise)} limit",
        f"              {'headroom' if headroom >= 0 else 'over by'} {format_paise(abs(headroom))}",
    ]
    if record.human_confirmed:
        lines.append("  confirmed   by the user, in person")

    if record.violations:
        lines.append("")
        lines.append(f"  {len(record.violations)} finding(s):")
        for violation in record.violations:
            lines.append(f"    [{violation.outcome.value}] {violation.code.value}")
            lines.append(f"      {violation.explanation}")
    else:
        lines.append("")
        lines.append("  no findings; every checked constraint was satisfied")

    lines += [
        "",
        f"  decided in  {record.latency_ms.total_ms:.3f} ms "
        f"(arithmetic {record.latency_ms.arithmetic_ms:.3f} ms)",
        f"  engine      {record.engine_version}",
        f"  mandate     {record.mandate_hash}",
        f"  offer hash  {record.offer_hash}",
        f"  chained to  {record.previous_hash or NOT_YET_WRITTEN}",
        _RULE,
    ]
    return "\n".join(lines)


def render_decision(decision: Decision) -> str:
    """The answer as the caller received it, including anything being asked."""
    lines = [f"{decision.decision.value} for offer {decision.offer_id}"]
    for violation in decision.violations:
        lines.append(f"  [{violation.outcome.value}] {violation.explanation}")
    if decision.escalation_question:
        lines.append(f"  question: {decision.escalation_question}")
    if decision.drift.items:
        missed = ", ".join(
            f"{item.field} (asked {item.requested}, got {item.offered})"
            for item in decision.drift.items
        )
        lines.append(f"  drift {decision.drift.score:.2f}: {missed}")
    return "\n".join(lines)


def render_receipt(receipt: ComplianceReceipt) -> str:
    """The merchant's copy. This is what gets attached to a dispute."""
    return "\n".join(
        [
            _RULE,
            "  COMPLIANCE RECEIPT",
            _RULE,
            f"  receipt     {receipt.receipt_id}",
            f"  issued      {receipt.issued_at.isoformat()}",
            f"  decision    {receipt.decision.value}",
            f"  authorized  {format_paise(receipt.amount_authorized_paise)}",
            f"  intent      {receipt.intent_id}",
            f"  offer       {receipt.offer_id}",
            "",
            "  constraints checked against the user's mandate:",
            *(f"    - {name}" for name in receipt.constraints_checked),
            "",
            f"  human confirmed  {'yes' if receipt.human_confirmed else 'no'}",
            f"  mandate hash     {receipt.mandate_hash}",
            f"  offer hash       {receipt.offer_hash}",
            f"  engine           {receipt.engine_version}",
            "",
            "  To verify: re-hash the offer JSON with sorted keys and no",
            "  insignificant whitespace, and compare with the offer hash above.",
            _RULE,
        ]
    )


def render_trail(records: list[AuditRecord]) -> str:
    """A whole log, newest last, as it was written."""
    if not records:
        return "the trail is empty"
    return "\n\n".join(render_record(record) for record in records)
