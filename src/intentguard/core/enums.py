"""Controlled vocabularies. No logic lives here."""

from enum import StrEnum


class Outcome(StrEnum):
    """The three outcomes. ESCALATE is a real outcome, not an error path."""

    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"


class LedgerStatus(StrEnum):
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    ACTIVE = "ACTIVE"
    SPENT = "SPENT"
    EXPIRED = "EXPIRED"
    EXECUTION_UNCERTAIN = "EXECUTION_UNCERTAIN"


class Condition(StrEnum):
    """The conditions IntentGuard can judge.

    A merchant string outside this enum is not a BLOCK. You do not know the item
    is bad, only that you cannot judge it, so it escalates as
    UNCLASSIFIABLE_CONDITION. That is why Product.condition is a raw string and
    only HardConstraints.condition is typed as this enum.
    """

    NEW = "new"
    REFURBISHED = "refurbished"
    USED = "used"
    OPEN_BOX = "open_box"


class QuantityMode(StrEnum):
    """Quantity is exact match unless the instruction said otherwise."""

    EXACT = "exact"
    AT_MOST = "at_most"
    AT_LEAST = "at_least"


class LineItemKind(StrEnum):
    PRODUCT = "product"
    SHIPPING = "shipping"
    TAX = "tax"
    FEE = "fee"
    ADDON = "addon"
    DISCOUNT = "discount"


class RecurrenceInterval(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class Category(StrEnum):
    """The merchant's controlled taxonomy.

    Category is matched exactly against this enum by the deterministic engine.
    Mapping loose human language onto it is the extractor's job; product-level
    similarity is semantic/'s job and is a different question.
    """

    ELECTRONICS = "electronics"
    FOOTWEAR = "footwear"
    APPAREL = "apparel"
    HOME_KITCHEN = "home_kitchen"
    BOOKS = "books"
    GROCERY = "grocery"
    BEAUTY = "beauty"
    SPORTS = "sports"
    TOYS = "toys"
    ACCESSORIES = "accessories"
