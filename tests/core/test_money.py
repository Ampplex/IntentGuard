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
    """Silently rounding a budget is the bug the integer rule exists to stop."""
    with pytest.raises(ValueError, match="decimal places"):
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
