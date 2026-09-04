"""What the bounded merchant view is actually worth, in rupees.

The track asks builders to grow a merchant's revenue and make them transactable
by an AI buyer. Those are two different numbers and this file measures both.

**Merchants gain the channel.** A merchant with no way to verify an agent's
claim either refuses agent traffic and loses the orders, or accepts it blind and
carries every dispute. The number is legitimate orders completed, and its
inverse, the value of good orders wrongly refused.

**Users keep the difference between the quote and the ceiling.** CLAUDE.md
predicts that a merchant who can see max_total_paise quotes just under it every
time, which turns the guard into the mechanism by which the user overpays. That
is an assertion until somebody runs it both ways, so this runs it both ways: the
same mandates, the same catalog, the same negotiation, and the only thing that
changes is whether the merchant was told the limit.

Nothing here is a simulation of a market. It measures one specific claim about
one specific design decision, which is all it is quoted as measuring.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..buyer import BuyerAgent
from ..core.enums import Category, Condition, Outcome
from ..core.intent import HardConstraints, IntentLedger
from ..core.money import format_paise, from_rupees
from ..gate import receive
from ..merchant import CATALOG, Concession, MerchantAgent, MerchantView

STARTED = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
DECIDED = STARTED + timedelta(minutes=5)


class ExposedMerchant(MerchantAgent):
    """A merchant that was told the ceiling, and prices to it.

    This is the counterfactual, not a hostile mode. Quoting just under a limit
    you can see is ordinary commercial behaviour; it is only a problem because
    the limit was never meant to be visible. The margin below the ceiling is
    what stops the quote reading as suspiciously exact.
    """

    def __init__(self, ceiling_paise: int, margin_bps: int = 100, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.ceiling_paise = ceiling_paise
        self.margin_bps = margin_bps

    def _priced_to_ceiling(self) -> int:
        return self.ceiling_paise - (self.ceiling_paise * self.margin_bps // 10_000)

    def quote(self, view: MerchantView) -> dict[str, Any] | None:
        payload = super().quote(view)
        if payload is None:
            return None
        target = self._priced_to_ceiling()
        product = payload["line_items"][0]
        if product["amount_paise"] >= target:
            return payload  # already dearer than the ceiling; nothing to gain
        product["amount_paise"] = target
        payload["total_paise"] = sum(item["amount_paise"] for item in payload["line_items"])
        return payload

    def counter(self, view: MerchantView, previous: dict, target_paise: int) -> dict:
        """Concedes nothing. Knowing the ceiling removes the reason to."""
        return previous


def mandates(count: int, seed: int = 20260904) -> list[IntentLedger]:
    """Mandates whose ceilings sit plausibly above the catalog, not on it."""
    rng = random.Random(seed)
    built = []
    for index in range(count):
        item = rng.choice([i for i in CATALOG if i.condition is Condition.NEW])
        headroom = rng.randrange(200, 4_000, 50)
        built.append(
            IntentLedger(
                intent_id=f"int_rev_{index:04d}",
                raw_instruction=f"Buy a {item.title.lower()} within budget",
                hard=HardConstraints(
                    category=Category(item.category),
                    max_total_paise=item.price_paise + from_rupees(headroom),
                    condition=Condition.NEW,
                ),
                status="ACTIVE",
                created_at=STARTED,
            )
        )
    return built


def _run_arm(ledgers: list[IntentLedger], *, exposed: bool) -> dict[str, Any]:
    paid: list[int] = []
    refused = 0
    for ledger in ledgers:
        merchant: MerchantAgent = (
            ExposedMerchant(ledger.hard.max_total_paise, concession=Concession.HAGGLE)
            if exposed
            else MerchantAgent(concession=Concession.HAGGLE)
        )
        negotiation = BuyerAgent(ledger).negotiate(merchant)
        if negotiation.final_payload is None:
            refused += 1
            continue
        decision, _ = receive(ledger, negotiation.final_payload, now=DECIDED)
        if decision.decision is Outcome.ALLOW:
            paid.append(negotiation.final_payload["total_paise"])
        else:
            refused += 1

    total = sum(paid)
    return {
        "orders_completed": len(paid),
        "orders_refused": refused,
        "total_paid_paise": total,
        "average_paid_paise": total // len(paid) if paid else 0,
    }


def compare(count: int = 200) -> dict[str, Any]:
    """The same mandates, twice. Only the merchant's knowledge changes."""
    ledgers = mandates(count)
    hidden = _run_arm(ledgers, exposed=False)
    exposed = _run_arm(ledgers, exposed=True)

    ceilings = sum(ledger.hard.max_total_paise for ledger in ledgers)
    difference = exposed["average_paid_paise"] - hidden["average_paid_paise"]
    return {
        "mandates": count,
        "total_authorised_paise": ceilings,
        "hidden": hidden,
        "exposed": exposed,
        "extra_paid_per_order_paise": difference,
        "extra_paid_total_paise": (exposed["total_paid_paise"] - hidden["total_paid_paise"]),
        "share_of_ceiling_hidden": (hidden["total_paid_paise"] / ceilings if ceilings else 0.0),
        "share_of_ceiling_exposed": (exposed["total_paid_paise"] / ceilings if ceilings else 0.0),
        "claim": (
            "The same mandates, catalog and negotiation in both arms. The only "
            "difference is whether the merchant was told max_total_paise."
        ),
    }


def render(result: dict[str, Any]) -> str:
    hidden, exposed = result["hidden"], result["exposed"]
    return "\n".join(
        [
            f"=== the ceiling, hidden and exposed ===  {result['mandates']} mandates",
            "",
            f"{'':<22}{'hidden':>16}{'exposed':>16}",
            f"{'orders completed':<22}{hidden['orders_completed']:>16}"
            f"{exposed['orders_completed']:>16}",
            f"{'average paid':<22}{format_paise(hidden['average_paid_paise']):>16}"
            f"{format_paise(exposed['average_paid_paise']):>16}",
            f"{'total paid':<22}{format_paise(hidden['total_paid_paise']):>16}"
            f"{format_paise(exposed['total_paid_paise']):>16}",
            f"{'share of ceiling':<22}{result['share_of_ceiling_hidden']:>15.1%}"
            f"{result['share_of_ceiling_exposed']:>16.1%}",
            "",
            f"  the user pays {format_paise(result['extra_paid_per_order_paise'])} more per order "
            f"when the merchant can see the limit",
            f"  {format_paise(result['extra_paid_total_paise'])} across "
            f"{result['mandates']} orders",
            "",
            f"  {result['claim']}",
        ]
    )


def main() -> None:
    result = compare()
    print(render(result))
    out = Path(__file__).resolve().parents[3] / "data" / "revenue.json"
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
