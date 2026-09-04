"""What the extractor is allowed to return.

Two properties matter more than the field list.

There is no decision field, and there is no vocabulary for one. A model reading
a hostile instruction cannot approve anything because the shape it must answer
in has nowhere to put an approval. That is the structural half of the injection
defence, and it is a property of this file rather than of any prompt.

No field here is a number of paise. The model reports the amount as the text it
found -- "5,000", "Rs 4999.50" -- and a deterministic parser turns that into
integer paise. The model never does arithmetic, so it can never be talked into
arithmetic that favours the merchant.
"""

from __future__ import annotations

from pydantic import Field

from ..core.base import StrictModel

# Names the response schema must never contain. A field called any of these
# would give a model somewhere to express an approval.
FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "decision",
        "approve",
        "approved",
        "allow",
        "allowed",
        "block",
        "blocked",
        "authorize",
        "authorized",
        "authorised",
        "verdict",
        "outcome",
        "safe",
        "ok",
        "permitted",
        "escalate",
    }
)


class ExtractedIntent(StrictModel):
    """Structured fields read out of a user's instruction. Facts, never findings."""

    category: str | None = Field(
        default=None, description="One of the merchant taxonomy categories, or null if unclear."
    )
    max_total_text: str | None = Field(
        default=None,
        description="The spending limit exactly as the user stated it, as text. "
        "Never compute or convert it. Null if the user gave no limit.",
    )
    limit_is_per_unit: bool = Field(
        default=False,
        description="True only if the user explicitly said the limit is per item, "
        "using a word like each, apiece or per pair.",
    )
    quantity: int | None = Field(default=None, description="How many items, or null if unstated.")
    quantity_mode: str = Field(
        default="exact",
        description="exact, at_most if the user said 'up to', at_least if they said 'at least'.",
    )
    condition: str | None = Field(
        default=None, description="new, refurbished, used or open_box. Null if unstated."
    )
    recurring_allowed: bool = Field(
        default=False, description="True only if the user asked for or accepted an ongoing charge."
    )
    emi_allowed: bool = Field(
        default=False, description="True only if the user accepted paying in instalments."
    )
    addons_allowed: bool = Field(
        default=False, description="True only if the user said extras or add-ons are acceptable."
    )
    product_ref: str | None = Field(
        default=None, description="The specific product named by the user, or null."
    )
    exclusions: list[str] = Field(
        default_factory=list, description="Things the user ruled out, as short terms."
    )
    brand: str | None = None
    colour: str | None = None
    delivery_speed: str | None = None
    vague_phrases: list[str] = Field(
        default_factory=list,
        description="Phrases in the instruction that are too imprecise to act on, "
        "such as 'nothing too pricey' or 'a few'. Quote them from the instruction.",
    )
