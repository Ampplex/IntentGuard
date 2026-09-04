"""Soft preference drift. Reported, ranked, and never able to stop a payment."""

from __future__ import annotations

from intentguard.core import LineItem, LineItemKind, SoftPreferences, from_rupees
from intentguard.semantic import WEIGHTS, score_drift
from tests.fixtures import a_ledger, an_offer


def ledger_wanting(**soft):
    return a_ledger().model_copy(update={"soft": SoftPreferences(**soft)})


def offer_with(**product):
    offer = an_offer()
    return offer.model_copy(update={"product": offer.product.model_copy(update=product)})


def test_a_matched_preference_produces_no_drift() -> None:
    report = score_drift(ledger_wanting(brand="Asics"), offer_with(brand="Asics"))
    assert report.items == []
    assert report.score == 0.0


def test_a_missed_brand_is_the_heaviest_single_miss() -> None:
    """Naming a brand is the closest a user gets to naming a product."""
    report = score_drift(ledger_wanting(brand="Asics"), offer_with(brand="Nike"))
    assert [item.field for item in report.items] == ["brand"]
    assert report.items[0].weight == WEIGHTS["brand"]
    assert report.score == 1.0


def test_drift_is_scored_against_what_the_user_actually_asked_for() -> None:
    """A user who stated one preference and had it missed scores as badly as one
    who stated three and had all three missed.

    Dividing by a fixed total would let the system look accurate by ignoring
    people who asked for little.
    """
    one = score_drift(ledger_wanting(colour="blue"), offer_with(colour="black"))
    assert one.score == 1.0


def test_a_partial_miss_scores_between() -> None:
    ledger = ledger_wanting(brand="Asics", colour="blue")
    report = score_drift(ledger, offer_with(brand="Asics", colour="black"))
    assert 0.0 < report.score < 1.0
    assert [item.field for item in report.items] == ["colour"]


def test_silence_is_not_a_mismatch() -> None:
    """A preference the merchant said nothing about has not been missed.

    Counting it would make a sparse offer look worse than a wrong one.
    """
    report = score_drift(ledger_wanting(brand="Asics"), offer_with(brand=None))
    assert report.items == []


def test_a_preference_never_expressed_cannot_drift() -> None:
    report = score_drift(ledger_wanting(), offer_with(brand="Nike", colour="black"))
    assert report.items == []
    assert report.score == 0.0


def test_delivery_speed_is_read_from_the_shipping_line() -> None:
    ledger = ledger_wanting(delivery_speed="express")
    offer = an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(4200), kind=LineItemKind.PRODUCT),
            LineItem(label="standard post", amount_paise=0, kind=LineItemKind.SHIPPING),
        ],
        total_paise=from_rupees(4200),
    )
    report = score_drift(ledger, offer)
    assert [item.field for item in report.items] == ["delivery_speed"]


def test_a_near_match_is_not_drift() -> None:
    """ "Asics" and "ASICS " are the same brand written differently."""
    report = score_drift(ledger_wanting(brand="Asics"), offer_with(brand="ASICS "))
    assert report.items == []


def test_the_weights_are_a_stated_judgement_that_sums_to_one() -> None:
    assert set(WEIGHTS) == {"brand", "colour", "delivery_speed"}
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9
    assert WEIGHTS["brand"] > WEIGHTS["delivery_speed"] > WEIGHTS["colour"]


def test_the_score_is_bounded() -> None:
    ledger = ledger_wanting(brand="Asics", colour="blue", delivery_speed="express")
    offer = offer_with(brand="Nike", colour="black")
    assert 0.0 <= score_drift(ledger, offer).score <= 1.0
