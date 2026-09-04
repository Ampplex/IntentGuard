"""The Intent Mandate as IntentGuard holds it.

This type lives in core/ and not in ledger/ because the policy engine has to
compare an Offer against it, and policy/ may not import ledger/. ledger/ owns
the machinery -- extraction, confidence, persistence, TTL enforcement -- not the
type.

Nothing here evaluates expiry. TTL is data; deciding whether it has run out
needs a clock, and the clock is injected into the policy entrypoint so the
engine stays deterministic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import Field, field_validator, model_validator

from .base import StrictModel
from .enums import Category, Condition, LedgerStatus, QuantityMode

T = TypeVar("T")


class ConfidenceField(StrictModel, Generic[T]):
    """One extracted value and how much the extractor trusts it.

    The engine never sees this type. Confidence rides alongside the constraints
    on IntentLedger.confidence so that policy/ compares nothing but integers,
    strings and enums -- which is what keeps a probabilistic number structurally
    incapable of moving a money comparison.
    """

    value: T
    confidence: float = Field(ge=0.0, le=1.0)


class HardConstraints(StrictModel):
    """What the user actually authorized. Every field here can block a payment."""

    category: Category
    max_total_paise: int = Field(ge=0)
    currency: str = "INR"

    @field_validator("currency")
    @classmethod
    def _single_currency(cls, value: str) -> str:
        """IntentGuard is INR only, and that is a decision rather than an oversight.

        The currency field exists so a non-INR quote is an immediate block, never
        so a mandate can be denominated in something else. A mandate carrying USD
        would have made a USD offer pass the one check the spec calls immediate.
        Normalise case, refuse anything else.
        """
        normalised = value.strip().upper()
        if normalised != "INR":
            raise ValueError(
                f"IntentGuard is single-currency and settles in INR; got {value!r}. "
                "The currency field exists to reject foreign quotes, not to denominate "
                "a mandate."
            )
        return normalised

    quantity: int = Field(default=1, ge=1)
    quantity_mode: QuantityMode = QuantityMode.EXACT
    condition: Condition | None = None
    recurring_allowed: bool = False
    emi_allowed: bool = False
    addons_allowed: bool = False


class SoftPreferences(StrictModel):
    """Ranking signals. These never block; they feed drift."""

    brand: str | None = None
    colour: str | None = None
    delivery_speed: str | None = None


class IntentLedger(StrictModel):
    intent_id: str
    raw_instruction: str
    hard: HardConstraints
    soft: SoftPreferences = SoftPreferences()
    confidence: dict[str, float] = Field(default_factory=dict)
    status: LedgerStatus = LedgerStatus.AWAITING_CONFIRMATION
    created_at: datetime
    ttl_seconds: int = Field(default=3600, ge=0)

    @model_validator(mode="after")
    def _confidence_keys_are_constraint_fields(self) -> IntentLedger:
        known = set(HardConstraints.model_fields) | set(SoftPreferences.model_fields)
        unknown = sorted(set(self.confidence) - known)
        if unknown:
            raise ValueError(f"confidence keys are not constraint fields: {unknown}")
        out_of_range = sorted(k for k, v in self.confidence.items() if not 0.0 <= v <= 1.0)
        if out_of_range:
            raise ValueError(f"confidence values outside 0..1: {out_of_range}")
        return self
