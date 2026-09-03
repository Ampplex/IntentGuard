"""One test per violation code the engine can produce, plus the two trap cases.

Written before the engine exists. Where a code is not produced by policy/ at
all, that is asserted explicitly in test_engine.py rather than left silent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from intentguard.core import (
    Condition,
    EmiTerms,
    LedgerStatus,
    LineItem,
    LineItemKind,
    Outcome,
    QuantityMode,
    ViolationCode,
    from_rupees,
)
from intentguard.policy import evaluate
from tests.fixtures import CREATED_AT, a_ledger, a_trial_recurrence, an_offer

NOW = CREATED_AT + timedelta(minutes=5)


def codes(result) -> set[ViolationCode]:
    return {violation.code for violation in result.violations}


def check(ledger=None, offer=None, now=NOW):
    return evaluate(ledger or a_ledger(), offer or an_offer(), now=now)


# --- the clean path -------------------------------------------------------


def test_a_compliant_offer_is_allowed() -> None:
    result = check()
    assert result.outcome is Outcome.ALLOW
    assert result.violations == []


def test_free_shipping_passes() -> None:
    """A zero-cost shipping line is not an add-on violation."""
    offer = an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(4200), kind=LineItemKind.PRODUCT),
            LineItem(label="Free delivery", amount_paise=0, kind=LineItemKind.SHIPPING),
        ],
        total_paise=from_rupees(4200),
    )
    assert check(offer=offer).outcome is Outcome.ALLOW


def test_a_free_tote_bag_passes() -> None:
    """Costs nothing, no recurring obligation, so it is permitted."""
    offer = an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(4200), kind=LineItemKind.PRODUCT),
            LineItem(label="Free tote bag", amount_paise=0, kind=LineItemKind.ADDON),
        ],
        total_paise=from_rupees(4200),
    )
    assert check(offer=offer).outcome is Outcome.ALLOW


def test_a_lower_price_is_not_a_violation() -> None:
    offer = an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(1200), kind=LineItemKind.PRODUCT)
        ],
        total_paise=from_rupees(1200),
    )
    assert check(offer=offer).outcome is Outcome.ALLOW


# --- arithmetic -----------------------------------------------------------


def test_total_exceeds_max() -> None:
    offer = an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(5001), kind=LineItemKind.PRODUCT)
        ],
        total_paise=from_rupees(5001),
    )
    result = check(offer=offer)
    assert result.outcome is Outcome.BLOCK
    assert ViolationCode.TOTAL_EXCEEDS_MAX in codes(result)


def test_the_ceiling_is_the_final_amount_not_the_line_item_price() -> None:
    """Shipping and tax count toward the ceiling. This is the most misread rule."""
    offer = an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(4800), kind=LineItemKind.PRODUCT),
            LineItem(label="Delivery", amount_paise=from_rupees(150), kind=LineItemKind.SHIPPING),
            LineItem(label="GST", amount_paise=from_rupees(120), kind=LineItemKind.TAX),
        ],
        total_paise=from_rupees(5070),
    )
    result = check(offer=offer)
    assert ViolationCode.TOTAL_EXCEEDS_MAX in codes(result)


def test_exactly_at_the_ceiling_is_allowed() -> None:
    offer = an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(5000), kind=LineItemKind.PRODUCT)
        ],
        total_paise=from_rupees(5000),
    )
    assert check(offer=offer).outcome is Outcome.ALLOW


def test_total_mismatch() -> None:
    result = check(offer=an_offer(total_paise=from_rupees(4000)))
    assert ViolationCode.TOTAL_MISMATCH in codes(result)
    assert result.outcome is Outcome.BLOCK


def test_negative_total() -> None:
    offer = an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(1000), kind=LineItemKind.PRODUCT),
            LineItem(
                label="Overzealous coupon",
                amount_paise=-from_rupees(1500),
                kind=LineItemKind.DISCOUNT,
            ),
        ],
        total_paise=-from_rupees(500),
    )
    result = check(offer=offer)
    assert ViolationCode.NEGATIVE_TOTAL in codes(result)


def test_a_discount_that_keeps_the_total_positive_is_fine() -> None:
    offer = an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(4200), kind=LineItemKind.PRODUCT),
            LineItem(
                label="Festive discount", amount_paise=-from_rupees(200), kind=LineItemKind.DISCOUNT
            ),
        ],
        total_paise=from_rupees(4000),
    )
    assert check(offer=offer).outcome is Outcome.ALLOW


def test_currency_mismatch_blocks_and_never_converts() -> None:
    offer = an_offer(currency="USD")
    result = check(offer=offer)
    assert ViolationCode.CURRENCY_MISMATCH in codes(result)
    assert result.outcome is Outcome.BLOCK


@pytest.mark.parametrize(
    ("mode", "authorized", "offered", "violates"),
    [
        (QuantityMode.EXACT, 2, 2, False),
        (QuantityMode.EXACT, 2, 3, True),
        (QuantityMode.EXACT, 2, 1, True),
        (QuantityMode.AT_MOST, 3, 2, False),
        (QuantityMode.AT_MOST, 3, 4, True),
        (QuantityMode.AT_LEAST, 3, 4, False),
        (QuantityMode.AT_LEAST, 3, 2, True),
    ],
)
def test_quantity(mode: QuantityMode, authorized: int, offered: int, violates: bool) -> None:
    ledger = a_ledger()
    hard = ledger.hard.model_copy(update={"quantity": authorized, "quantity_mode": mode})
    result = check(
        ledger=ledger.model_copy(update={"hard": hard}), offer=an_offer(quantity=offered)
    )
    assert (ViolationCode.QUANTITY_MISMATCH in codes(result)) is violates


# --- obligations ----------------------------------------------------------


def test_a_zero_rupee_trial_that_converts_is_a_violation() -> None:
    """The trap case. The total looks legitimate; the obligation is the problem."""
    offer = an_offer(recurring=[a_trial_recurrence()])
    result = check(offer=offer)
    assert offer.total_paise == from_rupees(4200)
    assert ViolationCode.RECURRING_NOT_AUTHORIZED in codes(result)
    assert result.outcome is Outcome.BLOCK


def test_recurrence_is_allowed_when_authorized() -> None:
    ledger = a_ledger()
    hard = ledger.hard.model_copy(update={"recurring_allowed": True})
    result = check(
        ledger=ledger.model_copy(update={"hard": hard}),
        offer=an_offer(recurring=[a_trial_recurrence()]),
    )
    assert result.outcome is Outcome.ALLOW


def test_addons_allowed_does_not_relax_the_recurrence_clause() -> None:
    ledger = a_ledger()
    hard = ledger.hard.model_copy(update={"addons_allowed": True})
    offer = an_offer(recurring=[a_trial_recurrence()])
    result = check(ledger=ledger.model_copy(update={"hard": hard}), offer=offer)
    assert ViolationCode.RECURRING_NOT_AUTHORIZED in codes(result)


def test_emi_not_authorized() -> None:
    offer = an_offer(emi=EmiTerms(installment_paise=from_rupees(400), installment_count=10))
    result = check(offer=offer)
    assert ViolationCode.EMI_NOT_AUTHORIZED in codes(result)


def test_the_financed_total_is_what_gets_checked_against_the_ceiling() -> None:
    """Rs 4,500 x 12 is Rs 54,000 even when the sticker says Rs 50,000."""
    ledger = a_ledger()
    hard = ledger.hard.model_copy(
        update={"emi_allowed": True, "max_total_paise": from_rupees(52000)}
    )
    offer = an_offer(
        line_items=[
            LineItem(label="Laptop", amount_paise=from_rupees(50000), kind=LineItemKind.PRODUCT)
        ],
        total_paise=from_rupees(50000),
        emi=EmiTerms(installment_paise=from_rupees(4500), installment_count=12),
    )
    result = check(ledger=ledger.model_copy(update={"hard": hard}), offer=offer)
    assert result.checked_total_paise == from_rupees(54000)
    assert ViolationCode.TOTAL_EXCEEDS_MAX in codes(result)


def test_a_paid_addon_is_a_violation() -> None:
    offer = an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(4000), kind=LineItemKind.PRODUCT),
            LineItem(
                label="Extended warranty", amount_paise=from_rupees(200), kind=LineItemKind.ADDON
            ),
        ],
        total_paise=from_rupees(4200),
    )
    result = check(offer=offer)
    assert ViolationCode.ADDON_NOT_AUTHORIZED in codes(result)


def test_addons_allowed_relaxes_the_cost_clause() -> None:
    ledger = a_ledger()
    hard = ledger.hard.model_copy(update={"addons_allowed": True})
    offer = an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(4000), kind=LineItemKind.PRODUCT),
            LineItem(label="Shoe trees", amount_paise=from_rupees(200), kind=LineItemKind.ADDON),
        ],
        total_paise=from_rupees(4200),
    )
    result = check(ledger=ledger.model_copy(update={"hard": hard}), offer=offer)
    assert result.outcome is Outcome.ALLOW


def test_every_paid_addon_is_named_separately() -> None:
    offer = an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(3000), kind=LineItemKind.PRODUCT),
            LineItem(label="Warranty", amount_paise=from_rupees(100), kind=LineItemKind.ADDON),
            LineItem(label="Gift wrap", amount_paise=from_rupees(50), kind=LineItemKind.ADDON),
        ],
        total_paise=from_rupees(3150),
    )
    result = check(offer=offer)
    addon_violations = [
        v for v in result.violations if v.code is ViolationCode.ADDON_NOT_AUTHORIZED
    ]
    assert len(addon_violations) == 2
    assert {v.observed for v in addon_violations} == {"Warranty", "Gift wrap"}


# --- product --------------------------------------------------------------


def test_condition_mismatch() -> None:
    offer = an_offer()
    product = offer.product.model_copy(update={"condition": "refurbished"})
    result = check(offer=offer.model_copy(update={"product": product}))
    assert ViolationCode.CONDITION_MISMATCH in codes(result)
    assert result.outcome is Outcome.BLOCK


def test_a_condition_outside_the_enum_escalates_rather_than_blocks() -> None:
    """You do not know the item is bad, only that you cannot judge it."""
    offer = an_offer()
    product = offer.product.model_copy(update={"condition": "slightly used"})
    result = check(offer=offer.model_copy(update={"product": product}))
    assert ViolationCode.UNCLASSIFIABLE_CONDITION in codes(result)
    assert result.outcome is Outcome.ESCALATE


@pytest.mark.parametrize("raw", ["new", "NEW", " New ", "open box", "open-box"])
def test_condition_spellings_that_should_still_match(raw: str) -> None:
    ledger = a_ledger()
    wanted = Condition.OPEN_BOX if "open" in raw.lower() else Condition.NEW
    hard = ledger.hard.model_copy(update={"condition": wanted})
    offer = an_offer()
    product = offer.product.model_copy(update={"condition": raw})
    result = check(
        ledger=ledger.model_copy(update={"hard": hard}),
        offer=offer.model_copy(update={"product": product}),
    )
    assert ViolationCode.CONDITION_MISMATCH not in codes(result)
    assert ViolationCode.UNCLASSIFIABLE_CONDITION not in codes(result)


def test_category_mismatch() -> None:
    offer = an_offer()
    product = offer.product.model_copy(update={"category": "electronics"})
    result = check(offer=offer.model_copy(update={"product": product}))
    assert ViolationCode.CATEGORY_MISMATCH in codes(result)
    assert result.outcome is Outcome.BLOCK


def test_a_category_outside_the_taxonomy_escalates() -> None:
    offer = an_offer()
    product = offer.product.model_copy(update={"category": "pet supplies"})
    result = check(offer=offer.model_copy(update={"product": product}))
    assert ViolationCode.UNCLASSIFIABLE_CATEGORY in codes(result)
    assert result.outcome is Outcome.ESCALATE


def test_condition_is_only_checked_when_the_mandate_states_one() -> None:
    ledger = a_ledger()
    hard = ledger.hard.model_copy(update={"condition": None})
    offer = an_offer()
    product = offer.product.model_copy(update={"condition": "who knows"})
    result = check(
        ledger=ledger.model_copy(update={"hard": hard}),
        offer=offer.model_copy(update={"product": product}),
    )
    assert result.outcome is Outcome.ALLOW


# --- ledger state ---------------------------------------------------------


def test_expired_ledger_blocks_rather_than_escalating() -> None:
    """The authorization is gone, not unclear."""
    ledger = a_ledger()
    result = check(ledger=ledger, now=CREATED_AT + timedelta(seconds=ledger.ttl_seconds + 1))
    assert ViolationCode.LEDGER_EXPIRED in codes(result)
    assert result.outcome is Outcome.BLOCK


def test_not_expired_one_second_before_the_deadline() -> None:
    ledger = a_ledger()
    result = check(ledger=ledger, now=CREATED_AT + timedelta(seconds=ledger.ttl_seconds - 1))
    assert result.outcome is Outcome.ALLOW


def test_already_spent() -> None:
    result = check(ledger=a_ledger(status=LedgerStatus.SPENT))
    assert ViolationCode.LEDGER_ALREADY_SPENT in codes(result)


def test_execution_uncertain_is_treated_as_spent() -> None:
    result = check(ledger=a_ledger(status=LedgerStatus.EXECUTION_UNCERTAIN))
    assert ViolationCode.LEDGER_ALREADY_SPENT in codes(result)


def test_an_unconfirmed_mandate_escalates() -> None:
    result = check(ledger=a_ledger(status=LedgerStatus.AWAITING_CONFIRMATION))
    assert ViolationCode.LEDGER_NOT_CONFIRMED in codes(result)
    assert result.outcome is Outcome.ESCALATE


def test_ttl_is_paused_while_awaiting_confirmation() -> None:
    """A slow human must not expire a transaction they are mid-approval of."""
    ledger = a_ledger(status=LedgerStatus.AWAITING_CONFIRMATION)
    result = check(ledger=ledger, now=CREATED_AT + timedelta(days=7))
    assert ViolationCode.LEDGER_EXPIRED not in codes(result)


def test_an_expired_status_blocks_regardless_of_the_clock() -> None:
    result = check(ledger=a_ledger(status=LedgerStatus.EXPIRED), now=CREATED_AT)
    assert ViolationCode.LEDGER_EXPIRED in codes(result)


def test_a_naive_created_at_is_read_as_utc() -> None:
    ledger = a_ledger(created_at=datetime(2026, 9, 4, 10, 0, 0))
    result = check(ledger=ledger, now=datetime(2026, 9, 4, 10, 5, tzinfo=UTC))
    assert result.outcome is Outcome.ALLOW
