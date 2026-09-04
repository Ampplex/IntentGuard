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


def test_a_field_of_spaces_is_silence_rather_than_a_mismatch() -> None:
    """A merchant sending whitespace was scored as getting the brand wrong."""
    report = score_drift(ledger_wanting(brand="Asics"), offer_with(brand="   "))
    assert report.items == []
    assert report.score == 0.0


def test_a_preference_of_only_spaces_is_not_an_expressed_preference() -> None:
    report = score_drift(ledger_wanting(brand="  "), offer_with(brand="Nike"))
    assert report.items == []
    assert report.score == 0.0


def test_a_very_long_brand_string_does_not_stall_the_gate() -> None:
    import time

    started = time.perf_counter()
    score_drift(ledger_wanting(brand="Asics"), offer_with(brand="Asics" * 100_000))
    assert (time.perf_counter() - started) * 1000 < 5.0


def test_a_plain_shipping_label_is_not_a_delivery_speed() -> None:
    """Reading the whole label as a speed misfired on almost every offer.

    A line called "Delivery" compared against a preference for "standard" looked
    like a missed preference, so any offer with an ordinary shipping line
    reported drift it had not caused.
    """
    ledger = ledger_wanting(delivery_speed="standard")
    for label in ("Delivery", "Free delivery", "Shipping", "Dispatch"):
        offer = an_offer(
            line_items=[
                LineItem(label="Shoes", amount_paise=from_rupees(4200), kind=LineItemKind.PRODUCT),
                LineItem(label=label, amount_paise=0, kind=LineItemKind.SHIPPING),
            ],
            total_paise=from_rupees(4200),
        )
        report = score_drift(ledger, offer)
        assert report.items == [], f"{label!r} was read as a delivery speed"


def test_a_label_that_names_a_speed_is_still_compared() -> None:
    ledger = ledger_wanting(delivery_speed="express")
    offer = an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(4200), kind=LineItemKind.PRODUCT),
            LineItem(label="Economy shipping", amount_paise=0, kind=LineItemKind.SHIPPING),
        ],
        total_paise=from_rupees(4200),
    )
    assert [item.field for item in score_drift(ledger, offer).items] == ["delivery_speed"]


def test_a_matching_speed_produces_no_drift() -> None:
    ledger = ledger_wanting(delivery_speed="express")
    offer = an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(4200), kind=LineItemKind.PRODUCT),
            LineItem(label="Express delivery", amount_paise=0, kind=LineItemKind.SHIPPING),
        ],
        total_paise=from_rupees(4200),
    )
    assert score_drift(ledger, offer).items == []


def test_a_preference_described_more_fully_is_still_met() -> None:
    """The same asymmetry that broke substitution matching, in drift.

    "express" against "Express delivery" is the preference met and described
    more fully. A symmetric measure scored it 0.5 and called it drift, so a
    merchant doing exactly what was asked looked like a merchant who had not.
    """
    for wanted, offered in [
        ("express", "Express delivery"),
        ("Asics", "Asics Corporation"),
        ("blue", "Deep blue"),
    ]:
        offer = an_offer()
        offer = offer.model_copy(
            update={"product": offer.product.model_copy(update={"colour": offered})}
        )
        assert score_drift(ledger_wanting(colour=wanted), offer).items == [], (
            f"{wanted!r} should be met by {offered!r}"
        )


def test_a_genuinely_different_value_is_still_drift() -> None:
    offer = an_offer()
    offer = offer.model_copy(
        update={"product": offer.product.model_copy(update={"colour": "black"})}
    )
    assert score_drift(ledger_wanting(colour="blue"), offer).items
