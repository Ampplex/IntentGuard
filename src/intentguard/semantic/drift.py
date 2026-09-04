"""How far the delivered offer sits from what the user would have preferred.

Drift never blocks. Soft preferences exist to rank offers that already passed
the hard checks and to feed the escalation signal, and a preference that could
stop a payment would be a hard constraint wearing the wrong label.

**The weights.** CLAUDE.md lists these as an open problem and says to choose and
justify rather than pretend a principle exists. The choice:

    brand           0.5   the strongest expression of preference. Naming a brand
                          is the closest a user gets to naming a product without
                          naming one, and getting a different brand is the
                          substitution people actually complain about.
    delivery speed  0.3   affects when the thing arrives, which is sometimes the
                          entire point of the purchase, but is recoverable and
                          usually visible before it matters.
    colour          0.2   cosmetic. Real, and the least costly to be wrong about.

These are a judgement, not a finding. The honest validation is user data about
which mismatches provoke complaints, and no such data exists here. They are
weights on a number that cannot move money, which is what makes an unvalidated
judgement tolerable in this one place.
"""

from __future__ import annotations

from ..core.decision import DriftItem, DriftReport
from ..core.intent import IntentLedger
from ..core.offer import Offer
from .similarity import LexicalSimilarity, Similarity, tokens

WEIGHTS: dict[str, float] = {
    "brand": 0.5,
    "delivery_speed": 0.3,
    "colour": 0.2,
}

# Below this, two values for the same preference are different things rather
# than the same thing spelled differently.
MATCH_THRESHOLD = 0.6


def _preference_met(wanted: str, offered: str, scorer: Similarity) -> bool:
    """Is what the user asked for present in what arrived?

    Coverage rather than similarity, for the same reason substitution matching
    uses it: the two strings are not peers. "express" against "Express delivery"
    is a met preference described more fully, and a symmetric measure scored it
    0.5 and called it drift. What matters is whether the preference is in there,
    not whether the merchant used exactly as many words.
    """
    asked = tokens(wanted)
    if asked and asked <= tokens(offered):
        return True
    return scorer.score(wanted, offered) >= MATCH_THRESHOLD


def _compare(
    field: str, wanted: str | None, offered: str | None, scorer: Similarity
) -> DriftItem | None:
    """One preference, or None when there is nothing to compare.

    A preference the user never expressed cannot drift, and neither can one the
    merchant said nothing about: silence is not a mismatch, and counting it as
    one would make every sparse offer look worse than a wrong one.
    """
    # Stripped before testing for presence. A merchant sending a field of spaces
    # was counted as a mismatch and scored full drift, which reads as "they got
    # the brand wrong" when they simply said nothing.
    wanted = (wanted or "").strip()
    offered = (offered or "").strip()
    if not wanted or not offered:
        return None
    if _preference_met(wanted, offered, scorer):
        return None
    return DriftItem(field=field, requested=wanted, offered=offered, weight=WEIGHTS[field])


def score_drift(
    ledger: IntentLedger, offer: Offer, *, similarity: Similarity | None = None
) -> DriftReport:
    """What the user asked for, softly, against what arrived."""
    scorer = similarity or LexicalSimilarity()
    soft = ledger.soft
    product = offer.product

    candidates = [
        _compare("brand", soft.brand, product.brand, scorer),
        _compare("colour", soft.colour, product.colour, scorer),
        _compare("delivery_speed", soft.delivery_speed, _delivery_of(offer), scorer),
    ]
    items = [item for item in candidates if item is not None]

    # Scored against the preferences the user actually expressed, so that a user
    # who stated one preference and had it missed scores as badly as one who
    # stated three and had all three missed. Dividing by a fixed total would let
    # a system look accurate by ignoring people who asked for little.
    expressed = sum(
        WEIGHTS[field]
        for field, value in (
            ("brand", soft.brand),
            ("colour", soft.colour),
            ("delivery_speed", soft.delivery_speed),
        )
        if value and value.strip()
    )
    missed = sum(item.weight for item in items)
    score = missed / expressed if expressed else 0.0
    return DriftReport(score=min(1.0, score), items=items)


# Words that actually name a speed. A shipping line called "Delivery" or "Free
# delivery" says nothing about how fast it is.
SPEED_WORDS = (
    "express",
    "standard",
    "priority",
    "overnight",
    "next day",
    "next-day",
    "same day",
    "same-day",
    "economy",
    "scheduled",
    "two day",
    "two-day",
    "slow",
    "fast",
    "rush",
)


def _delivery_of(offer: Offer) -> str | None:
    """The delivery speed a merchant named, if they named one at all.

    Reading the whole shipping label as a speed was wrong and misfired
    constantly: a line called "Delivery" compared against a preference for
    "standard" looked like a missed preference, so almost every offer carrying a
    plain shipping line reported drift it had not caused.

    Silence is not a mismatch. A label with no speed word in it is a merchant
    saying nothing about speed, which cannot drift from anything.
    """
    for item in offer.line_items:
        if item.kind.value != "shipping":
            continue
        lowered = item.label.lower()
        if any(word in lowered for word in SPEED_WORDS):
            return item.label
    return None
