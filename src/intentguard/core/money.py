"""Money helpers. Every amount in IntentGuard is an integer number of paise.

Decimal appears in exactly one place: the parse boundary, where human text like
"1,299.50" becomes 129950. It is never stored, never returned and never compared.
Everything downstream sees int and nothing else.

The builtin that turns text into a binary fraction is not referenced anywhere in
this module, and tests/core/test_no_floats.py enforces that by parsing this
file's syntax tree rather than trusting the comment you are reading.

Single-currency by deliberate scope decision. See the README.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import BeforeValidator

PAISE_PER_RUPEE = 100
MAX_DECIMAL_PLACES = 2

_CURRENCY_PREFIXES = ("₹", "INR", "RS.", "RS")
# A model writing out an amount says "5,000 rupees", and refusing that would
# discard a perfectly clear figure over a word. Stripped only from the end,
# and only these words: anything else still fails rather than being guessed at.
_CURRENCY_SUFFIXES = ("RUPEES", "RUPEE", "INR", "RS.", "RS", "PAISE")

# Ungrouped digits, or digits grouped in twos and threes so that both Indian
# (12,99,000) and Western (1,299,000) separators parse. A stray or trailing
# comma is malformed, and a malformed amount gets refused rather than guessed
# at -- same reason a third decimal place is refused.
_INTEGER_PART = re.compile(r"^(?:\d+|\d{1,3}(?:,\d{2,3})+)$")

# Scale words, longest first so "crores" is matched before "crore" and "lakhs"
# before "lakh". A budget written the way people in India actually write one --
# "7.50 crore", "2 lakh", "50k" -- parsed nothing at all before this, and an
# unreadable ceiling becomes a question about a figure the user already gave.
# That is a worse failure than it looks: the system asks the user to repeat
# themselves and appears not to have read the instruction.
_SCALES: tuple[tuple[str, int], ...] = (
    ("CRORES", 10_000_000),
    ("CRORE", 10_000_000),
    ("LAKHS", 100_000),
    ("LAKHS.", 100_000),
    ("LAKH", 100_000),
    ("LACS", 100_000),
    ("LAC", 100_000),
    ("BILLION", 1_000_000_000),
    ("MILLION", 1_000_000),
    ("THOUSAND", 1_000),
    ("CR", 10_000_000),
    ("BN", 1_000_000_000),
    ("MN", 1_000_000),
    ("K", 1_000),
)


def _require_paise(value: object, label: str = "amount") -> int:
    """Reject anything that is not a plain int, bools included."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer number of paise, got {type(value).__name__}")
    return value


def from_rupees(rupees: int) -> int:
    """Whole rupees to paise. Exists so fixtures never need to write a decimal."""
    return _require_paise(rupees, "rupees") * PAISE_PER_RUPEE


def parse_rupees(text: str) -> int:
    """Parse human rupee text into integer paise.

    Accepts a leading minus, an optional currency prefix, and thousands commas.
    Refuses more than two decimal places rather than rounding: silently rounding
    a stated budget is exactly the class of bug the integer-paise rule exists to
    prevent.
    """
    if not isinstance(text, str):
        raise TypeError(f"expected a string, got {type(text).__name__}")

    cleaned = text.strip()
    if not cleaned:
        raise ValueError("empty amount")

    negative = cleaned.startswith("-")
    if negative:
        cleaned = cleaned[1:].lstrip()

    upper = cleaned.upper()
    for prefix in _CURRENCY_PREFIXES:
        if upper.startswith(prefix):
            cleaned = cleaned[len(prefix) :].lstrip()
            break

    # "7.50 crore rupees" and "Rs 2 lakh" both occur, so the currency word and
    # the scale word are stripped in whichever order they appear.
    scale = 1
    while True:
        upper = cleaned.upper()
        for suffix in _CURRENCY_SUFFIXES:
            if upper.endswith(suffix) and cleaned[: len(cleaned) - len(suffix)].rstrip():
                cleaned = cleaned[: len(cleaned) - len(suffix)].rstrip()
                break
        else:
            for word, multiplier in _SCALES:
                head = cleaned[: len(cleaned) - len(word)].rstrip()
                # A scale word only counts when digits precede it, so "krupees"
                # or a bare "k" is still refused rather than read as a thousand.
                if upper.endswith(word) and head and head[-1].isdigit():
                    if scale != 1:
                        raise ValueError(f"more than one scale word in amount: {text!r}")
                    scale = multiplier
                    cleaned = head
                    break
            else:
                break

    if not cleaned:
        raise ValueError(f"no digits in amount: {text!r}")

    integer_part, separator, fraction = cleaned.partition(".")
    if not _INTEGER_PART.match(integer_part):
        raise ValueError(f"malformed digit grouping in amount: {text!r}")
    if separator and not fraction.isdigit():
        raise ValueError(f"malformed decimal part in amount: {text!r}")

    cleaned = integer_part.replace(",", "") + separator + fraction

    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"not a valid rupee amount: {text!r}") from None

    if not amount.is_finite():
        raise ValueError(f"not a finite amount: {text!r}")

    # Scaled before the paise check, because "7.50 crore" has two decimal places
    # and is still an exact number of paise, while "0.001 rupees" is not. The
    # test that matters is whether the result lands on a whole paisa.
    amount = amount * scale

    in_paise = amount.scaleb(MAX_DECIMAL_PLACES)
    if in_paise != in_paise.to_integral_value():
        raise ValueError(
            f"{text!r} is not a whole number of paise; IntentGuard will not round a stated amount"
        )

    paise = int(in_paise)
    return -paise if negative else paise


def _group_indian(rupees: int) -> str:
    """Indian digit grouping: last three digits, then pairs. 1299000 -> 12,99,000."""
    digits = str(rupees)
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join([*groups, tail])


def format_paise(paise: int) -> str:
    """Integer paise to display text. Integer division only, both directions."""
    _require_paise(paise)
    sign = "-" if paise < 0 else ""
    rupees, remainder = divmod(abs(paise), PAISE_PER_RUPEE)
    return f"{sign}₹{_group_indian(rupees)}.{remainder:02d}"


def sum_paise(amounts: Iterable[int]) -> int:
    """Sum integer paise, rejecting any non-integer member."""
    total = 0
    for index, amount in enumerate(amounts):
        total += _require_paise(amount, f"amount[{index}]")
    return total


# --- money as a declared type ---------------------------------------------


def coerce_to_paise(value: object) -> object:
    """Accept integer paise, or the text a person wrote, and yield paise.

    Money parsing belongs in one declared type rather than at each call site.
    Before this, the amount arrived as a string, a regex decided whether it
    looked like money, and a `float()` decided whether it was big enough to be a
    price -- which crashed outright on "20k" and, worse, put a float in the
    money path to make a decision about a payment.

    A bool is rejected explicitly: `True` is an int in Python, and a flag
    silently read as one paisa is the kind of thing that only shows up in
    production.
    """
    if isinstance(value, bool):
        raise ValueError("a boolean is not an amount")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return parse_rupees(value)
    return value


# Every field that holds money uses this, so "₹1.25 lakh", "20k" and 125000 all
# arrive at the same integer and nothing downstream has to guess which it got.
Paise = Annotated[int, BeforeValidator(coerce_to_paise)]
