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
from ..core.vocabulary import CATEGORY_WORDS, GENERIC_PRODUCT_WORDS
from .confidence import DEFAULT_THRESHOLD, score_extraction
from .extractor import RuleBasedExtractor, material_product_ref
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

    generic = set(GENERIC_PRODUCT_WORDS)
    if category is not None:
        generic |= set(re.split(r"[^a-z0-9]+", Category(category).value))
        generic |= set(CATEGORY_WORDS.get(Category(category).value, ()))

    return raw.strip() if tokens - generic else None


_SCAFFOLD_WORDS = frozenset(
    {
        # who is asking, and what they are doing
        "i",
        "we",
        "me",
        "my",
        "us",
        "our",
        "you",
        "want",
        "wants",
        "wanted",
        "need",
        "needs",
        "needed",
        "like",
        "would",
        "buy",
        "buying",
        "get",
        "order",
        "purchase",
        "please",
        "kindly",
        "find",
        "look",
        "looking",
        # how much they will spend
        "budget",
        "budgeted",
        "limit",
        "limited",
        "max",
        "maximum",
        "spend",
        "spending",
        "under",
        "below",
        "upto",
        "up",
        "to",
        "at",
        "most",
        "around",
        "about",
        "within",
        "cost",
        "costs",
        "costing",
        "price",
        "priced",
        "total",
        "rs",
        "rupees",
        "rupee",
        "inr",
        # judgements that describe nothing on any shelf
        "decent",
        "nice",
        "quality",
        "basic",
        "simple",
        "proper",
        "solid",
        "expensive",
        "pricey",
        "affordable",
        "reasonable",
        "better",
        "great",
        "nothing",
        "anything",
        "something",
        "too",
        "very",
        "quite",
        "really",
        "much",
        # payment arrangements, which have fields of their own
        "subscription",
        "subscriptions",
        "emi",
        "recurring",
        "instalment",
        "instalments",
        "installment",
        "installments",
        "trial",
        "addon",
        "addons",
        # connective tissue
        "and",
        "or",
        "but",
        "with",
        "without",
        "no",
        "not",
        "is",
        "are",
        "be",
        "that",
        "this",
        "it",
        "if",
        "then",
        "also",
    }
)


def recovered_product_ref(
    instruction: str,
    category: Category | None,
    budget_text: str | None,
    quantity: int | None = None,
) -> str | None:
    """A named product recovered from the user's own words.

    product_ref is the field that lets a substitution *block*, and leaving it to
    the model alone means an extraction miss opens a payment path. It did: asked
    for a "macbook pro m5" the model returned null, so nothing was pinned, and
    the engine allowed a pair of earbuds -- the only comparison left was the
    merchant's opening move against the merchant's own delivery, and those
    agreed. A prompt is a request; this is a rule.

    The test for "named one product rather than a kind of thing" is a model
    designation: a token carrying a digit, alongside a word, once the digits
    that are a budget or a count have been removed. "macbook pro m5"
    and "iphone 15 pro" name a product; "a yoga mat" and "running shoes" name a
    kind, and pinning on those would refuse every offer in the category. This is
    deliberately narrower than the category word lists, which are incomplete --
    "yoga" and "mat" are absent from them, and a filter that trusted them pinned
    "a yoga mat" and would have blocked the one the merchant actually stocks.

    The limit of it, stated plainly: "buy me a MacBook Pro" carries no model
    number, so nothing is recovered and that case still rests on the model
    reporting product_ref itself.
    """
    if not instruction or not instruction.strip():
        return None

    # The budget is the user's own words too, and its digits would otherwise
    # read as a model number. Removed by the text the extractor reported.
    text = instruction
    if budget_text:
        text = re.sub(re.escape(budget_text), " ", text, flags=re.IGNORECASE)

    # A count is not a model number. "buy 3 shirts" would otherwise pin "3
    # shirts" and refuse the shirts the user asked for.
    counted = str(quantity) if quantity and quantity > 1 else None

    words = [
        word
        for word in re.findall(r"[A-Za-z0-9]+", text)
        if word.lower() not in _SCAFFOLD_WORDS
        and word.lower() not in GENERIC_PRODUCT_WORDS
        and word != counted
    ]
    if not words:
        return None

    names_a_model = any(any(ch.isdigit() for ch in word) for word in words)
    names_a_thing = any(word.isalpha() for word in words)
    if not (names_a_model and names_a_thing):
        return None

    return meaningful_product_ref(" ".join(words), category)


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
    recovered_material = material_product_ref(instruction)
    deterministic = RuleBasedExtractor().extract(instruction)
    if recovered_material or deterministic.exclusions:
        material = recovered_material.split(maxsplit=1)[0] if recovered_material else None
        explicit_exclusions = {term.casefold() for term in deterministic.exclusions}
        exclusions = tuple(
            term
            for term in extracted.exclusions
            if not (material and term.casefold() == material and material not in explicit_exclusions)
        )
        extracted = extracted.model_copy(
            update={
                "product_ref": extracted.product_ref or recovered_material,
                "exclusions": exclusions,
            }
        )
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
        product_ref=(
            meaningful_product_ref(extracted.product_ref, category)
            or recovered_product_ref(
                instruction, category, extracted.max_total_text, extracted.quantity
            )
        ),
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
