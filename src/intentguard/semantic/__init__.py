"""Substitution matching and soft drift. Advisory to an escalation, never to a block."""

from .drift import MATCH_THRESHOLD, WEIGHTS, score_drift
from .similarity import (
    EmbeddingSimilarity,
    LexicalSimilarity,
    Similarity,
    bigrams,
    tokens,
)
from .substitution import (
    DEFAULT_CONFUSION_THRESHOLD,
    DEFAULT_SUBSTITUTION_THRESHOLD,
    assess_substitution,
    names_another_product,
    product_match_score,
)

__all__ = [
    "DEFAULT_CONFUSION_THRESHOLD",
    "DEFAULT_SUBSTITUTION_THRESHOLD",
    "MATCH_THRESHOLD",
    "WEIGHTS",
    "EmbeddingSimilarity",
    "LexicalSimilarity",
    "Similarity",
    "assess_substitution",
    "bigrams",
    "names_another_product",
    "product_match_score",
    "score_drift",
    "tokens",
]
