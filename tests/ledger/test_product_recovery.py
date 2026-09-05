"""Pinning the product must not depend on the model getting it right.

The bug this file exists for: asked to buy a "macbook pro m5" with a ₹90,000
ceiling, the model returned product_ref null. Nothing was pinned, so the
deterministic substitution check returned immediately, and the only comparison
left was the merchant's opening quote against the merchant's own delivery --
which agreed, because it offered earbuds from the start. Every arithmetic check
passed, since ₹2,999 is well under ₹90,000 and a lower price does not violate
the price check on its own. The gate allowed it and an order was created.

An extraction miss was therefore sufficient to open a payment path, which is
the one thing this project claims cannot happen.
"""

from __future__ import annotations

import pytest

from intentguard.core.enums import Category
from intentguard.ledger.build import recovered_product_ref

# --- the miss that started it --------------------------------------------


def test_the_macbook_case() -> None:
    assert (
        recovered_product_ref(
            "I want to buy macbook pro m5 , budget is Rs 90,000",
            Category.ELECTRONICS,
            "Rs 90,000",
            1,
        )
        == "macbook pro m5"
    )


# --- a named product is recovered ----------------------------------------


@pytest.mark.parametrize(
    ("instruction", "category", "budget", "quantity", "expected"),
    [
        (
            "I need an iphone 15 pro, budget 90000",
            Category.ELECTRONICS,
            "90000",
            1,
            "iphone 15 pro",
        ),
        (
            "Buy me a pair of Nike Revolution 7, new, budget 5000 rupees.",
            Category.FOOTWEAR,
            "5000 rupees",
            1,
            "Nike Revolution 7",
        ),
        (
            "buy 2 Asics Gel-Contend 9, budget 9000 rupees",
            Category.FOOTWEAR,
            "9000 rupees",
            2,
            "Asics Gel Contend 9",
        ),
    ],
)
def test_a_model_designation_pins(
    instruction: str, category: Category, budget: str, quantity: int, expected: str
) -> None:
    assert recovered_product_ref(instruction, category, budget, quantity) == expected


# --- a kind of thing must never pin ---------------------------------------


@pytest.mark.parametrize(
    ("instruction", "category", "budget", "quantity"),
    [
        # The direction that costs money the other way: a pin no catalog entry
        # matches refuses every offer in the category.
        (
            "Buy me a pair of running shoes, budget 5000 rupees.",
            Category.FOOTWEAR,
            "5000 rupees",
            1,
        ),
        ("buy a laptop under 50000", Category.ELECTRONICS, "50000", 1),
        ("buy me a book, budget 500 rupees", Category.BOOKS, "500 rupees", 1),
        ("Buy me an electric kettle, budget 2000 rupees.", Category.HOME_KITCHEN, "2000 rupees", 1),
        ("Get me a decent laptop, nothing too pricey.", Category.ELECTRONICS, None, 1),
    ],
)
def test_a_kind_of_thing_pins_nothing(
    instruction: str, category: Category, budget: str | None, quantity: int
) -> None:
    assert recovered_product_ref(instruction, category, budget, quantity) is None


def test_a_thin_category_word_list_does_not_produce_a_false_pin() -> None:
    """This one was a real false pin, and it would have blocked a real product.

    Neither "yoga" nor "mat" appears in the category word lists, so a filter
    resting on those alone kept the phrase and pinned it -- against a catalog
    whose entry is "Cork Yoga Mat", which would then never match. Requiring a
    model designation is what closes it, because the lists are incomplete and
    completing them is not a thing that stays done.
    """
    assert (
        recovered_product_ref("get me a yoga mat, budget 1500", Category.SPORTS, "1500", 1) is None
    )


# --- digits that are not a model number -----------------------------------


def test_a_count_is_not_a_model_number() -> None:
    assert (
        recovered_product_ref(
            "buy 3 shirts, budget 2000 rupees", Category.APPAREL, "2000 rupees", 3
        )
        is None
    )


def test_a_budget_is_not_a_model_number() -> None:
    """Without removing the budget text every instruction carries digits."""
    assert (
        recovered_product_ref("buy me a yoga mat, budget 1500 rupees", Category.SPORTS, None, 1)
        is not None
    ), "the guard only holds because the budget text is removed first"
    assert (
        recovered_product_ref(
            "buy me a yoga mat, budget 1500 rupees", Category.SPORTS, "1500 rupees", 1
        )
        is None
    )


def test_nothing_is_recovered_from_nothing() -> None:
    assert recovered_product_ref("", Category.FOOTWEAR, None, 1) is None
    assert recovered_product_ref("   ", Category.FOOTWEAR, None, 1) is None
