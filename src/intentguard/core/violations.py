"""Violation vocabulary.

This list is frozen at nineteen codes -- the sixteen set at stage 1 plus the
three added by Amendment 1. Adding a code requires an explicit amendment to
SPEC-DECISIONS.md, and tests/core/test_violations.py fails if the enum drifts
from the frozen sixteen. The stage 2 gate is "a test per violation code", which
is self-referential unless the list cannot quietly grow to match whatever got
implemented.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType

from .enums import Outcome


class ViolationCode(StrEnum):
    TOTAL_EXCEEDS_MAX = "TOTAL_EXCEEDS_MAX"
    TOTAL_MISMATCH = "TOTAL_MISMATCH"
    NEGATIVE_TOTAL = "NEGATIVE_TOTAL"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    RECURRING_NOT_AUTHORIZED = "RECURRING_NOT_AUTHORIZED"
    EMI_NOT_AUTHORIZED = "EMI_NOT_AUTHORIZED"
    ADDON_NOT_AUTHORIZED = "ADDON_NOT_AUTHORIZED"
    CONDITION_MISMATCH = "CONDITION_MISMATCH"
    CATEGORY_MISMATCH = "CATEGORY_MISMATCH"
    PRODUCT_SUBSTITUTION = "PRODUCT_SUBSTITUTION"
    LEDGER_EXPIRED = "LEDGER_EXPIRED"
    LEDGER_ALREADY_SPENT = "LEDGER_ALREADY_SPENT"
    LEDGER_NOT_CONFIRMED = "LEDGER_NOT_CONFIRMED"
    OFFER_MALFORMED = "OFFER_MALFORMED"
    UNMODELLED_FIELD = "UNMODELLED_FIELD"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    UNCLASSIFIABLE_CONDITION = "UNCLASSIFIABLE_CONDITION"
    UNCLASSIFIABLE_CATEGORY = "UNCLASSIFIABLE_CATEGORY"


ESCALATING_CODES = frozenset(
    {
        ViolationCode.UNMODELLED_FIELD,
        ViolationCode.LOW_CONFIDENCE,
        ViolationCode.UNCLASSIFIABLE_CONDITION,
        ViolationCode.UNCLASSIFIABLE_CATEGORY,
        ViolationCode.LEDGER_NOT_CONFIRMED,
    }
)

DEFAULT_OUTCOME = MappingProxyType(
    {
        code: (Outcome.ESCALATE if code in ESCALATING_CODES else Outcome.BLOCK)
        for code in ViolationCode
    }
)

# Written for a person about to lose money, not for a developer. Placeholders are
# filled by the engine with already-formatted values.
EXPLANATION_TEMPLATES = MappingProxyType(
    {
        ViolationCode.TOTAL_EXCEEDS_MAX: (
            "This order comes to {observed}, but you authorized at most {expected}. "
            "Nothing was charged."
        ),
        ViolationCode.TOTAL_MISMATCH: (
            "The seller's itemised charges add up to {expected}, but the amount they asked "
            "to charge is {observed}. Those do not agree, so nothing was charged."
        ),
        ViolationCode.NEGATIVE_TOTAL: (
            "After discounts this order totals {observed}, which is less than nothing. "
            "That is not a charge anyone can make, so nothing was charged."
        ),
        ViolationCode.CURRENCY_MISMATCH: (
            "You authorized payment in {expected}, but the seller quoted in {observed}. "
            "IntentGuard never converts between currencies, so nothing was charged."
        ),
        ViolationCode.QUANTITY_MISMATCH: (
            "You authorized {expected}, but this order is for {observed}."
        ),
        ViolationCode.RECURRING_NOT_AUTHORIZED: (
            "This order starts an ongoing charge you did not authorize: {observed}. "
            "A trial that costs nothing today still counts, because it converts later. "
            "Nothing was charged."
        ),
        ViolationCode.EMI_NOT_AUTHORIZED: (
            "This order splits payment into instalments you did not authorize: {observed}. "
            "Nothing was charged."
        ),
        ViolationCode.ADDON_NOT_AUTHORIZED: (
            "This order adds {observed}, which you did not authorize. Nothing was charged."
        ),
        ViolationCode.CONDITION_MISMATCH: (
            "You asked for an item in {expected} condition, but this one is {observed}."
        ),
        ViolationCode.CATEGORY_MISMATCH: (
            "You authorized a purchase in {expected}, but this item is listed under {observed}."
        ),
        ViolationCode.PRODUCT_SUBSTITUTION: (
            "The seller offered {observed} in place of {expected}. That is a different "
            "product from the one you authorized."
        ),
        ViolationCode.LEDGER_EXPIRED: (
            "Your authorization expired at {expected} and this offer arrived at {observed}. "
            "It needs authorizing again before anything can be charged."
        ),
        ViolationCode.LEDGER_ALREADY_SPENT: (
            "This authorization was already used for another order. Each one covers a "
            "single purchase."
        ),
        ViolationCode.UNMODELLED_FIELD: (
            "This offer contains something IntentGuard has no way to check: {observed}. "
            "Asking you rather than guessing."
        ),
        ViolationCode.LOW_CONFIDENCE: (
            "IntentGuard is not confident it read your instruction correctly ({observed}). "
            "Asking you before spending anything."
        ),
        ViolationCode.LEDGER_NOT_CONFIRMED: (
            "You have not confirmed this authorization yet, so nothing can be charged "
            "against it. Asking you to confirm before going any further."
        ),
        ViolationCode.OFFER_MALFORMED: (
            "The seller sent an order IntentGuard could not read: {observed}. Nothing was charged."
        ),
        ViolationCode.UNCLASSIFIABLE_CATEGORY: (
            "The seller lists this item under {observed}, which is not a category "
            "IntentGuard recognises. Asking you rather than guessing."
        ),
        ViolationCode.UNCLASSIFIABLE_CONDITION: (
            "The seller describes this item as {observed}, which is not a condition "
            "IntentGuard recognises. Asking you rather than guessing."
        ),
    }
)


def explain(
    code: ViolationCode, *, expected: str | None = None, observed: str | None = None
) -> str:
    """Fill a violation's template. Formatting, not judgement."""
    return EXPLANATION_TEMPLATES[code].format(expected=expected, observed=observed)
