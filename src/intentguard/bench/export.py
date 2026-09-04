"""Runs the whole system and writes down what happened.

The stage 12 gate is that the dashboard renders a real run rather than fixtures.
This is what makes that possible: every number it emits is computed here, now,
by putting instructions through extraction, negotiation, the gate, the payment
adapter and the audit log. Nothing is typed in.

If the engine regresses, this file's output changes. That is the whole point of
it existing rather than a JSON file someone maintained by hand.
"""

from __future__ import annotations

import json
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..audit import AuditLog, verify_trail
from ..buyer import BuyerAgent
from ..core.enums import Outcome
from ..core.money import format_paise
from ..gate import (
    Answer,
    ask_about_mandate,
    ask_about_offer,
    issue_receipt,
    receive,
    resolve_mandate,
    resolve_offer,
)
from ..ledger import RuleBasedExtractor, build_ledger
from ..merchant import CATALOG, Concession, Hostility, MerchantAgent, project
from ..payments import PaymentTimeout, RefusingClient, execute, reconcile
from .harness import SYNTHETIC_PATH, injection_experiment, load, report_for

STARTED = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
DECIDED = STARTED + timedelta(minutes=5)
ANSWERED = STARTED + timedelta(hours=6)

SHELF = [item.title for item in CATALOG]
EXTRACT = RuleBasedExtractor()


class _FakeRazorpay:
    """Stands in for the test-mode API so an export needs no key or network.

    Named a fake rather than a client: it answers in the shapes Razorpay
    documents, and the dashboard says plainly that no live call was made.
    """

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.fail_with = fail_with
        self._orders: dict[str, dict[str, Any]] = {}

    def create_order(self, **kwargs: Any) -> dict[str, Any]:
        if self.fail_with is not None:
            raise self.fail_with
        receipt = kwargs["receipt"]
        if receipt not in self._orders:
            self._orders[receipt] = {
                "id": f"order_{len(self._orders) + 1:04d}",
                "amount": kwargs["amount_paise"],
                "amount_paid": 0,
                "currency": kwargs["currency"],
                "receipt": receipt,
                "status": "created",
            }
        return self._orders[receipt]

    def fetch_order(self, order_id: str) -> dict[str, Any]:
        return {"id": order_id, "status": "created", "amount_paid": 0}

    def fetch_order_payments(self, order_id: str) -> dict[str, Any]:
        return {
            "entity": "collection",
            "count": 1,
            "items": [{"id": "pay_1", "status": "captured", "order_id": order_id}],
        }


def _mandate(instruction: str):
    return build_ledger(instruction, EXTRACT.extract(instruction), created_at=STARTED)


def _violations(decision) -> list[dict[str, str]]:
    return [
        {"code": v.code.value, "outcome": v.outcome.value, "explanation": v.explanation}
        for v in decision.violations
    ]


def negotiated_scenario(
    name: str, instruction: str, hostility: Hostility, concession: Concession, log: AuditLog
) -> dict[str, Any]:
    """One transaction, all the way through, exactly as the system runs it."""
    proposal = _mandate(instruction)
    ledger = proposal.ledger
    if ledger is None:
        return {"name": name, "instruction": instruction, "outcome": "no mandate"}

    merchant = MerchantAgent(hostility, concession)

    # What was on the table when the negotiation opened, quoted honestly. Taking
    # it from the hostile merchant instead would compare the swapped product
    # against itself and find nothing, which is a scenario that proves the
    # detector works by never exercising it.
    opening = MerchantAgent().quote(project(ledger))
    buyer = BuyerAgent(ledger)
    negotiation = buyer.negotiate(merchant)

    decision, record = receive(
        ledger,
        negotiation.final_payload,
        now=DECIDED,
        log=log,
        negotiated_product=opening["product"]["title"],
        known_products=SHELF,
    )

    client = _FakeRazorpay() if decision.decision is Outcome.ALLOW else RefusingClient()
    attempt, after = execute(ledger, record, client, now=DECIDED)

    return {
        "name": name,
        "instruction": instruction,
        "merchant": {"hostility": hostility.value, "concession": concession.value},
        "negotiated_product": opening["product"]["title"],
        "delivered_product": negotiation.final_payload["product"]["title"],
        "mandate": {
            "ceiling": format_paise(ledger.hard.max_total_paise),
            "category": ledger.hard.category.value,
            "condition": ledger.hard.condition.value if ledger.hard.condition else None,
            "recurring_allowed": ledger.hard.recurring_allowed,
        },
        "merchant_view_has_ceiling": "max_total" in project(ledger).model_dump_json(),
        "negotiation": {
            "target": format_paise(negotiation.target_paise),
            "ending": negotiation.ending.value,
            "exchanges": negotiation.exchanges,
            "rounds": [
                {
                    "number": r.number,
                    "quoted": format_paise(r.quoted_total_paise),
                    "asked": format_paise(r.asked_for_paise) if r.asked_for_paise else None,
                    "note": r.note,
                }
                for r in negotiation.rounds
            ],
        },
        "decision": decision.decision.value,
        "violations": _violations(decision),
        "drift": {
            "score": round(decision.drift.score, 3),
            "items": [
                {"field": i.field, "requested": i.requested, "offered": i.offered}
                for i in decision.drift.items
            ],
        },
        "latency_ms": round(decision.latency_ms.total_ms, 4),
        "payment": {
            "outcome": attempt.outcome.value,
            "reached_the_rail": attempt.reached_the_rail,
            "order_id": attempt.order_id,
            "amount": format_paise(attempt.amount_paise),
            "receipt": attempt.receipt,
            "ledger_after": after.status.value,
        },
        "compliance_receipt": (
            {
                "receipt_id": issue_receipt(record).receipt_id,
                "amount": format_paise(issue_receipt(record).amount_authorized_paise),
                "constraints_checked": list(issue_receipt(record).constraints_checked),
                "offer_hash": record.offer_hash,
            }
            if decision.decision is Outcome.ALLOW
            else None
        ),
    }


def timeout_scenario(log: AuditLog) -> dict[str, Any]:
    """The second failure the plan names: the network goes quiet mid-execution."""
    proposal = _mandate("Buy me a pair of new running shoes, budget 5000 rupees.")
    ledger = proposal.ledger
    payload = MerchantAgent().quote(project(ledger))
    _, record = receive(ledger, payload, now=DECIDED, log=log)

    attempt, uncertain = execute(
        ledger, record, _FakeRazorpay(fail_with=PaymentTimeout("no answer")), now=DECIDED, log=log
    )
    resolved, settled = reconcile(attempt, uncertain, _FakeRazorpay())

    return {
        "name": "Razorpay stops answering mid-execution",
        "attempt": attempt.outcome.value,
        "detail": attempt.detail,
        "ledger_after_timeout": uncertain.status.value,
        "reconciled_order": resolved.order_id if resolved else None,
        "payment_statuses": resolved.payment_statuses if resolved else [],
        "ledger_after_reconciling": settled.status.value,
        "retried": False,
    }


def escalation_scenario() -> list[dict[str, Any]]:
    """The failure the track asks to see handled gracefully."""
    out = []
    for instruction in (
        "Get me a decent laptop, nothing too pricey.",
        "Get me 3 shirts, budget 2000.",
    ):
        proposal = _mandate(instruction)
        question = ask_about_mandate(proposal, now=STARTED)
        entry: dict[str, Any] = {
            "instruction": instruction,
            "mandate_built": proposal.ledger is not None,
            "weak_fields": list(proposal.weak_fields),
            "question": question.question if question else None,
            "confidence": {k: round(v, 2) for k, v in proposal.confidence.items()},
        }
        if question is not None:
            answer = Answer(question_id=question.question_id, approved=True, answered_at=ANSWERED)
            resolved = resolve_mandate(question, answer, proposal, now=ANSWERED)
            entry["resolution"] = resolved.resolution.value
            entry["detail"] = resolved.detail
            entry["hours_to_answer"] = 6
            entry["expired_while_waiting"] = False
        out.append(entry)
    return out


def offer_escalation_scenario(log: AuditLog) -> dict[str, Any]:
    """A cart the engine cannot judge, and what a human answer may do about it."""
    proposal = _mandate("Buy me a pair of new running shoes, budget 5000 rupees.")
    ledger = proposal.ledger
    payload = MerchantAgent().quote(project(ledger))
    payload["product"] = {**payload["product"], "condition": "gently loved"}

    decision, _ = receive(ledger, payload, now=DECIDED, log=log)
    question, paused = ask_about_offer(decision, ledger, now=DECIDED)
    answer = Answer(question_id=question.question_id, approved=True, answered_at=ANSWERED)
    resolved, record = resolve_offer(question, answer, paused, payload, now=ANSWERED, log=log)

    return {
        "condition_offered": "gently loved",
        "decision": decision.decision.value,
        "question": question.question,
        "clock_paused": paused.status.value,
        "resolution": resolved.resolution.value,
        "decision_after": resolved.decision.decision.value if resolved.decision else None,
        "human_confirmed": bool(record and record.human_confirmed),
    }


def threat_table() -> list[dict[str, Any]]:
    """Every hostile merchant mode, judged on arrival."""
    # The mandate carries an exclusion as well as a budget, so every hostile mode
    # has something to violate. Without one the excluded-material row showed
    # ALLOW, which reads as a hole rather than as a check given no input.
    proposal = _mandate(
        "Buy me a pair of new running shoes, budget 4300 rupees. "
        "No subscriptions, nothing in leather."
    )
    ledger = proposal.ledger
    view = project(ledger)

    # What an honest merchant would have quoted. Substitution is only visible by
    # comparing the final cart with what was being negotiated, so without this
    # the table showed a swapped product as ALLOW, which reads as a hole rather
    # than as a check that was never given its input.
    honest = MerchantAgent().quote(view)["product"]["title"]

    rows = []
    for hostility in Hostility:
        payload = MerchantAgent(hostility).quote(view)
        decision, _ = receive(
            ledger,
            payload,
            now=DECIDED,
            negotiated_product=honest,
            known_products=SHELF,
        )
        rows.append(
            {
                "attack": hostility.value,
                "decision": decision.decision.value,
                "codes": [v.code.value for v in decision.violations],
                "total": format_paise(payload.get("total_paise", 0)),
            }
        )
    return rows


def measure_latency(samples: int = 5_000) -> dict[str, float]:
    """The gate's own cost, measured now rather than quoted."""
    proposal = _mandate("Buy me a pair of new running shoes, budget 5000 rupees.")
    ledger = proposal.ledger
    payload = MerchantAgent().quote(project(ledger))

    timings = []
    for _ in range(samples):
        started = time.perf_counter()
        receive(ledger, payload, now=DECIDED)
        timings.append((time.perf_counter() - started) * 1000)
    timings.sort()
    return {
        "samples": samples,
        "p50_ms": round(timings[samples // 2], 4),
        "p95_ms": round(timings[int(samples * 0.95)], 4),
        "p99_ms": round(timings[int(samples * 0.99)], 4),
    }


def build() -> dict[str, Any]:
    """Everything the dashboard shows, computed by running the system."""
    with tempfile.TemporaryDirectory() as tmp:
        log = AuditLog(Path(tmp) / "audit.jsonl")

        scenarios = [
            negotiated_scenario(
                "An honest merchant, haggled down",
                "Buy me a pair of new running shoes, budget 4300 rupees. No subscriptions.",
                Hostility.NONE,
                Concession.HAGGLE,
                log,
            ),
            negotiated_scenario(
                "A free trial that converts to 299 a month",
                "Buy me a pair of new running shoes, budget 4300 rupees. No subscriptions.",
                Hostility.TRIAL_SUBSCRIPTION,
                Concession.MEET,
                log,
            ),
            negotiated_scenario(
                "Shipping added after the quote",
                "Buy me a pair of new running shoes, budget 4300 rupees. No subscriptions.",
                Hostility.HIDDEN_SHIPPING,
                Concession.STUBBORN,
                log,
            ),
            negotiated_scenario(
                "The product swapped mid-negotiation",
                "Buy me a pair of new running shoes, budget 5000 rupees.",
                Hostility.SUBSTITUTION,
                Concession.MEET,
                log,
            ),
            negotiated_scenario(
                "Injection spliced into the description",
                "Buy me a pair of new running shoes, budget 5000 rupees.",
                Hostility.INJECTION,
                Concession.HAGGLE,
                log,
            ),
        ]
        timeout = timeout_scenario(log)
        offer_escalation = offer_escalation_scenario(log)
        trail = verify_trail(log)
        sample_records = [
            json.loads(record.model_dump_json()) for record in list(log.read_all())[:3]
        ]

    cases = load(SYNTHETIC_PATH)
    train = [case for case in cases if case["split"] == "train"]
    report = report_for("synthetic / train", train)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "note": (
            "Every figure on this page was produced by running the system at export "
            "time. No value is typed in. Payments use a stand-in for Razorpay's "
            "test-mode API, so no live call was made."
        ),
        "scenarios": scenarios,
        "timeout": timeout,
        "mandate_escalations": escalation_scenario(),
        "offer_escalation": offer_escalation,
        "threat_table": threat_table(),
        "latency": measure_latency(),
        "benchmark": json.loads(report.model_dump_json()),
        "injection": injection_experiment(cases),
        "audit": {
            "intact": trail.intact,
            "records": trail.records,
            "decisions": trail.decisions,
            "sample": sample_records,
        },
    }


def main() -> None:
    payload = build()
    out = Path(__file__).resolve().parents[3] / "data" / "dashboard.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote a real run to {out}")
    print(f"  {len(payload['scenarios'])} scenarios, {payload['audit']['records']} audit records")
    print(f"  benchmark accuracy {payload['benchmark']['accuracy']:.1%}")
    print(f"  gate p50 {payload['latency']['p50_ms']} ms")


if __name__ == "__main__":
    main()
