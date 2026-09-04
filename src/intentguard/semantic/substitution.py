"""Did the product change between the opening quote and the final cart?

This is the half of substitution detection that no exact comparison can do, and
it is deliberately weaker than the half that can.

Where a mandate pins a product, `policy/` compares identities exactly and blocks
on a mismatch. There is no model in that path and no score, which is what makes
blocking safe. Where nothing is pinned, the only signal available is that the
thing being sold stopped resembling the thing that was being negotiated, and
that signal is a number produced by a similarity function.

**A similarity score never blocks a payment.** It raises a question. Amendment 3
settled this by splitting on how the signal is computed rather than what it is
about, and the reason is not squeamishness: an embedding threshold gating a
payment is a probabilistic number moving money, which is the exact thing this
project was built to argue against. A test asserts nothing here can emit a BLOCK.

The lexical scorer cannot tell "WH-1000XM5" from "WH-1000XM4", which are
genuinely different products, apart from "Gel-Contend 9" and "Gel-Contend 9
(2024)", which are the same one listed twice. That ambiguity is the argument for
escalating rather than deciding.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..core.decision import Violation
from ..core.enums import Outcome
from ..core.violations import ViolationCode, explain
from .similarity import Similarity, tokens

# Calibrated against data/dev/substitutions.json. See product_match_score for why
# the measure is asymmetric; with a symmetric score the classes did not separate
# at any threshold.
DEFAULT_SUBSTITUTION_THRESHOLD = 0.9

# An added token carrying a digit is a model number, a capacity or a tier, and
# those name a different thing to buy. An added word without one is description.
ADDED_IDENTIFIER_PENALTY = 0.5

# How much of another product's distinguishing name has to appear in the
# description before it counts as naming that product too. Calibrated against
# the shelf-aware pairs in data/dev/substitutions.json.
DEFAULT_CONFUSION_THRESHOLD = 0.5


def _has_digit(token: str) -> bool:
    return any(character.isdigit() for character in token)


def product_match_score(negotiated: str, delivered: str) -> float:
    """How much of the agreed product is still present in what arrived.

    Deliberately asymmetric, and the calibration set is what forced that. A
    symmetric overlap punishes a merchant for describing the same item more
    fully: "Midnight's Children" against "Midnight's Children by Salman Rushdie"
    scored 0.51, barely above "Asics Gel-Contend 9" against "Nike Revolution 7".
    No threshold separated the classes, because the measure was answering the
    wrong question.

    The right question is coverage: is everything that was agreed still there?
    Extra words then cost nothing, which is correct, since a retailer adding
    "Bluetooth earbuds" has not changed the earbuds.

    Coverage alone is too generous in one direction. "Electric Kettle" is fully
    covered by "Electric Kettle 1.5L Pro", which is a different appliance at a
    different price. So an added token containing a digit -- a model number, a
    capacity, a tier -- halves the score, because those name a different thing
    to buy rather than describe the same one.
    """
    agreed = tokens(negotiated)
    arrived = tokens(delivered)
    if not agreed:
        return 0.0

    coverage = len(agreed & arrived) / len(agreed)
    added_identifiers = {token for token in arrived - agreed if _has_digit(token)}
    if added_identifiers:
        coverage *= ADDED_IDENTIFIER_PENALTY
    return coverage


def names_another_product(
    negotiated: str,
    delivered: str,
    alternatives: Iterable[str],
    *,
    threshold: float = DEFAULT_CONFUSION_THRESHOLD,
) -> str | None:
    """Does the description also name something else on the merchant's shelf?

    This closes the evasion coverage cannot see. A merchant that keeps the
    agreed name and appends a different product's -- "Asics Gel-Contend 9
    replacement, Nike Revolution" -- has a description in which everything
    agreed is still present, so coverage reads one and nothing looks wrong.

    What gives it away is knowing what else the merchant sells. The test is not
    how much of the alternative appears, which would fire on any two products
    sharing a brand, but how much of what makes it *distinct from the agreed
    product* appears. "Asics Gel-Kayano 30" shares "asics" and "gel" with
    "Asics Gel-Contend 9", and those shared words say nothing; "kayano" and "30"
    say everything. A description containing them is describing a Kayano.

    Returns the alternative it found, or None. Escalates, like everything else
    here, because a name appearing in a description is evidence and not proof.
    """
    agreed = tokens(negotiated)
    arrived = tokens(delivered)
    if not arrived:
        return None

    for alternative in alternatives:
        distinctive = tokens(alternative) - agreed
        if not distinctive:
            # Indistinguishable from what was agreed, so its presence says nothing.
            continue
        if len(distinctive & arrived) / len(distinctive) >= threshold:
            return alternative
    return None


def assess_substitution(
    negotiated: str,
    delivered: str,
    *,
    similarity: Similarity | None = None,
    threshold: float = DEFAULT_SUBSTITUTION_THRESHOLD,
    alternatives: Iterable[str] = (),
    confusion_threshold: float = DEFAULT_CONFUSION_THRESHOLD,
) -> list[Violation]:
    """Compare what was being negotiated with what arrived.

    Returns an escalation, never a block. `negotiated` is the product described
    in the opening quote; `delivered` is the product in the final cart. A swap
    partway through a negotiation is the drift this exists to catch, and it is
    invisible to any check that only ever sees the final offer.
    """
    if not negotiated.strip() or not delivered.strip():
        return []

    score = (
        similarity.score(negotiated, delivered)
        if similarity is not None
        else product_match_score(negotiated, delivered)
    )
    confused_with = names_another_product(
        negotiated, delivered, alternatives, threshold=confusion_threshold
    )
    if score >= threshold and confused_with is None:
        return []

    observed = (
        f"{delivered} (which also names {confused_with})"
        if confused_with is not None
        else delivered
    )
    return [
        Violation(
            code=ViolationCode.PRODUCT_SUBSTITUTION,
            # Deliberately not DEFAULT_OUTCOME, which is BLOCK for this code.
            # The code names what was noticed; the outcome reflects how well it
            # is known, and a similarity score is never known well enough.
            outcome=Outcome.ESCALATE,
            explanation=explain(
                ViolationCode.PRODUCT_SUBSTITUTION, expected=negotiated, observed=observed
            ),
            field="product",
            expected=negotiated,
            observed=observed,
        )
    ]
