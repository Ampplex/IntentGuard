"""The schema-level rules that stage 1 owns, and the ones it deliberately does not."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from intentguard.core import (
    Decision,
    LineItem,
    LineItemKind,
    Outcome,
    Violation,
    ViolationCode,
    from_rupees,
)

from .fixtures import a_ledger, an_offer


def test_only_a_discount_may_be_negative() -> None:
    LineItem(label="Diwali", amount_paise=-from_rupees(500), kind=LineItemKind.DISCOUNT)
    for kind in (LineItemKind.PRODUCT, LineItemKind.SHIPPING, LineItemKind.TAX, LineItemKind.FEE):
        with pytest.raises(ValidationError, match="may not be negative"):
            LineItem(label="x", amount_paise=-1, kind=kind)


def test_total_mismatch_is_constructible_because_it_is_a_decision_not_a_parse_error() -> None:
    """An offer that cannot be built cannot be blocked, and TOTAL_MISMATCH is a BLOCK."""
    offer = an_offer(total_paise=from_rupees(9999))
    assert offer.total_paise == from_rupees(9999)


def test_unknown_offer_field_is_refused_so_the_gate_can_escalate_it() -> None:
    with pytest.raises(ValidationError) as caught:
        an_offer(loyalty_lock_in_months=12)
    errors = caught.value.errors()
    assert any(e["type"] == "extra_forbidden" for e in errors)
    assert any("loyalty_lock_in_months" in str(e["loc"]) for e in errors)


def test_merchant_condition_string_is_free_text_not_an_enum() -> None:
    """ "slightly used" must be able to reach the engine and escalate, not 422."""
    offer = an_offer()
    weird = offer.model_copy(
        update={"product": offer.product.model_copy(update={"condition": "slightly used"})}
    )
    assert weird.product.condition == "slightly used"


def test_offer_must_itemise() -> None:
    with pytest.raises(ValidationError, match="itemise"):
        an_offer(line_items=[])


def test_confidence_keys_must_name_real_constraints() -> None:
    with pytest.raises(ValidationError, match="not constraint fields"):
        a_ledger(confidence={"vibes": 0.9})


def test_confidence_values_are_bounded() -> None:
    with pytest.raises(ValidationError, match="outside 0..1"):
        a_ledger(confidence={"category": 1.4})


def test_core_models_are_frozen() -> None:
    offer = an_offer()
    with pytest.raises(ValidationError):
        offer.total_paise = 1


def test_allow_cannot_carry_violations() -> None:
    violation = Violation(
        code=ViolationCode.TOTAL_EXCEEDS_MAX,
        outcome=Outcome.BLOCK,
        explanation="over budget",
    )
    with pytest.raises(ValidationError, match="cannot carry violations"):
        Decision(
            decision=Outcome.ALLOW,
            intent_id="int_001",
            offer_id="off_001",
            violations=[violation],
            checked_at=datetime(2026, 9, 4, tzinfo=UTC),
        )


def test_a_block_must_say_what_was_wrong() -> None:
    with pytest.raises(ValidationError, match="must say what was wrong"):
        Decision(
            decision=Outcome.BLOCK,
            intent_id="int_001",
            offer_id="off_001",
            checked_at=datetime(2026, 9, 4, tzinfo=UTC),
        )
