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
from .similarity import LexicalSimilarity, Similarity

WEIGHTS: dict[str, float] = {
    "brand": 0.5,
    "delivery_speed": 0.3,
    "colour": 0.2,
}

# Below this, two values for the same preference are different things rather
# than the same thing spelled differently.
MATCH_THRESHOLD = 0.6


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
    if scorer.score(wanted, offered) >= MATCH_THRESHOLD:
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


def _delivery_of(offer: Offer) -> str | None:
    """The shipping line's label, which is where a merchant names the speed."""
    for item in offer.line_items:
        if item.kind.value == "shipping":
            return item.label
    return None
