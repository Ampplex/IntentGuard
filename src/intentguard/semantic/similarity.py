"""How alike are two product descriptions?

Two implementations behind one protocol, the same shape as the extractors.

LexicalSimilarity is deterministic, needs no model, and is what the tests run
against. It compares word sets and character bigrams, which is enough to tell
"Asics Gel-Contend 9" from "Nike Revolution 7" and enough to recognise
"Asics Gel Contend 9 (2024)" as the same shoe written differently.

EmbeddingSimilarity is the stronger path, kept behind a lazy import so that
neither the tests nor the demo require a model to be downloaded. It is wired and
untested against a real model, which is stated rather than implied.

Whatever computes it, a similarity score never blocks a payment. It can only
raise a question. That rule is not local to this file -- it is why the project
exists -- and substitution.py is where it is enforced.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

_TOKENS = re.compile(r"[a-z0-9]+")

# Words that carry no information about which product this is.
STOPWORDS = frozenset(
    {"the", "a", "an", "of", "for", "with", "and", "new", "pack", "size", "pair", "set"}
)


def tokens(text: str) -> set[str]:
    return {t for t in _TOKENS.findall(text.lower()) if t not in STOPWORDS}


def bigrams(text: str) -> set[str]:
    flat = "".join(_TOKENS.findall(text.lower()))
    return {flat[i : i + 2] for i in range(len(flat) - 1)}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


class Similarity(Protocol):
    def score(self, left: str, right: str) -> float: ...


class LexicalSimilarity:
    """Word overlap and character bigrams, combined.

    Words alone are brittle: "Gel-Contend" and "Gel Contend" tokenise the same
    but "XM5" and "XM4" do not, and neither does a model number against its own
    successor. Bigrams catch the near-misses that word overlap treats as total
    strangers, which matters because a substitution that differs by one
    character is exactly the one worth noticing.
    """

    def __init__(self, word_weight: float = 0.6) -> None:
        if not 0.0 <= word_weight <= 1.0:
            raise ValueError("word_weight is a proportion between zero and one")
        self.word_weight = word_weight

    def score(self, left: str, right: str) -> float:
        if not left.strip() or not right.strip():
            return 0.0
        word = _jaccard(tokens(left), tokens(right))
        char = _jaccard(bigrams(left), bigrams(right))
        return self.word_weight * word + (1.0 - self.word_weight) * char


class EmbeddingSimilarity:
    """Cosine similarity over sentence-transformer embeddings.

    Loaded lazily and locally so there is no network call in the decision path,
    which is what keeps the latency claim true. Untested against a real model
    here, because pulling one is not something the test suite should do.
    """

    def __init__(self, model: Any = None, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model = model
        self._model_name = model_name

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return self._model

    def score(self, left: str, right: str) -> float:
        if not left.strip() or not right.strip():
            return 0.0
        model = self._load()
        vectors = model.encode([left, right])
        first, second = vectors[0], vectors[1]
        dot = sum(a * b for a, b in zip(first, second, strict=True))
        norm_left = sum(a * a for a in first) ** 0.5
        norm_right = sum(b * b for b in second) ** 0.5
        if not norm_left or not norm_right:
            return 0.0
        return max(0.0, min(1.0, dot / (norm_left * norm_right)))
