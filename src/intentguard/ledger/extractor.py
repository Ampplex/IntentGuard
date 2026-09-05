"""Turning a sentence into structured fields.

Two implementations behind one protocol.

RuleBasedExtractor is deterministic, needs no network, and is what the tests
run against. It is not a mock: a demo with no API key still works, and a
deployment that loses its key degrades to it rather than failing open.

ClaudeExtractor is the real path. Its response schema has no decision field, so
a model reading a hostile instruction has nowhere to put an approval. It never
returns a number of paise either -- the amount comes back as the text the user
wrote, and a deterministic parser converts it. The model does no arithmetic, so
it cannot be argued into arithmetic.
"""

from __future__ import annotations

import re
import string
from typing import Protocol

from ..core.money import parse_rupees
from ..core.vocabulary import CATEGORY_WORDS
from .schema import ExtractedIntent

# The merchant taxonomy, reached from the words people actually use.

CONDITION_WORDS = {
    "new": "new",
    "brand new": "new",
    "refurbished": "refurbished",
    "refurb": "refurbished",
    "used": "used",
    "second hand": "used",
    "second-hand": "used",
    "pre-owned": "used",
    "open box": "open_box",
    "open-box": "open_box",
}

# The scale words people actually use. This parser is the fallback when the
# model is throttled, and a fallback that cannot read "20k" or "2 lakh" turns a
# provider hiccup into "please confirm how much you want to spend" -- which is
# what the stress run showed. parse_rupees() already understands these; the
# pattern just has to capture them.
# A bare number under a hundred rupees reads as a count, not a price:
# "up to 3 reams, budget 1500" has two numbers and only one is money.
_COUNT_CEILING_PAISE = 100_00

_SCALE = r"(?:\s*(?:crores?|lakhs?|lacs?|thousand|million|billion|cr|bn|mn|k)\b)?"
_NUMBER = r"\d(?:[\d,]*\d)?(?:\.\d{1,2})?"

_AMOUNT = re.compile(
    r"(?:under|below|less than|no more than|max(?:imum)?|budget(?: is| of)?|within|up ?to|at most)"
    rf"\s*(?:rs\.?|inr|₹)?\s*({_NUMBER}{_SCALE})",
    re.IGNORECASE,
)
_BARE_AMOUNT = re.compile(rf"(?:rs\.?|inr|₹)\s*({_NUMBER}{_SCALE})", re.IGNORECASE)
# People put the bound after the number as often as before: "45000 max",
# "900 for both". Reading only the prefix form loses ordinary instructions.
_TRAILING_AMOUNT = re.compile(
    rf"(?:rs\.?|inr|₹)?\s*({_NUMBER}{_SCALE})\s*"
    r"(?:max(?:imum)?|budget|total|for (?:both|all|the lot|everything))\b",
    re.IGNORECASE,
)
# Counts are small and never followed by a currency word.
_QUANTITY_DIGIT = re.compile(
    r"\b(\d{1,3})\s+(?:pairs?\s+of\s+)?(?!rupees?\b|rs\b|inr\b)[a-z]", re.IGNORECASE
)
_WORD_NUMBERS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "dozen": 12,
}
_PER_UNIT = re.compile(r"\b(each|apiece|per\s+(?:pair|item|unit|piece|one))\b", re.IGNORECASE)
_AT_MOST = re.compile(r"\b(up ?to|at most|no more than)\s+\d", re.IGNORECASE)
_AT_LEAST = re.compile(r"\b(at least|minimum of|no fewer than)\s+\d", re.IGNORECASE)
_NO_RECURRING = re.compile(
    r"\bno (?:recurring|subscription|subscriptions|auto[- ]?renew)", re.IGNORECASE
)
_YES_RECURRING = re.compile(
    r"\b(subscription|recurring)\b(?!\s*(?:s)?\b[^.]*\bno\b)", re.IGNORECASE
)
_YES_EMI = re.compile(
    r"\b(emi|instal?ments?|financing)\b\s*(?:is|are)?\s*(?:fine|ok|okay|allowed)", re.IGNORECASE
)
_NO_EMI = re.compile(r"\bno (?:emi|instal?ments?|financing)\b|\bpay in full\b", re.IGNORECASE)
_YES_ADDONS = re.compile(
    r"\b(add[- ]?ons?|extras?)\b\s*(?:are|is)?\s*(?:fine|ok|okay|allowed|acceptable)",
    re.IGNORECASE,
)
_EXCLUSION = re.compile(
    r"\b(?:no|not|nothing in|without|avoid|except)\s+([a-z][a-z\s-]{2,25}?)(?:[,.]|$| and | but )",
    re.IGNORECASE,
)
_EXCLUSION_STOPWORDS = frozenset(
    {
        "more",
        "less",
        "subscription",
        "subscriptions",
        "recurring",
        "emi",
        "financing",
        "instalments",
        "installments",
        "than",
        "too",
        "much",
        "one",
        "other",
        "else",
    }
)
# Only an explicit naming construction counts. "the Asics Gel-Contend 9" pins a
# product; "a Nike running shoe" expresses a brand preference and must not,
# because a pinned product blocks and a preference never does.
_PRODUCT_REF = re.compile(
    r"\bthe\s+((?:[A-Z][\w-]*|\d[\w-]*)(?:\s+(?:[A-Z][\w-]*|\d[\w-]*)){1,4})",
)
_BRAND = re.compile(r"\b(?:by|from)\s+([A-Z][\w-]+)|\b([A-Z][\w-]+)\s+(?:running|shoe)")
_MATERIALS = ("leather", "mesh", "rubber", "cotton", "polyester", "whey", "wood", "cork", "steel")


def material_product_ref(text: str) -> str | None:
    punctuation = str.maketrans(string.punctuation, " " * len(string.punctuation))
    tokens = text.casefold().translate(punctuation).split()
    for material in _MATERIALS:
        for words in CATEGORY_WORDS.values():
            for word in words:
                for index in range(len(tokens) - 1):
                    same_material = tokens[index] == material
                    same_category = tokens[index + 1].rstrip("s") == word.rstrip("s")
                    if same_material and same_category:
                        return " ".join(tokens[index : index + 2])
    return None

_VAGUE = (
    "decent",
    "reasonable",
    "cheap",
    "affordable",
    "good",
    "nice",
    "quality",
    "premium",
    "not too",
    "nothing too",
    "a few",
    "some",
    "several",
    "a couple",
    "similar",
    "something like",
    "or so",
    "around",
    "roughly",
    "about",
    "whatever",
    "best",
    "cheapest",
)


class Extractor(Protocol):
    """Anything that can turn an instruction into structured fields."""

    def extract(self, instruction: str) -> ExtractedIntent: ...


class RuleBasedExtractor:
    """Deterministic extraction. No network, no model, no surprises.

    Its recall is narrower than a model's and that is the trade. What it does
    return, it returns for a reason a person can read in this file, which makes
    it the right thing for tests and an honest fallback in production.
    """

    def extract(self, instruction: str) -> ExtractedIntent:
        text = instruction.strip()
        lowered = text.lower()

        amount = self._amount(text)

        # Look for a count in what is left once the price is taken out. Otherwise
        # "budget 5000 rupees" reads as five thousand pairs of shoes.
        without_amount = text[: amount.start()] + " " + text[amount.end() :] if amount else text
        quantity, mode = self._quantity(without_amount, without_amount.lower())

        return ExtractedIntent(
            category=self._category(lowered),
            max_total_text=amount.group(1) if amount else None,
            limit_is_per_unit=bool(_PER_UNIT.search(text)),
            quantity=quantity,
            quantity_mode=mode,
            condition=self._condition(lowered),
            recurring_allowed=bool(_YES_RECURRING.search(text)) and not _NO_RECURRING.search(text),
            emi_allowed=bool(_YES_EMI.search(text)) and not _NO_EMI.search(text),
            addons_allowed=bool(_YES_ADDONS.search(text)),
            product_ref=self._product_ref(text),
            exclusions=self._exclusions(text),
            brand=self._brand(text),
            colour=None,
            delivery_speed=None,
            vague_phrases=[term for term in _VAGUE if term in lowered],
        )

    @staticmethod
    def _amount(text: str):
        """The first candidate that reads as money rather than a count.

        "up to 3 reams of paper, budget 1500" contains two numbers after a bound
        word. A bare number below a hundred is far more likely to be a count than
        a price, so it only counts as money when a currency marker says so.
        """
        for pattern in (_AMOUNT, _TRAILING_AMOUNT):
            for match in pattern.finditer(text):
                marked = bool(re.search(r"(rs\.?|inr|₹)", match.group(0), re.IGNORECASE))
                try:
                    paise = parse_rupees(match.group(1))
                except (ValueError, TypeError):
                    # Not money at all. It used to be float(), which read "20k"
                    # as a crash and put a float in the money path besides.
                    continue
                if marked or paise >= _COUNT_CEILING_PAISE:
                    return match
        return _BARE_AMOUNT.search(text)

    @staticmethod
    def _product_ref(text: str) -> str | None:
        match = _PRODUCT_REF.search(text)
        if match:
            return match.group(1).strip()
        return material_product_ref(text)

    @staticmethod
    def _brand(text: str) -> str | None:
        match = _BRAND.search(text)
        if not match:
            return None
        return (match.group(1) or match.group(2)).strip()

    @staticmethod
    def _category(lowered: str) -> str | None:
        for category, words in CATEGORY_WORDS.items():
            if any(re.search(rf"\b{re.escape(word)}s?\b", lowered) for word in words):
                return category
        return None

    @staticmethod
    def _condition(lowered: str) -> str | None:
        for phrase, condition in sorted(CONDITION_WORDS.items(), key=lambda kv: -len(kv[0])):
            if re.search(rf"\b{re.escape(phrase)}\b", lowered):
                return condition
        return None

    @staticmethod
    def _quantity(text: str, lowered: str) -> tuple[int | None, str]:
        mode = "exact"
        if _AT_MOST.search(text):
            mode = "at_most"
        elif _AT_LEAST.search(text):
            mode = "at_least"

        digits = _QUANTITY_DIGIT.search(text)
        if digits:
            return int(digits.group(1)), mode
        for word, value in _WORD_NUMBERS.items():
            if value > 1 and re.search(rf"\b{word}\b", lowered):
                return value, mode
        return None, mode

    @staticmethod
    def _exclusions(text: str) -> list[str]:
        found = []
        for match in _EXCLUSION.finditer(text):
            term = match.group(1).strip().lower()
            head = term.split()[0] if term else ""
            if head and head not in _EXCLUSION_STOPWORDS and len(head) > 2:
                found.append(head)
        return sorted(set(found))
