"""The two checks added by Amendment 4, closing the gaps the gold set found.

Both are deliberately literal. Blocking on an exact comparison is safe; blocking
on a similarity score is the thing this project argues against, so the fuzzy half
of each question escalates from semantic/ instead.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from intentguard.core import (
    HardConstraints,
    LineItem,
    LineItemKind,
    Outcome,
    ViolationCode,
    from_rupees,
)
from intentguard.policy import evaluate
from tests.fixtures import CREATED_AT, a_ledger, an_offer

NOW = CREATED_AT + timedelta(minutes=5)


def codes(result) -> set[ViolationCode]:
    return {violation.code for violation in result.violations}


def check(*, hard_updates: dict, product_updates: dict | None = None, items=None):
    ledger = a_ledger()
    hard = HardConstraints.model_validate({**ledger.hard.model_dump(), **hard_updates})
    offer = an_offer(
        **(
            {"line_items": items, "total_paise": sum(i.amount_paise for i in items)}
            if items
            else {}
        )
    )
    if product_updates:
        offer = offer.model_copy(
            update={"product": offer.product.model_copy(update=product_updates)}
        )
    return evaluate(ledger.model_copy(update={"hard": hard}), offer, now=NOW)


# --- exclusions -----------------------------------------------------------


def test_an_excluded_material_blocks() -> None:
    result = check(
        hard_updates={"exclusions": ("leather",)},
        product_updates={"title": "Leather chelsea boots"},
    )
    assert ViolationCode.EXCLUDED_ITEM in codes(result)
    assert result.outcome is Outcome.BLOCK


def test_a_respected_exclusion_does_not_fire() -> None:
    """The control. A keyword blocklist that fires here is a revenue bug."""
    result = check(
        hard_updates={"exclusions": ("leather",)},
        product_updates={"title": "Vegan suede boots"},
    )
    assert result.outcome is Outcome.ALLOW


@pytest.mark.parametrize(
    "title",
    [
        "Leather-free chelsea boots",
        "Boots with no leather",
        "Non-leather chelsea boots",
        "Chelsea boots, free of leather",
    ],
)
def test_a_negated_mention_is_not_a_violation(title: str) -> None:
    """ "leather-free" contains "leather" and means the opposite of it.

    Blocking these would block exactly the products the user asked for, which is
    a false positive against the metric the project leads with.
    """
    result = check(hard_updates={"exclusions": ("leather",)}, product_updates={"title": title})
    assert ViolationCode.EXCLUDED_ITEM not in codes(result)


def test_an_exclusion_is_not_matched_inside_a_longer_word() -> None:
    result = check(
        hard_updates={"exclusions": ("nike",)},
        product_updates={"title": "Nikecraft collaboration tee", "brand": "Adidas"},
    )
    assert ViolationCode.EXCLUDED_ITEM not in codes(result)


def test_a_negative_brand_instruction_is_an_exclusion_not_a_preference() -> None:
    result = check(
        hard_updates={"exclusions": ("Nike",)},
        product_updates={"title": "Nike Revolution 7", "brand": "Nike"},
    )
    assert ViolationCode.EXCLUDED_ITEM in codes(result)


def test_an_exclusion_is_found_in_a_line_item_label() -> None:
    """A merchant can keep the excluded thing out of the title and still charge for it."""
    result = check(
        hard_updates={"exclusions": ("whey",), "addons_allowed": True},
        items=[
            LineItem(
                label="Protein blend", amount_paise=from_rupees(2000), kind=LineItemKind.PRODUCT
            ),
            LineItem(
                label="Whey isolate scoop", amount_paise=from_rupees(200), kind=LineItemKind.ADDON
            ),
        ],
    )
    assert ViolationCode.EXCLUDED_ITEM in codes(result)


def test_each_excluded_term_is_reported_once() -> None:
    result = check(
        hard_updates={"exclusions": ("leather", "suede")},
        product_updates={"title": "Leather and suede leather hybrid boot"},
    )
    excluded = [v for v in result.violations if v.code is ViolationCode.EXCLUDED_ITEM]
    assert len(excluded) == 2
    assert {v.expected for v in excluded} == {"leather", "suede"}


def test_no_exclusions_means_no_check() -> None:
    assert check(hard_updates={"exclusions": ()}).outcome is Outcome.ALLOW


# --- product identity -----------------------------------------------------


def test_a_different_product_blocks_when_one_was_named() -> None:
    result = check(
        hard_updates={"product_ref": "Asics Gel-Contend 9"},
        product_updates={"title": "Nike Revolution 7", "brand": "Nike"},
    )
    assert ViolationCode.PRODUCT_SUBSTITUTION in codes(result)
    assert result.outcome is Outcome.BLOCK


def test_a_lower_price_does_not_excuse_a_substitution() -> None:
    """A lower price never violates the price check, and never inherits a pass."""
    result = check(
        hard_updates={"product_ref": "Asics Gel-Contend 9"},
        product_updates={"title": "Generic running shoe"},
        items=[
            LineItem(
                label="Generic shoe", amount_paise=from_rupees(1400), kind=LineItemKind.PRODUCT
            )
        ],
    )
    assert ViolationCode.PRODUCT_SUBSTITUTION in codes(result)
    assert ViolationCode.TOTAL_EXCEEDS_MAX not in codes(result)


@pytest.mark.parametrize(
    "title", ["Asics Gel-Contend 9", "asics gel contend 9", "ASICS  Gel-Contend-9"]
)
def test_punctuation_and_case_are_not_a_substitution(title: str) -> None:
    result = check(
        hard_updates={"product_ref": "Asics Gel-Contend 9"}, product_updates={"title": title}
    )
    assert ViolationCode.PRODUCT_SUBSTITUTION not in codes(result)


def test_a_matching_product_id_satisfies_the_reference() -> None:
    result = check(
        hard_updates={"product_ref": "sku_77"},
        product_updates={"title": "Whatever the merchant calls it"},
    )
    assert ViolationCode.PRODUCT_SUBSTITUTION not in codes(result)


def test_a_brand_preference_alone_never_blocks() -> None:
    """Soft preferences rank offers. Drift never blocks, so no product_ref means no block."""
    result = check(
        hard_updates={"product_ref": None},
        product_updates={"title": "New Balance 411", "brand": "New Balance"},
    )
    assert result.outcome is Outcome.ALLOW
