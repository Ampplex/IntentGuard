"""The individual constraint checks.

Every function here takes data and returns violations. None of them decide an
outcome, none of them stop early, and none of them read a clock -- the moment of
evaluation arrives as an argument so that the same inputs always produce the
same answer.

Each check returns a list rather than an optional single violation because the
specification requires every violation to be reported, not the first one found.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from ..core.decision import Violation
from ..core.enums import Category, Condition, LedgerStatus, LineItemKind, Outcome, QuantityMode
from ..core.intent import IntentLedger
from ..core.money import format_paise, sum_paise
from ..core.offer import LineItem, Offer
from ..core.violations import (
    CONFIDENCE_GATED_FIELDS,
    DEFAULT_OUTCOME,
    ViolationCode,
    explain,
)
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


def _searchable_text(offer: Offer) -> str:
    """Everything about an offer a person would read to spot an excluded term."""
    parts = [
        offer.product.title,
        offer.product.brand or "",
        offer.product.colour or "",
        *(item.label for item in offer.line_items),
    ]
    return " ".join(parts).lower()


# "leather-free" contains "leather" and means the opposite of it. A literal
# matcher that ignores this blocks legitimate orders, and a false block costs a
# merchant real revenue, which is the metric this project cares most about.
_NEGATED = re.compile(r"(?:\bno\s+|\bnon[-\s]?|\bwithout\s+|\bfree\s+of\s+)$")
_NEGATING_SUFFIX = re.compile(r"^[-\s]?free\b")


def check_exclusions(ledger: IntentLedger, offer: Offer) -> list[Violation]:
    """Terms the user ruled out, matched literally.

    This is a deterministic floor rather than a complete answer. It catches a
    merchant offering the excluded thing by name, which is the common case, and
    it will miss a synonym. Recognising that "cowhide" satisfies an exclusion of
    "leather" needs judgement about words, which belongs to semantic/ and
    escalates rather than blocks.
    """
    if not ledger.hard.exclusions:
        return []

    haystack = _searchable_text(offer)
    found: list[Violation] = []
    for term in ledger.hard.exclusions:
        needle = term.strip().lower()
        if not needle:
            continue
        for match in re.finditer(rf"\b{re.escape(needle)}\b", haystack):
            before = haystack[: match.start()]
            after = haystack[match.end() :]
            if _NEGATED.search(before) or _NEGATING_SUFFIX.match(after):
                continue
            found.append(
                _violation(
                    ViolationCode.EXCLUDED_ITEM,
                    field="exclusions",
                    expected=term,
                    observed=offer.product.title,
                )
            )
            break
    return found


def _identity_key(text: str) -> str:
    """Fold punctuation and spacing so "Gel-Contend 9" and "gel contend 9" agree."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def check_product_identity(ledger: IntentLedger, offer: Offer) -> list[Violation]:
    """Did the merchant ship the product the user actually named?

    Only runs when the mandate pins one. This is an exact comparison after
    folding punctuation, with no model and no similarity score, which is what
    makes it safe to block on. Where nothing is pinned, a suspected swap is
    semantic/'s to raise and escalates instead.
    """
    reference = ledger.hard.product_ref
    if not reference:
        return []

    wanted = _identity_key(reference)
    offered = {_identity_key(offer.product.product_id), _identity_key(offer.product.title)}
    if wanted in offered:
        return []
    return [
        _violation(
            ViolationCode.PRODUCT_SUBSTITUTION,
            field="product_ref",
            expected=reference,
            observed=offer.product.title,
        )
    ]


def check_confidence(ledger: IntentLedger, threshold: float) -> list[Violation]:
    """Was the instruction read well enough to spend against?

    A deterministic comparison of numbers already stored on the mandate against
    a threshold passed in. No model runs here and none is consulted; the score
    was computed when the mandate was built, and this only reads it.

    The threshold is an argument rather than a constant so that recalibrating it
    is a change to data, not to the engine.
    """
    weak = sorted(
        name
        for name, score in ledger.confidence.items()
        if name in CONFIDENCE_GATED_FIELDS and score < threshold
    )
    if not weak:
        return []
    described = ", ".join(name.replace("_paise", "").replace("_", " ") for name in weak)
    return [
        _violation(
            ViolationCode.LOW_CONFIDENCE,
            field="confidence",
            observed=f"the {described} could not be read from your instruction with confidence",
        )
    ]


def check_mandate_feasibility(ledger: IntentLedger) -> list[Violation]:
    """Does the mandate contradict itself, before any offer is even considered?

    A contradiction is not the merchant's fault and it is not low confidence
    either -- the extractor can be entirely certain it read "buy me new shoes,
    nothing new" correctly. It is a question only the user can settle, so it
    escalates.

    Only contradictions the schema can actually express are checked. A per-unit
    limit that conflicts with an order cap is not among them, because there is
    one ceiling field; that ambiguity is caught earlier, at extraction, and
    escalates there.
    """
    hard = ledger.hard
    excluded = {term.strip().lower() for term in hard.exclusions if term.strip()}
    if not excluded and hard.max_total_paise > 0:
        return []

    conflicts: list[str] = []
    if hard.condition is not None and Condition(hard.condition).value in excluded:
        conflicts.append(f"you asked for {Condition(hard.condition).value} and also ruled it out")
    if hard.product_ref:
        reference = hard.product_ref.lower()
        for term in sorted(excluded):
            if re.search(rf"\b{re.escape(term)}\b", reference):
                conflicts.append(f"you named {hard.product_ref} and also ruled out {term}")
    if Category(hard.category).value in excluded:
        conflicts.append(f"you asked for {Category(hard.category).value} and also ruled it out")
    if hard.max_total_paise == 0:
        conflicts.append("the spending limit is nothing at all")

    if not conflicts:
        return []
    return [
        _violation(
            ViolationCode.MANDATE_INFEASIBLE,
            field="hard",
            observed="; ".join(conflicts),
        )
    ]


# Named so a compliance receipt can state what was actually checked rather than
# claiming "all constraints". A merchant defending a chargeback needs the list.
CHECKS_PERFORMED = (
    "mandate_state",
    "mandate_feasibility",
    "confidence",
    "currency",
    "totals",
    "quantity",
    "recurrence",
    "emi",
    "addons",
    "condition",
    "category",
    "product_identity",
    "exclusions",
)


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
