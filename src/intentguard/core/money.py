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

    upper = cleaned.upper()
    for suffix in _CURRENCY_SUFFIXES:
        if upper.endswith(suffix):
            cleaned = cleaned[: len(cleaned) - len(suffix)].rstrip()
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

    exponent = amount.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -MAX_DECIMAL_PLACES:
        raise ValueError(
            f"{text!r} states more than {MAX_DECIMAL_PLACES} decimal places; "
            "IntentGuard will not round a stated amount"
        )

    paise = int(amount.scaleb(MAX_DECIMAL_PLACES))
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
