"""Confidence scoring.

CLAUDE.md lists this as an open problem and says self-reported confidence from a
model is close to meaningless. It is: a model asked how sure it is will tell you
what the phrasing sounds like, not what it knows.

The approach here is rules over language, not introspection. A ceiling extracted
from "under 5000 rupees" is trustworthy because the instruction contains a
number and a bound. A ceiling extracted from "nothing too pricey" is not, and it
is the instruction that says so, not the model.

Multi-sample agreement is the second half of the hybrid and belongs with the
model-backed extractor: sample the extraction several times and measure whether
the fields agree. It costs N times the latency and money, so it runs only for
fields the rules below already flagged as risky.

Every number here is a starting point rather than a finding. They are calibrated
against a development set, never against the gold set.
"""

from __future__ import annotations

import re

# Words that promise imprecision. Their presence near a field is evidence the
# field cannot be extracted defensibly, whatever the model reports.
VAGUE_TERMS = (
    "decent",
    "reasonable",
    "cheap",
    "affordable",
    "budget-friendly",
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
    "ish",
    "around",
    "roughly",
    "approximately",
    "about",
    "maybe",
    "probably",
    "whatever",
    "best",
    "cheapest",
    "reasonably",
)

# A stated limit needs a number and a bound to be a limit at all.
_HAS_DIGITS = re.compile(r"\d")
_BOUND_WORDS = re.compile(
    r"\b(under|below|less than|no more than|max|maximum|budget|within|up to|upto|at most)\b",
    re.IGNORECASE,
)
_PER_UNIT_MARKER = re.compile(r"\b(each|apiece|per\s+\w+|a\s?piece)\b", re.IGNORECASE)
_TOTAL_MARKER = re.compile(r"\b(total|altogether|in total|for the lot|all in)\b", re.IGNORECASE)
_HEDGED_QUANTITY = re.compile(
    r"\b(a few|some|several|a couple|couple of|multiple)\b", re.IGNORECASE
)

# Penalties, subtracted from a starting confidence of 1.0.
PENALTY_VAGUE_NEARBY = 0.55
PENALTY_NO_BOUND_WORD = 0.25
PENALTY_MISSING = 1.0
PENALTY_UNMARKED_MULTI_UNIT = 0.45
PENALTY_HEDGED_QUANTITY = 0.5

# Invented in the specification and treated as such until data says otherwise.
DEFAULT_THRESHOLD = 0.85


# Matched on word boundaries, not as substrings. "refurbished" contains "ish",
# and a substring match dragged a perfectly clear instruction below the threshold.
_VAGUE_PATTERN = re.compile(
    r"(?<![a-z])(" + "|".join(re.escape(term) for term in VAGUE_TERMS) + r")(?![a-z])",
    re.IGNORECASE,
)


def vague_terms_in(text: str) -> list[str]:
    return [match.group(1).lower() for match in _VAGUE_PATTERN.finditer(text)]


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def score_ceiling(
    instruction: str,
    max_total_text: str | None,
    quantity: int | None,
    limit_is_per_unit: bool,
    quantity_mode: str = "exact",
) -> float:
    """How much to trust the extracted spending limit."""
    if max_total_text is None:
        return 0.0

    score = 1.0
    if not _HAS_DIGITS.search(max_total_text):
        score -= PENALTY_VAGUE_NEARBY
    if not _BOUND_WORDS.search(instruction):
        score -= PENALTY_NO_BOUND_WORD
    if vague_terms_in(instruction):
        score -= PENALTY_VAGUE_NEARBY

    # "3 shirts, budget 2000" is genuinely ambiguous to a human reader. Guessing
    # either way blocks a legitimate order or authorizes three times the intent.
    # Only an exact count is ambiguous this way. "up to 3 reams, budget 1500"
    # reads as a total to any English speaker, because a per-item limit paired
    # with an upper bound on the count would be a strange thing to say.
    unmarked_multi_unit = (
        quantity_mode == "exact"
        and quantity is not None
        and quantity > 1
        and not limit_is_per_unit
        and not _PER_UNIT_MARKER.search(instruction)
        and not _TOTAL_MARKER.search(instruction)
    )
    if unmarked_multi_unit:
        score -= PENALTY_UNMARKED_MULTI_UNIT
    return _clamp(score)


def score_quantity(instruction: str, quantity: int | None) -> float:
    if quantity is None:
        return 0.0
    score = 1.0
    if _HEDGED_QUANTITY.search(instruction):
        score -= PENALTY_HEDGED_QUANTITY
    return _clamp(score)


def score_stated(value: object) -> float:
    """Fields that map onto a controlled vocabulary or do not.

    Deliberately not penalised for vague words elsewhere in the instruction. In
    "a decent laptop, nothing too pricey" the vagueness is entirely about price;
    "laptop" is a laptop. Dragging every field down because one phrase was woolly
    produces a question that asks about the wrong thing.
    """
    return 0.0 if value in (None, "", []) else 1.0


def score_extraction(instruction: str, extracted) -> dict[str, float]:
    """Confidence per constraint field, keyed to match IntentLedger.confidence."""
    return {
        "max_total_paise": score_ceiling(
            instruction,
            extracted.max_total_text,
            extracted.quantity,
            extracted.limit_is_per_unit,
            extracted.quantity_mode,
        ),
        "quantity": score_quantity(instruction, extracted.quantity),
        "category": score_stated(extracted.category),
        "condition": score_stated(extracted.condition),
        "product_ref": score_stated(extracted.product_ref),
        "exclusions": score_stated(extracted.exclusions),
    }


def weakest_field(confidence: dict[str, float], required: tuple[str, ...]) -> tuple[str, float]:
    """The field that decides whether the mandate is usable."""
    scored = [(name, confidence.get(name, 0.0)) for name in required]
    return min(scored, key=lambda pair: pair[1])
