"""The deterministic engine.

This module is the thesis. Given a mandate and an offer it returns the same
answer every time, computed from integers and enumerated values, with no model
anywhere in the path. Nothing here can be persuaded.

Two properties are enforced from outside rather than promised here:
tests/structure/test_import_graph.py fails if this package reaches for a model
client or a sibling package, and fails if any file in it reads a clock.

Every check runs. None of them stop early, because an offer that breaks the
budget and adds a subscription has to say both -- a user who fixes the price and
resubmits should not discover the subscription on the second attempt.
"""

from __future__ import annotations

from datetime import datetime

from ..core.decision import PolicyResult, Violation
from ..core.intent import IntentLedger
from ..core.offer import Offer
from . import checks


def evaluate(ledger: IntentLedger, offer: Offer, *, now: datetime) -> PolicyResult:
    """Decide whether this offer satisfies this mandate.

    ``now`` is a required argument and not a default, so that a caller cannot
    accidentally make the engine depend on when it happened to run.
    """
    checked_total = checks.chargeable_total(offer)
    violations: list[Violation] = [
        *checks.check_ledger_state(ledger, now),
        *checks.check_currency(ledger, offer),
        *checks.check_totals(ledger, offer, checked_total),
        *checks.check_quantity(ledger, offer),
        *checks.check_recurrence(ledger, offer),
        *checks.check_emi(ledger, offer),
        *checks.check_addons(ledger, offer),
        *checks.check_condition(ledger, offer),
        *checks.check_category(ledger, offer),
        *checks.check_product_identity(ledger, offer),
        *checks.check_exclusions(ledger, offer),
    ]
    return PolicyResult(
        outcome=checks.outcome_for(violations),
        violations=violations,
        checked_total_paise=checked_total,
    )
