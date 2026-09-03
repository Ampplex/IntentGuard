"""Shared fixtures. Every amount here is written in integer paise or via
from_rupees, never as a decimal literal -- tests/core/test_no_floats.py scans
this directory to keep it that way.
"""

from __future__ import annotations

from datetime import UTC, datetime

from intentguard.core import (
    Category,
    Condition,
    HardConstraints,
    IntentLedger,
    LedgerStatus,
    LineItem,
    LineItemKind,
    Offer,
    Product,
    RecurrenceInterval,
    RecurringCharge,
    SoftPreferences,
    from_rupees,
)

CREATED_AT = datetime(2026, 9, 4, 10, 0, 0, tzinfo=UTC)


def a_ledger(**overrides) -> IntentLedger:
    hard = HardConstraints(
        category=Category.FOOTWEAR,
        max_total_paise=from_rupees(5000),
        quantity=1,
        condition=Condition.NEW,
    )
    base = {
        "intent_id": "int_001",
        "raw_instruction": "buy me a pair of running shoes under 5000 rupees",
        "hard": hard,
        "soft": SoftPreferences(brand="Asics", colour="blue", delivery_speed="standard"),
        "confidence": {"max_total_paise": 0.98, "category": 0.91},
        "status": LedgerStatus.ACTIVE,
        "created_at": CREATED_AT,
    }
    return IntentLedger(**{**base, **overrides})


def an_offer(**overrides) -> Offer:
    base = {
        "offer_id": "off_001",
        "product": Product(
            product_id="sku_77",
            title="Asics Gel-Contend 9",
            category="footwear",
            condition="new",
            brand="Asics",
            colour="blue",
        ),
        "quantity": 1,
        "currency": "INR",
        "line_items": [
            LineItem(
                label="Gel-Contend 9", amount_paise=from_rupees(4200), kind=LineItemKind.PRODUCT
            ),
            LineItem(label="Delivery", amount_paise=0, kind=LineItemKind.SHIPPING),
        ],
        "total_paise": from_rupees(4200),
        "raw_description": "Free delivery. Ships in two days.",
    }
    return Offer(**{**base, **overrides})


def a_trial_recurrence() -> RecurringCharge:
    """The trap case: costs nothing today, converts later."""
    return RecurringCharge(
        label="ShoeCare protection plan",
        amount_paise=0,
        interval=RecurrenceInterval.MONTHLY,
        starts_after_days=30,
    )
