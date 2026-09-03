"""Schemas, money helpers and violation codes. No decision logic lives here."""

from .base import StrictModel
from .decision import Decision, DriftItem, DriftReport, LatencyBreakdown, Violation
from .enums import (
    Category,
    Condition,
    LedgerStatus,
    LineItemKind,
    Outcome,
    QuantityMode,
    RecurrenceInterval,
)
from .hashing import canonical_json, content_hash, offer_hash
from .intent import ConfidenceField, HardConstraints, IntentLedger, SoftPreferences
from .money import PAISE_PER_RUPEE, format_paise, from_rupees, parse_rupees, sum_paise
from .offer import EmiTerms, LineItem, Offer, Product, RecurringCharge
from .violations import (
    DEFAULT_OUTCOME,
    ESCALATING_CODES,
    EXPLANATION_TEMPLATES,
    ViolationCode,
)

__all__ = [
    "DEFAULT_OUTCOME",
    "ESCALATING_CODES",
    "EXPLANATION_TEMPLATES",
    "PAISE_PER_RUPEE",
    "Category",
    "Condition",
    "ConfidenceField",
    "Decision",
    "DriftItem",
    "DriftReport",
    "EmiTerms",
    "HardConstraints",
    "IntentLedger",
    "LatencyBreakdown",
    "LedgerStatus",
    "LineItem",
    "LineItemKind",
    "Offer",
    "Outcome",
    "Product",
    "QuantityMode",
    "RecurrenceInterval",
    "RecurringCharge",
    "SoftPreferences",
    "StrictModel",
    "Violation",
    "ViolationCode",
    "canonical_json",
    "content_hash",
    "format_paise",
    "from_rupees",
    "offer_hash",
    "parse_rupees",
    "sum_paise",
]
