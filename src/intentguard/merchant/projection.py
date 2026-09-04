"""What a merchant is allowed to know about a mandate.

The ceiling is absent, and its absence is the whole point. A merchant that can
see max_total_paise quotes just under it, every time, and the guard becomes the
mechanism by which the user overpays. Everything else the merchant needs in
order to quote honestly is here.

The projection is built by allowing fields, never by removing them. A new field
on HardConstraints is invisible to the merchant until someone adds it here on
purpose, which is the safe direction for a mistake to fall.
"""

from __future__ import annotations

from pydantic import Field

from ..core.base import StrictModel
from ..core.enums import Category, Condition, QuantityMode
from ..core.intent import IntentLedger

# Named so the leak test can state what it is checking rather than trusting a
# field list to stay short.
NEVER_PROJECTED = ("max_total_paise", "confidence", "raw_instruction")


class MerchantView(StrictModel):
    """The bounded view. No ceiling, no confidence, no raw instruction.

    raw_instruction is withheld for the same reason as the ceiling: a user who
    writes "I can stretch to 6000 if I must" has stated a ceiling in prose, and
    handing the sentence over hands over the number.
    """

    intent_id: str
    category: Category
    quantity: int = Field(ge=1)
    quantity_mode: QuantityMode
    currency: str
    condition: Condition | None = None
    recurring_permitted: bool
    emi_permitted: bool
    addons_permitted: bool
    product_ref: str | None = None
    exclusions: tuple[str, ...] = ()
    brand_preference: str | None = None
    colour_preference: str | None = None
    delivery_preference: str | None = None


def project(ledger: IntentLedger) -> MerchantView:
    """Build the merchant's view of a mandate by naming what it may see."""
    hard = ledger.hard
    return MerchantView(
        intent_id=ledger.intent_id,
        category=Category(hard.category),
        quantity=hard.quantity,
        quantity_mode=QuantityMode(hard.quantity_mode),
        currency=hard.currency,
        condition=Condition(hard.condition) if hard.condition else None,
        recurring_permitted=hard.recurring_allowed,
        emi_permitted=hard.emi_allowed,
        addons_permitted=hard.addons_allowed,
        product_ref=hard.product_ref,
        exclusions=hard.exclusions,
        brand_preference=ledger.soft.brand,
        colour_preference=ledger.soft.colour,
        delivery_preference=ledger.soft.delivery_speed,
    )
