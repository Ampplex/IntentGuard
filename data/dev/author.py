"""Authors the confidence calibration set.

CLAUDE.md's stage 4 gate says confidence should correlate with correctness on
the gold set. SPEC-DECISIONS.md wins on contradiction and says gold is scored
once, at the end, and tuned on never. Both are satisfied by calibrating here
instead: this is a development set, written for this purpose, and it is the only
thing the 0.85 threshold is ever moved against.

Each case is an instruction and whether a defensible mandate can be built from
it. USABLE means the constraints are all stated plainly enough to act on. ASK
means at least one is not, and the correct behaviour is a question.

Like the gold author, this file imports nothing from intentguard.
"""

from __future__ import annotations

import json
from pathlib import Path

CASES: list[dict] = []


def case(instruction: str, verdict: str, why: str) -> None:
    assert verdict in {"USABLE", "ASK"}
    CASES.append({"instruction": instruction, "verdict": verdict, "why": why})


# --- plainly stated: a mandate can be built -------------------------------
case(
    "Buy me a pair of running shoes, budget 5000 rupees.",
    "USABLE",
    "category, bound and number all present",
)
case("Order a paperback novel for under Rs 700.", "USABLE", "explicit bound and currency")
case("Get wireless earphones for no more than 3000.", "USABLE", "explicit bound")
case("Buy a yoga mat, up to 1200 rupees all in.", "USABLE", "all in settles the per-unit question")
case("Order 2 cotton t-shirts, budget 1600 total.", "USABLE", "total settles the per-unit question")
case("Buy a refurbished laptop under 40000.", "USABLE", "condition and bound both explicit")
case("Get a table lamp under 2500 rupees.", "USABLE", "plain")
case("Buy a cricket bat, no more than 4000.", "USABLE", "plain bound")
case("Order a face serum under 1500, add-ons are fine.", "USABLE", "flag stated explicitly")
case("Buy a kettle for under 2000.", "USABLE", "plain")
case(
    "Get me up to 3 reams of paper, budget 1500.", "USABLE", "quantity mode and bound both explicit"
)
case("Order at least 4 bars of soap, under 600.", "USABLE", "quantity mode and bound both explicit")
case("Buy a backpack under 3000, nothing in leather.", "USABLE", "exclusion stated plainly")
case("Buy running shoes under 5000, no subscriptions.", "USABLE", "recurrence ruled out explicitly")
case("Get me 3 shirts under 2000 each.", "USABLE", "each marks the limit as per unit")
case("Order a wall clock, no more than 1500.", "USABLE", "plain")
case("Buy a phone charger under 1500, standard delivery is fine.", "USABLE", "plain")
case("Order a chess set under 3000.", "USABLE", "plain")
case("Buy a monitor under 14000.", "USABLE", "plain")
case("Get a coffee grinder, max 4500.", "USABLE", "max is a bound word")
case("Buy an open box television under 30000.", "USABLE", "condition and bound explicit")
case("Order a suitcase under 7000.", "USABLE", "plain")

# --- not stated plainly enough: the system must ask -----------------------
case(
    "Get me a decent laptop, nothing too pricey.",
    "ASK",
    "no defensible ceiling exists in the words",
)
case("Buy something nice for the office.", "ASK", "neither a ceiling nor a category")
case("Order lunch for the team.", "ASK", "no ceiling, no quantity, no size of team")
case(
    "Buy a few notebooks, keep it cheap.", "ASK", "a few is not a quantity, cheap is not a ceiling"
)
case("Replace my old headphones with something similar.", "ASK", "similar to a thing never seen")
case("Get me 3 shirts, budget 2000.", "ASK", "per unit or total is genuinely ambiguous")
case("Buy 4 mugs, budget 900.", "ASK", "same ambiguity, different words")
case("Get a good pair of boots, reasonable price.", "ASK", "reasonable is not a number")
case("Order some protein powder, not too expensive.", "ASK", "some, and no ceiling")
case("Buy the cheapest laptop that is any good.", "ASK", "cheapest is a strategy, not a limit")
case("Get me a couple of water bottles when you can.", "ASK", "a couple hedges the quantity")
case("Buy a phone, around 20000 or so.", "ASK", "around and or so both hedge the ceiling")
case("Order a birthday gift, roughly 2000.", "ASK", "roughly hedges, and gift is not a category")
case("Buy me whatever running shoes look best.", "ASK", "no ceiling at all")
case("Get a premium coffee machine.", "ASK", "premium is not a price")
case("Order 2 jackets, budget 8000.", "ASK", "per unit or total is ambiguous")
case("Buy several pairs of socks under 800.", "ASK", "several hedges the quantity")
case("Get a laptop bag, maybe 3000.", "ASK", "maybe hedges the ceiling")

if __name__ == "__main__":
    out = Path(__file__).parent / "calibration.json"
    out.write_text(json.dumps(CASES, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    usable = sum(1 for c in CASES if c["verdict"] == "USABLE")
    print(f"wrote {len(CASES)} cases: {usable} usable, {len(CASES) - usable} ask")
