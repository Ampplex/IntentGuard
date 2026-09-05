"""Money helpers. The parse boundary is the only place a decimal exists."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from intentguard.core.money import (
    PAISE_PER_RUPEE,
    format_paise,
    from_rupees,
    parse_rupees,
    sum_paise,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1299", 129900),
        ("1299.50", 129950),
        ("1,299.50", 129950),
        ("₹1,299.50", 129950),
        ("INR 1299.50", 129950),
        ("Rs. 1,299.50", 129950),
        ("Rs 1299", 129900),
        ("0", 0),
        ("0.01", 1),
        ("0.10", 10),
        ("-250.75", -25075),
        ("₹12,99,000", 129900000),
        ("  1299  ", 129900),
    ],
)
def test_parse_rupees(text: str, expected: int) -> None:
    assert parse_rupees(text) == expected


@pytest.mark.parametrize("text", ["1.005", "1299.999", "0.001"])
def test_parse_refuses_to_round_a_stated_amount(text: str) -> None:
    """Silently rounding a budget is the bug the integer rule exists to stop.

    The test reads "whole number of paise" rather than "decimal places" because
    the rule is about the paisa, not the digit count: "7.50 crore" carries two
    decimal places and is exactly 7,500,000,000 paise, while "1.005" carries
    three and is half a paisa.
    """
    with pytest.raises(ValueError, match="whole number of paise"):
        parse_rupees(text)


@pytest.mark.parametrize("text", ["", "   ", "abc", "₹", "1299,", "NaN", "Infinity", "1.2.3"])
def test_parse_rejects_junk(text: str) -> None:
    with pytest.raises(ValueError):
        parse_rupees(text)


def test_parse_rejects_non_string() -> None:
    with pytest.raises(TypeError):
        parse_rupees(1299)


@pytest.mark.parametrize(
    ("paise", "expected"),
    [
        (0, "₹0.00"),
        (1, "₹0.01"),
        (129950, "₹1,299.50"),
        (129900000, "₹12,99,000.00"),
        (100000, "₹1,000.00"),
        (-25075, "-₹250.75"),
    ],
)
def test_format_paise(paise: int, expected: str) -> None:
    assert format_paise(paise) == expected


def test_format_rejects_non_int() -> None:
    with pytest.raises(TypeError):
        format_paise("1299")


def test_bools_are_not_money() -> None:
    with pytest.raises(TypeError):
        format_paise(True)
    with pytest.raises(TypeError):
        sum_paise([1, True])


def test_from_rupees() -> None:
    assert from_rupees(5000) == 5000 * PAISE_PER_RUPEE


def test_sum_paise() -> None:
    assert sum_paise([420000, 0, -5000]) == 415000
    assert sum_paise([]) == 0


@given(st.integers(min_value=-(10**12), max_value=10**12))
def test_format_then_parse_round_trips(paise: int) -> None:
    assert parse_rupees(format_paise(paise)) == paise


@given(st.integers(min_value=0, max_value=10**10))
def test_from_rupees_round_trips_through_display(rupees: int) -> None:
    paise = from_rupees(rupees)
    assert parse_rupees(format_paise(paise)) == paise


# --- Indian scale words ---------------------------------------------------
#
# A budget written the way people here actually write one parsed as nothing at
# all: "i want to buy rolls royce car, budget is Rs 7.50 Crore" produced no
# ceiling, so the system asked the user how much they wanted to spend -- about
# a figure they had just given it. For a product built on Razorpay that is not
# an edge case.


@pytest.mark.parametrize(
    ("text", "expected_paise"),
    [
        ("7.50 Crore", 7_500_000_000),
        ("7.5 crore", 7_500_000_000),
        ("1 cr", 1_000_000_000),
        ("2 crore rupees", 2_000_000_000),
        ("2 lakh", 200_000_00),
        ("1.5 lakhs", 150_000_00),
        ("2 lacs", 200_000_00),
        ("Rs 7.50 Crore", 7_500_000_000),
        ("₹1.25 lakh", 125_000_00),
        ("50k", 50_000_00),
        ("3 thousand", 3_000_00),
        ("1 million", 1_000_000_00),
    ],
)
def test_a_scale_word_multiplies_the_amount(text: str, expected_paise: int) -> None:
    assert parse_rupees(text) == expected_paise


def test_a_scaled_amount_is_still_exact_paise() -> None:
    """Two decimal places on a crore is a whole number of paise, and must not be
    refused by a rule written for two decimal places on a rupee."""
    assert parse_rupees("7.50 crore") == parse_rupees("75000000")


@pytest.mark.parametrize(
    "text",
    [
        "k",  # a scale word needs digits before it
        "krupees",
        "2 lakh crore",  # one scale word, not two
        "0.001 rupees",  # not a whole paisa
        "lakh 2",
    ],
)
def test_what_is_still_refused(text: str) -> None:
    with pytest.raises((ValueError, TypeError)):
        parse_rupees(text)


def test_no_float_enters_the_money_path() -> None:
    """The whole point of the integer-paise rule, checked on the new path too."""
    for text in ("7.50 crore", "1.5 lakhs", "50k"):
        assert isinstance(parse_rupees(text), int)
