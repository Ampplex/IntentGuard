"""What the merchant is offering. Every field here arrived over the wire from an
untrusted party.

Two deliberate choices about types:

``Product.category`` and ``Product.condition`` are raw strings, not enums, even
though the matching constraints are enums. A merchant saying "slightly used"
must produce an escalation, not a parse failure -- you do not know the item is
bad, only that you cannot judge it. Typing them as enums here would turn that
escalation into a 422 and lose the outcome.

``total_paise`` is not validated against the line items at construction. The
mismatch is a BLOCK carrying TOTAL_MISMATCH, and an offer that cannot be built
cannot be decided on. The arithmetic is policy/'s to do.
"""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from .base import StrictModel
from .enums import LineItemKind, RecurrenceInterval


class Product(StrictModel):
    product_id: str
    title: str
    category: str
    condition: str | None = None
    brand: str | None = None
    colour: str | None = None


class LineItem(StrictModel):
    label: str
    amount_paise: int
    kind: LineItemKind

    @model_validator(mode="after")
    def _only_discounts_may_be_negative(self) -> LineItem:
        if self.amount_paise < 0 and self.kind is not LineItemKind.DISCOUNT:
            raise ValueError(
                f"a {self.kind.value} line item may not be negative; "
                "only a discount may carry a negative amount"
            )
        return self


class RecurringCharge(StrictModel):
    """A future-dated obligation. Amount is irrelevant to whether it is one."""

    label: str
    amount_paise: int = Field(ge=0)
    interval: RecurrenceInterval
    starts_after_days: int = Field(default=0, ge=0)


class EmiTerms(StrictModel):
    """Financing on a single purchase. The checked total is every instalment."""

    installment_paise: int = Field(ge=0)
    installment_count: int = Field(ge=1)
    provider: str | None = None


class Offer(StrictModel):
    offer_id: str
    product: Product
    quantity: int = Field(ge=1)
    currency: str
    line_items: list[LineItem] = Field(default_factory=list)
    total_paise: int
    recurring: list[RecurringCharge] = Field(default_factory=list)
    emi: EmiTerms | None = None
    raw_description: str = ""

    @field_validator("line_items")
    @classmethod
    def _at_least_one_line_item(cls, items: list[LineItem]) -> list[LineItem]:
        if not items:
            raise ValueError("an offer must itemise what it is charging for")
        return items
