"""Assembling a mandate from an extraction.

Every conversion from text to money happens here, with the deterministic parser,
never in the model. If the stated amount cannot be parsed exactly, the mandate is
not built -- IntentGuard does not round a budget and does not guess one.

A mandate whose weakest constraint falls below the confidence threshold is
proposed rather than activated. It goes to the user as a question with the
reading attached, which is the failure the track asks to see handled gracefully.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from ..core.base import StrictModel
from ..core.enums import Category, Condition, LedgerStatus, QuantityMode
from ..core.intent import HardConstraints, IntentLedger, SoftPreferences
from ..core.money import format_paise, parse_rupees
from .confidence import DEFAULT_THRESHOLD, score_extraction
from .extractor import CATEGORY_WORDS
from .schema import ExtractedIntent

# Without these two, there is no mandate to speak of: nothing to spend against
# and nothing to spend it on.
REQUIRED_FIELDS = ("max_total_paise", "category")


class LedgerProposal(StrictModel):
    """The result of reading an instruction.

    `ledger` is None when the instruction did not yield enough to build one at
    all. `question` is populated whenever a person needs to answer something
    before money can move.
    """

    ledger: IntentLedger | None
    extracted: ExtractedIntent
    confidence: dict[str, float]
    question: str | None = None
    weak_fields: tuple[str, ...] = ()


def _ceiling_paise(extracted: ExtractedIntent) -> int | None:
    """Text to integer paise, with the per-unit rule applied.

    An explicit per-unit marker multiplies by quantity. Nothing else does: an
    unmarked multi-quantity instruction is ambiguous, and the confidence score
    already drives it to a question rather than a guess.
    """
    if extracted.max_total_text is None:
        return None
    try:
        stated = parse_rupees(extracted.max_total_text)
    except (ValueError, TypeError):
        return None
    if extracted.limit_is_per_unit and extracted.quantity and extracted.quantity > 1:
        return stated * extracted.quantity
    return stated


# Words that describe a kind of thing rather than name one. A reference built
# only from these is a category, and pinning a mandate to a category blocks every
# offer in it.
_GENERIC_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "for",
        "pair",
        "set",
        "new",
        "some",
        "any",
        "item",
        "items",
        "product",
        "products",
        "thing",
        "things",
        "one",
        "unit",
        "units",
        "running",
        "wireless",
        "electric",
        "cotton",
        "leather",
        "steel",
        "plain",
        "small",
        "medium",
        "large",
        "cheap",
        "good",
        "best",
    }
)


def meaningful_product_ref(raw: str | None, category: Category | None) -> str | None:
    """A named product, or None when the phrase only names a kind of thing.

    product_ref is the one field that lets substitution *block*, so a value in it
    has to actually distinguish one product from another. A model asked to
    extract it from "buy me a pair of new running shoes" will happily answer
    "running shoes", and that pins the mandate to a phrase no catalog entry
    matches, blocking every offer in the category as a substitution.

    The test is whether anything is left once category words and generic
    descriptors are removed. "running shoes" leaves nothing. "Asics Gel-Contend
    9" leaves all of it. Checked here rather than only in a prompt, because a
    prompt is a request and this is a rule.
    """
    if not raw or not raw.strip():
        return None

    tokens = {t for t in re.split(r"[^a-z0-9]+", raw.lower()) if t}
    if not tokens:
        return None

    generic = set(_GENERIC_WORDS)
    if category is not None:
        generic |= set(re.split(r"[^a-z0-9]+", Category(category).value))
        generic |= set(CATEGORY_WORDS.get(Category(category).value, ()))

    return raw.strip() if tokens - generic else None


def _enum_or_none(enum_type, raw: str | None):
    if raw is None:
        return None
    try:
        return enum_type(raw.strip().lower().replace("-", "_").replace(" ", "_"))
    except ValueError:
        return None


def _question_for(extracted: ExtractedIntent, weak: tuple[str, ...], ceiling: int | None) -> str:
    """Ask about the specific thing that is unclear, with the current reading."""
    parts = []
    if "max_total_paise" in weak:
        if ceiling is None:
            parts.append("how much you want to spend at most")
        else:
            parts.append(f"whether {format_paise(ceiling)} is the right limit for the whole order")
    if "category" in weak:
        parts.append("what kind of item this is")
    if "quantity" in weak:
        parts.append("how many you want")

    asked = parts[0] if len(parts) == 1 else ", and ".join([", ".join(parts[:-1]), parts[-1]])
    quoted = ", ".join(f'"{phrase}"' for phrase in extracted.vague_phrases[:3])
    because = f" {quoted} is not something IntentGuard can turn into a limit." if quoted else ""
    return f"Before spending anything, please confirm {asked}.{because}".replace("..", ".")


def build_ledger(
    instruction: str,
    extracted: ExtractedIntent,
    *,
    created_at: datetime,
    threshold: float = DEFAULT_THRESHOLD,
    ttl_seconds: int = 3600,
    intent_id: str | None = None,
) -> LedgerProposal:
    """Turn an extraction into a mandate, or into a question."""
    confidence = score_extraction(instruction, extracted)
    ceiling = _ceiling_paise(extracted)
    category = _enum_or_none(Category, extracted.category)

    if ceiling is None:
        confidence["max_total_paise"] = 0.0
    if category is None:
        confidence["category"] = 0.0

    weak = tuple(name for name in REQUIRED_FIELDS if confidence.get(name, 0.0) < threshold)
    if extracted.quantity is not None and confidence.get("quantity", 1.0) < threshold:
        weak = (*weak, "quantity")

    if ceiling is None or category is None:
        return LedgerProposal(
            ledger=None,
            extracted=extracted,
            confidence=confidence,
            question=_question_for(extracted, weak or REQUIRED_FIELDS, ceiling),
            weak_fields=weak or REQUIRED_FIELDS,
        )

    hard = HardConstraints(
        category=category,
        max_total_paise=ceiling,
        quantity=extracted.quantity or 1,
        quantity_mode=_enum_or_none(QuantityMode, extracted.quantity_mode) or QuantityMode.EXACT,
        condition=_enum_or_none(Condition, extracted.condition),
        recurring_allowed=extracted.recurring_allowed,
        emi_allowed=extracted.emi_allowed,
        addons_allowed=extracted.addons_allowed,
        product_ref=meaningful_product_ref(extracted.product_ref, category),
        exclusions=tuple(extracted.exclusions),
    )
    ledger = IntentLedger(
        intent_id=intent_id or f"int_{uuid.uuid4().hex[:12]}",
        raw_instruction=instruction,
        hard=hard,
        soft=SoftPreferences(
            brand=extracted.brand,
            colour=extracted.colour,
            delivery_speed=extracted.delivery_speed,
        ),
        confidence=confidence,
        status=LedgerStatus.AWAITING_CONFIRMATION if weak else LedgerStatus.ACTIVE,
        created_at=created_at,
        ttl_seconds=ttl_seconds,
    )
    return LedgerProposal(
        ledger=ledger,
        extracted=extracted,
        confidence=confidence,
        question=_question_for(extracted, weak, ceiling) if weak else None,
        weak_fields=weak,
    )


def confirm(ledger: IntentLedger, *, now: datetime, ttl_seconds: int | None = None) -> IntentLedger:
    """A human answered. The mandate becomes live with a fresh clock.

    TTL restarts rather than resuming, because the time a person spent deciding
    is not time the authorization was live. Expiring a transaction someone was
    mid-approval of is a bad product and a worse demo.

    The mandate is also marked human_confirmed, which supersedes the confidence
    scores without erasing them: the extractor's own assessment stays on the
    record for calibration, and the engine stops asking a question that has
    already been answered.
    """
    return ledger.model_copy(
        update={
            "status": LedgerStatus.ACTIVE,
            "created_at": now,
            "ttl_seconds": ttl_seconds if ttl_seconds is not None else ledger.ttl_seconds,
            # A person has now vouched for the reading, which supersedes whatever
            # the extractor thought of it. Without this the mandate kept raising
            # LOW_CONFIDENCE after being confirmed and the escalation could never
            # complete.
            "human_confirmed": True,
        }
    )
