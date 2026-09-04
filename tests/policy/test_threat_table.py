"""The threat table from the original concept, one test per row.

This file exists so the claim "we handle these" is a thing pytest proves rather
than a slide. Each test names the attack in the language of the table, builds the
mandate and the offer the table describes, and asserts the outcome the table
expects.

Where a row's outcome is right but the reasoning differs from the table, that is
noted in the test rather than smoothed over.
"""

from __future__ import annotations

from datetime import timedelta

from intentguard.core import (
    Category,
    Condition,
    EmiTerms,
    HardConstraints,
    IntentLedger,
    LedgerStatus,
    LineItem,
    LineItemKind,
    Offer,
    Outcome,
    Product,
    RecurrenceInterval,
    RecurringCharge,
    SoftPreferences,
    ViolationCode,
    from_rupees,
)
from intentguard.policy import evaluate
from tests.fixtures import CREATED_AT

NOW = CREATED_AT + timedelta(minutes=5)


def mandate(**hard) -> IntentLedger:
    """The user's instruction, extracted. Shoes under 5000 unless overridden."""
    base = {
        "category": Category.FOOTWEAR,
        "max_total_paise": from_rupees(5000),
        "quantity": 1,
        "condition": Condition.NEW,
    }
    return IntentLedger(
        intent_id="int_threat",
        raw_instruction="Buy me running shoes under 5000 rupees. Nothing else.",
        hard=HardConstraints(**{**base, **hard}),
        soft=SoftPreferences(delivery_speed="standard"),
        status=LedgerStatus.ACTIVE,
        created_at=CREATED_AT,
    )


def offer(
    items,
    *,
    quantity=1,
    currency="INR",
    total=None,
    recurring=(),
    emi=None,
    condition="new",
    title="Running shoes",
) -> Offer:
    line_items = [LineItem(label=lbl, amount_paise=amt, kind=kind) for lbl, amt, kind in items]
    return Offer(
        offer_id="off_threat",
        product=Product(
            product_id="sku_threat", title=title, category="footwear", condition=condition
        ),
        quantity=quantity,
        currency=currency,
        line_items=line_items,
        total_paise=total if total is not None else sum(i.amount_paise for i in line_items),
        recurring=list(recurring),
        emi=emi,
    )


def decide(led, off):
    result = evaluate(led, off, now=NOW)
    return result, {v.code for v in result.violations}


# --- rows the table expects to BLOCK --------------------------------------


def test_price_escalation() -> None:
    """5,000 -> 5,499."""
    result, codes = decide(
        mandate(), offer([("Running shoes", from_rupees(5499), LineItemKind.PRODUCT)])
    )
    assert result.outcome is Outcome.BLOCK
    assert ViolationCode.TOTAL_EXCEEDS_MAX in codes


def test_hidden_upsell() -> None:
    """4,500 + 799 protection. Two violations, not one: the add-on and the ceiling."""
    result, codes = decide(
        mandate(),
        offer(
            [
                ("Running shoes", from_rupees(4500), LineItemKind.PRODUCT),
                ("Protection plan", from_rupees(799), LineItemKind.ADDON),
            ]
        ),
    )
    assert result.outcome is Outcome.BLOCK
    assert {ViolationCode.ADDON_NOT_AUTHORIZED, ViolationCode.TOTAL_EXCEEDS_MAX} <= codes


def test_subscription_trap() -> None:
    """0 first month, then 299 a month. The total is legitimate; the obligation is not."""
    off = offer(
        [
            ("Running shoes", from_rupees(4499), LineItemKind.PRODUCT),
            ("First month free", 0, LineItemKind.ADDON),
        ],
        recurring=[
            RecurringCharge(
                label="Care plan",
                amount_paise=from_rupees(299),
                interval=RecurrenceInterval.MONTHLY,
                starts_after_days=30,
            )
        ],
    )
    result, codes = decide(mandate(), off)
    assert off.total_paise < from_rupees(5000), "the visible total must look compliant"
    assert result.outcome is Outcome.BLOCK
    assert ViolationCode.RECURRING_NOT_AUTHORIZED in codes


def test_quantity_manipulation() -> None:
    """1 item -> 2 items, deliberately kept inside the ceiling so quantity is the only fault."""
    result, codes = decide(
        mandate(),
        offer([("Running shoes x2", from_rupees(4600), LineItemKind.PRODUCT)], quantity=2),
    )
    assert result.outcome is Outcome.BLOCK
    assert codes == {ViolationCode.QUANTITY_MISMATCH}


def test_new_swapped_for_refurbished() -> None:
    """The table calls this product substitution. The engine calls it a condition mismatch.

    Same outcome, different reasoning, and the distinction matters: refurbished is a
    recognised condition, so this is a definite mismatch rather than an uncertainty.
    A genuinely different product is a separate check against product_ref.
    """
    result, codes = decide(
        mandate(),
        offer(
            [("Running shoes", from_rupees(4200), LineItemKind.PRODUCT)],
            condition="refurbished",
        ),
    )
    assert result.outcome is Outcome.BLOCK
    assert ViolationCode.CONDITION_MISMATCH in codes


def test_product_substitution_proper() -> None:
    """The other reading of that row: a different product entirely."""
    led = mandate(product_ref="Asics Gel-Contend 9")
    result, codes = decide(
        led,
        offer(
            [("Nike Revolution 7", from_rupees(4200), LineItemKind.PRODUCT)],
            title="Nike Revolution 7",
        ),
    )
    assert result.outcome is Outcome.BLOCK
    assert ViolationCode.PRODUCT_SUBSTITUTION in codes


def test_shipping_manipulation() -> None:
    """4,800 + 500 shipping. Shipping is inside the ceiling by definition."""
    result, codes = decide(
        mandate(),
        offer(
            [
                ("Running shoes", from_rupees(4800), LineItemKind.PRODUCT),
                ("Shipping", from_rupees(500), LineItemKind.SHIPPING),
            ]
        ),
    )
    assert result.outcome is Outcome.BLOCK
    assert ViolationCode.TOTAL_EXCEEDS_MAX in codes


def test_currency_manipulation() -> None:
    """4,900 rupees quoted as 4,900 dollars. Never converted, always blocked."""
    result, codes = decide(
        mandate(),
        offer([("Running shoes", from_rupees(4900), LineItemKind.PRODUCT)], currency="USD"),
    )
    assert result.outcome is Outcome.BLOCK
    assert ViolationCode.CURRENCY_MISMATCH in codes


# --- rows the table expects to PASS ---------------------------------------
# These matter more than the blocks. A gate that blocks everything is a perfect
# detector and a useless product.


def test_negotiated_discount_passes() -> None:
    """5,500 -> 4,700 after negotiation."""
    result, codes = decide(
        mandate(),
        offer(
            [
                ("Running shoes", from_rupees(5500), LineItemKind.PRODUCT),
                ("Negotiated discount", -from_rupees(800), LineItemKind.DISCOUNT),
            ]
        ),
    )
    assert result.outcome is Outcome.ALLOW
    assert not codes


def test_better_shipping_passes() -> None:
    """Standard requested, free express delivered. Faster than asked is drift, not a fault."""
    result, codes = decide(
        mandate(),
        offer(
            [
                ("Running shoes", from_rupees(4499), LineItemKind.PRODUCT),
                ("Express delivery, free upgrade", 0, LineItemKind.SHIPPING),
            ]
        ),
    )
    assert result.outcome is Outcome.ALLOW


def test_merchant_discount_passes() -> None:
    """5,000 -> 4,499. A lower price never violates the price check on its own."""
    result, codes = decide(
        mandate(), offer([("Running shoes", from_rupees(4499), LineItemKind.PRODUCT)])
    )
    assert result.outcome is Outcome.ALLOW
    assert not codes


# --- the worked example from the concept ----------------------------------


def test_the_laptop_example_reports_every_reason_not_just_the_price() -> None:
    """ "Buy me a laptop under 70,000. No EMI."

    The concept cites one reason: the total exceeds the maximum by 3,497. The
    engine gives three, because a user who negotiates the price down and
    resubmits should not then discover the warranty and the financing.
    """
    led = mandate(
        category=Category.ELECTRONICS,
        max_total_paise=from_rupees(70000),
        emi_allowed=False,
    )
    off = Offer(
        offer_id="off_laptop",
        product=Product(
            product_id="sku_laptop", title="Laptop", category="electronics", condition="new"
        ),
        quantity=1,
        currency="INR",
        line_items=[
            LineItem(label="Laptop", amount_paise=from_rupees(67999), kind=LineItemKind.PRODUCT),
            LineItem(
                label="Extended warranty", amount_paise=from_rupees(4999), kind=LineItemKind.ADDON
            ),
            LineItem(label="Shipping", amount_paise=from_rupees(499), kind=LineItemKind.SHIPPING),
        ],
        total_paise=from_rupees(73497),
        emi=EmiTerms(installment_paise=from_rupees(6125), installment_count=12),
    )
    result, codes = decide(led, off)

    assert result.outcome is Outcome.BLOCK
    assert {
        ViolationCode.TOTAL_EXCEEDS_MAX,
        ViolationCode.ADDON_NOT_AUTHORIZED,
        ViolationCode.EMI_NOT_AUTHORIZED,
    } <= codes
    assert len(result.violations) >= 3
    for violation in result.violations:
        assert violation.explanation and "None" not in violation.explanation
