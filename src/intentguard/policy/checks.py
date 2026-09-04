"""The individual constraint checks.

Every function here takes data and returns violations. None of them decide an
outcome, none of them stop early, and none of them read a clock -- the moment of
evaluation arrives as an argument so that the same inputs always produce the
same answer.

Each check returns a list rather than an optional single violation because the
specification requires every violation to be reported, not the first one found.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ..core.decision import Violation
from ..core.enums import Category, Condition, LedgerStatus, LineItemKind, Outcome, QuantityMode
from ..core.intent import IntentLedger
from ..core.money import format_paise, sum_paise
from ..core.offer import LineItem, Offer
from ..core.violations import DEFAULT_OUTCOME, ViolationCode, explain
from .normalise import to_category, to_condition


def _violation(code: ViolationCode, *, field=None, expected=None, observed=None) -> Violation:
    return Violation(
        code=code,
        outcome=DEFAULT_OUTCOME[code],
        explanation=explain(code, expected=expected, observed=observed),
        field=field,
        expected=expected,
        observed=observed,
    )


def _as_utc(moment: datetime) -> datetime:
    """A naive timestamp is read as UTC rather than rejected or guessed at."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


# --- ledger state ---------------------------------------------------------


def check_ledger_state(ledger: IntentLedger, now: datetime) -> list[Violation]:
    found: list[Violation] = []
    status = ledger.status

    # EXECUTION_UNCERTAIN is treated as spent: in both states a payment attempt
    # has consumed the authorization, so the correct behaviour is identical.
    # Recorded as an interpretation in SPEC-DECISIONS.md, Amendment 1.
    if status in (LedgerStatus.SPENT, LedgerStatus.EXECUTION_UNCERTAIN):
        found.append(_violation(ViolationCode.LEDGER_ALREADY_SPENT, field="status"))

    if status is LedgerStatus.AWAITING_CONFIRMATION:
        found.append(_violation(ViolationCode.LEDGER_NOT_CONFIRMED, field="status"))

    # The deadline is computable whichever way the mandate expired, and both
    # paths need it: a person told their authorization has run out is owed the
    # time it ran out at, not a sentence with a hole where the time should be.
    deadline = _as_utc(ledger.created_at) + timedelta(seconds=ledger.ttl_seconds)
    moment = _as_utc(now)

    # TTL is paused while a human is being asked, so only a live mandate ages.
    expired = status is LedgerStatus.EXPIRED or (
        status is LedgerStatus.ACTIVE and moment >= deadline
    )
    if expired:
        found.append(
            _violation(
                ViolationCode.LEDGER_EXPIRED,
                field="ttl_seconds",
                expected=deadline.isoformat(),
                observed=moment.isoformat(),
            )
        )
    return found


# --- arithmetic -----------------------------------------------------------


def chargeable_total(offer: Offer) -> int:
    """What the user actually ends up paying, taken at its highest reading.

    A financed offer is checked on the sum of its instalments, because interest
    makes the real cost higher than the sticker price and the authorization is
    about money leaving the account.

    The maximum matters as much as the sum. Everything this function reads is
    supplied by an untrusted merchant, so instalment terms are never allowed to
    *lower* the figure the ceiling is checked against -- otherwise one instalment
    of one paisa attached to a ninety thousand rupee cart would be compared
    against the paisa. Untrusted input may raise the number under scrutiny. It
    may never choose it.
    """
    if offer.emi is None:
        return offer.total_paise
    financed = offer.emi.installment_paise * offer.emi.installment_count
    return max(offer.total_paise, financed)


def check_currency(ledger: IntentLedger, offer: Offer) -> list[Violation]:
    wanted = ledger.hard.currency.strip().upper()
    offered = offer.currency.strip().upper()
    if wanted == offered:
        return []
    return [
        _violation(
            ViolationCode.CURRENCY_MISMATCH,
            field="currency",
            expected=wanted,
            observed=offered,
        )
    ]


def check_totals(ledger: IntentLedger, offer: Offer, checked: int) -> list[Violation]:
    found: list[Violation] = []
    line_sum = sum_paise(item.amount_paise for item in offer.line_items)

    if offer.total_paise != line_sum:
        found.append(
            _violation(
                ViolationCode.TOTAL_MISMATCH,
                field="total_paise",
                expected=format_paise(line_sum),
                observed=format_paise(offer.total_paise),
            )
        )

    lowest = min(line_sum, offer.total_paise)
    if lowest < 0:
        found.append(
            _violation(
                ViolationCode.NEGATIVE_TOTAL,
                field="total_paise",
                observed=format_paise(lowest),
            )
        )

    if checked > ledger.hard.max_total_paise:
        found.append(
            _violation(
                ViolationCode.TOTAL_EXCEEDS_MAX,
                field="max_total_paise",
                expected=format_paise(ledger.hard.max_total_paise),
                observed=format_paise(checked),
            )
        )
    return found


def check_quantity(ledger: IntentLedger, offer: Offer) -> list[Violation]:
    wanted = ledger.hard.quantity
    mode = ledger.hard.quantity_mode
    offered = offer.quantity

    breached = (
        (mode is QuantityMode.EXACT and offered != wanted)
        or (mode is QuantityMode.AT_MOST and offered > wanted)
        or (mode is QuantityMode.AT_LEAST and offered < wanted)
    )
    if not breached:
        return []

    phrasing = {
        QuantityMode.EXACT: f"exactly {wanted}",
        QuantityMode.AT_MOST: f"at most {wanted}",
        QuantityMode.AT_LEAST: f"at least {wanted}",
    }[mode]
    return [
        _violation(
            ViolationCode.QUANTITY_MISMATCH,
            field="quantity",
            expected=phrasing,
            observed=str(offered),
        )
    ]


# --- obligations ----------------------------------------------------------


def check_recurrence(ledger: IntentLedger, offer: Offer) -> list[Violation]:
    """Any future-dated obligation counts, whatever it costs today.

    A zero-cost line item with a non-empty recurring block is the trap this
    check exists for: the total looks legitimate and the obligation is the
    problem. addons_allowed never reaches this check -- it relaxes cost, and
    only recurring_allowed can authorize an ongoing charge.
    """
    if not offer.recurring or ledger.hard.recurring_allowed:
        return []
    described = "; ".join(
        f"{charge.label}, {format_paise(charge.amount_paise)} {charge.interval.value}"
        + (f" starting in {charge.starts_after_days} days" if charge.starts_after_days else "")
        for charge in offer.recurring
    )
    return [
        _violation(
            ViolationCode.RECURRING_NOT_AUTHORIZED,
            field="recurring",
            observed=described,
        )
    ]


def check_emi(ledger: IntentLedger, offer: Offer) -> list[Violation]:
    if offer.emi is None or ledger.hard.emi_allowed:
        return []
    terms = offer.emi
    return [
        _violation(
            ViolationCode.EMI_NOT_AUTHORIZED,
            field="emi",
            observed=(
                f"{terms.installment_count} instalments of {format_paise(terms.installment_paise)}"
            ),
        )
    ]


def _addon_is_permitted(item: LineItem, ledger: IntentLedger) -> bool:
    """The cost clause, stated as a clause rather than an early return.

    Written this way so the shape of the rule survives contact with the other
    two clauses. addons_allowed relaxes cost and nothing else; it must not
    become a switch that skips add-on checking altogether.
    """
    costs_nothing = item.amount_paise == 0
    return costs_nothing or ledger.hard.addons_allowed


def check_addons(ledger: IntentLedger, offer: Offer) -> list[Violation]:
    """The cost clause of the add-on rule, one violation per offending add-on.

    An add-on is permitted if it costs nothing, introduces no ongoing
    obligation, and is not a distinct product needing its own authorization.
    Cost is arithmetic and lives here. Ongoing obligations are caught by the
    recurrence check whatever their source. The third clause needs a judgement
    about what an add-on actually is, which is not something an integer
    comparison can make, so it is deferred to semantic/ at stage 7 rather than
    approximated here.
    """
    add_ons = [item for item in offer.line_items if item.kind is LineItemKind.ADDON]
    return [
        _violation(ViolationCode.ADDON_NOT_AUTHORIZED, field="line_items", observed=item.label)
        for item in add_ons
        if not _addon_is_permitted(item, ledger)
    ]


# --- product --------------------------------------------------------------


def check_condition(ledger: IntentLedger, offer: Offer) -> list[Violation]:
    wanted = ledger.hard.condition
    if wanted is None:
        return []

    raw = offer.product.condition
    offered = to_condition(raw)
    if offered is None:
        return [
            _violation(
                ViolationCode.UNCLASSIFIABLE_CONDITION,
                field="condition",
                observed=raw if raw is not None else "nothing at all",
            )
        ]
    if offered is not wanted:
        return [
            _violation(
                ViolationCode.CONDITION_MISMATCH,
                field="condition",
                expected=Condition(wanted).value,
                observed=offered.value,
            )
        ]
    return []


def check_category(ledger: IntentLedger, offer: Offer) -> list[Violation]:
    raw = offer.product.category
    offered = to_category(raw)
    if offered is None:
        return [
            _violation(
                ViolationCode.UNCLASSIFIABLE_CATEGORY,
                field="category",
                observed=raw if raw else "nothing at all",
            )
        ]
    if offered is not Category(ledger.hard.category):
        return [
            _violation(
                ViolationCode.CATEGORY_MISMATCH,
                field="category",
                expected=Category(ledger.hard.category).value,
                observed=offered.value,
            )
        ]
    return []


def outcome_for(violations: list[Violation]) -> Outcome:
    """A definite violation outranks an uncertain one.

    Knowing the total is over the ceiling settles the matter even when some
    other field could not be judged, so BLOCK wins over ESCALATE.
    """
    outcomes = {violation.outcome for violation in violations}
    if Outcome.BLOCK in outcomes:
        return Outcome.BLOCK
    if Outcome.ESCALATE in outcomes:
        return Outcome.ESCALATE
    return Outcome.ALLOW
