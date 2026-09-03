"""Every core model survives JSON and comes back equal. Stage 1's gate."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from intentguard.core import (
    Decision,
    DriftItem,
    DriftReport,
    EmiTerms,
    LatencyBreakdown,
    LineItem,
    LineItemKind,
    Outcome,
    Violation,
    ViolationCode,
    from_rupees,
)
from intentguard.core.intent import ConfidenceField

from .fixtures import a_ledger, a_trial_recurrence, an_offer


def _round_trip(model):
    return type(model).model_validate_json(model.model_dump_json())


@pytest.mark.parametrize(
    "model",
    [
        a_ledger(),
        an_offer(),
        an_offer(recurring=[a_trial_recurrence()]),
        an_offer(emi=EmiTerms(installment_paise=from_rupees(4500), installment_count=12)),
        a_trial_recurrence(),
        LineItem(
            label="Diwali discount", amount_paise=-from_rupees(500), kind=LineItemKind.DISCOUNT
        ),
        ConfidenceField[int](value=129950, confidence=0.91),
        DriftItem(field="colour", requested="blue", offered="black", weight=0.4),
        DriftReport(score=0.4, items=[DriftItem(field="brand", requested="Asics", offered="Nike")]),
        LatencyBreakdown(arithmetic_ms=1.2, total_ms=1.9),
        Violation(
            code=ViolationCode.TOTAL_EXCEEDS_MAX,
            outcome=Outcome.BLOCK,
            explanation="This order comes to more than you authorized.",
            field="max_total_paise",
        ),
        Decision(
            decision=Outcome.ALLOW,
            intent_id="int_001",
            offer_id="off_001",
            checked_at=datetime(2026, 9, 4, 10, 5, tzinfo=UTC),
        ),
    ],
    ids=lambda m: type(m).__name__,
)
def test_round_trips(model) -> None:
    assert _round_trip(model) == model


def test_round_trip_preserves_exact_paise() -> None:
    offer = an_offer(total_paise=129950)
    assert _round_trip(offer).total_paise == 129950
    assert isinstance(_round_trip(offer).total_paise, int)
