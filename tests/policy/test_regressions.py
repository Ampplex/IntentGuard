"""Defects found by reviewing the engine after stage 3, kept as regressions.

Each of these passed review once. They are here so they cannot pass it twice.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from intentguard.core import (
    EmiTerms,
    LineItem,
    LineItemKind,
    Outcome,
    ViolationCode,
    explain,
    from_rupees,
)
from intentguard.policy import evaluate
from tests.fixtures import CREATED_AT, a_ledger, an_offer

NOW = CREATED_AT + timedelta(minutes=5)


def codes(result) -> set[ViolationCode]:
    return {violation.code for violation in result.violations}


def test_bogus_emi_terms_cannot_lower_the_figure_checked_against_the_ceiling() -> None:
    """A financed offer was checked on the instalments *instead of* the total.

    A merchant with emi_allowed could therefore attach one instalment of one
    paisa to a ninety thousand rupee cart and the ceiling check would compare
    against the paisa. The rule that the instalment sum is what counts exists to
    catch interest making the real cost higher, never to let EMI make the
    checked figure lower than the money actually leaving the account.
    """
    ledger = a_ledger()
    hard = ledger.hard.model_copy(
        update={"emi_allowed": True, "max_total_paise": from_rupees(5000)}
    )
    offer = an_offer(
        line_items=[
            LineItem(label="Laptop", amount_paise=from_rupees(90000), kind=LineItemKind.PRODUCT)
        ],
        total_paise=from_rupees(90000),
        emi=EmiTerms(installment_paise=1, installment_count=1),
    )
    result = evaluate(ledger.model_copy(update={"hard": hard}), offer, now=NOW)
    assert result.checked_total_paise == from_rupees(90000)
    assert ViolationCode.TOTAL_EXCEEDS_MAX in codes(result)
    assert result.outcome is Outcome.BLOCK


def test_interest_still_counts_when_it_raises_the_cost() -> None:
    """The original rule has to keep working: 4500 x 12 is 54000, not 50000."""
    ledger = a_ledger()
    hard = ledger.hard.model_copy(
        update={"emi_allowed": True, "max_total_paise": from_rupees(52000)}
    )
    offer = an_offer(
        line_items=[
            LineItem(label="Television", amount_paise=from_rupees(50000), kind=LineItemKind.PRODUCT)
        ],
        total_paise=from_rupees(50000),
        emi=EmiTerms(installment_paise=from_rupees(4500), installment_count=12),
    )
    result = evaluate(ledger.model_copy(update={"hard": hard}), offer, now=NOW)
    assert result.checked_total_paise == from_rupees(54000)
    assert ViolationCode.TOTAL_EXCEEDS_MAX in codes(result)


def test_a_mandate_cannot_be_created_in_another_currency() -> None:
    """The system is single-currency by decision, and nothing enforced it.

    A mandate carrying USD would have made an offer quoted in USD pass the
    currency check, which is the one check the spec calls an immediate block.
    """
    hard = a_ledger().hard
    with pytest.raises(ValidationError, match="single-currency"):
        type(hard).model_validate({**hard.model_dump(), "currency": "USD"})


def test_a_mandate_currency_is_normalised_not_rejected_on_case() -> None:
    ledger = a_ledger()
    hard = type(ledger.hard).model_validate({**ledger.hard.model_dump(), "currency": "inr"})
    assert hard.currency == "INR"


def test_an_explanation_never_shows_the_word_none_to_a_user() -> None:
    """explain() filled missing placeholders with None and rendered it verbatim."""
    with pytest.raises(ValueError, match="expected"):
        explain(ViolationCode.QUANTITY_MISMATCH, observed="3")


def test_every_explanation_the_engine_produces_is_complete() -> None:
    """Belt and braces: no rendered violation may contain a stray None."""
    ledger = a_ledger()
    hard = ledger.hard.model_copy(update={"quantity": 2})
    offer = an_offer(
        quantity=5,
        currency="USD",
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(9000), kind=LineItemKind.PRODUCT)
        ],
        total_paise=from_rupees(9000),
    )
    result = evaluate(ledger.model_copy(update={"hard": hard}), offer, now=NOW)
    assert result.violations
    for violation in result.violations:
        assert "None" not in violation.explanation, violation.code


def test_the_engine_returns_a_decision_rather_than_raising() -> None:
    """A ledger built by model_copy skips validation and can hold plain strings.

    pydantic re-validates on model_validate and not on model_copy, so an
    internally constructed mandate can carry a str where the annotation says
    enum. The engine used to raise AttributeError reaching for .value on it,
    which returns no decision at all -- strictly worse than any wrong answer,
    because a caller with no decision has nothing to refuse on.
    """
    ledger = a_ledger()
    hard = ledger.hard.model_copy(update={"category": "electronics"})
    result = evaluate(ledger.model_copy(update={"hard": hard}), an_offer(), now=NOW)
    assert result.outcome in {Outcome.ALLOW, Outcome.BLOCK, Outcome.ESCALATE}
    assert ViolationCode.CATEGORY_MISMATCH in codes(result)
