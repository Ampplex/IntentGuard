"""Hybrid retrieval over the catalog: BM25, character trigrams, and RRF.

**Why this exists.** The lookup here used to be an exact title match with a
fallback to "cheapest thing in the category". That fallback is how asking for a
"macbook pro m5" produced a pair of earbuds, and how asking for "Chelsea Boots"
produced Nike Revolution 7: there was no way for the merchant to say it does not
stock something, so every query landed on a product. A miss has to be
representable, and that is most of what this module is for.

**The arms, and what each is good at.**

- *BM25* rewards rare terms, which is exactly what a model designation is. "m5",
  "t480" and "airdopes" appear in one document each, so their IDF is high and a
  query containing one lands on the right row.
- *Character trigrams* survive the ways people actually write product names:
  "earphone" against "earphones", "boat" against "boAt", "mac book" against
  "macbook". BM25 sees those as different tokens; trigrams do not.
- *Reciprocal rank fusion* combines them without needing their scores to be on
  the same scale, which they are not. RRF only reads positions, so a term-
  frequency score and a trigram overlap can be merged without inventing a
  normalisation that would be arbitrary.

**The dense arm is wired and inert.** A third retriever slots in wherever an
embedding model is available. None is installed here, so it contributes nothing
and `describe()` says so. This is written as two arms honestly rather than three
arms where one is quietly a copy of another: fusing a signal with itself is not
a hybrid, and reporting it as one would be the sort of claim this project exists
to argue against.

**Nothing here decides anything.** This is the untrusted merchant's own search.
A better search makes an honest merchant behave honestly; it does not make the
merchant trustworthy, and the gate re-checks the result either way.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from ..core.vocabulary import CATEGORY_WORDS, GENERIC_PRODUCT_WORDS
from .catalog import CatalogItem

# RRF's smoothing constant. 60 is the value from the original paper, and it is
# kept because nothing here justifies a tuned one.
RRF_K = 60

# BM25's usual parameters. Documents are short and near-uniform in length, so
# these barely matter; they are named rather than inlined so that is visible.
BM25_K1 = 1.5
BM25_B = 0.75

_TRIGRAM_N = 3

# Below this share of the query's trigrams a document is not a candidate. An
# arm that nominates everything contributes noise to the fusion rather than a
# signal: unfiltered, this one ranked "Lenovo IdeaPad Slim 3" first for the
# query "earbuds" and pulled it level with the earphones.
#
# Measured rather than chosen. Across the pairs in the tests, matches scored
# 0.909, 1.000 and 1.000; non-matches scored 0.200, 0.083, 0.083 and 0.000.
# Nothing at all falls between, and 0.5 sits in the middle of that gap.
_TRIGRAM_FLOOR = 0.5


def tokenise(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).split()


def document_for(item: CatalogItem) -> str:
    """Everything an item can honestly be found by.

    The category's own words are included so that "earphone" retrieves an item
    whose title never says the word, which is the ordinary case for brand names.
    """
    parts = [
        item.title,
        item.brand or "",
        item.colour or "",
        item.product_id.replace("_", " "),
        item.category.value.replace("_", " "),
        " ".join(CATEGORY_WORDS.get(item.category.value, ())),
        " ".join(item.materials),
    ]
    return " ".join(part for part in parts if part)


def distinctive(query: str, category_value: str | None) -> set[str]:
    """Query words that name a product rather than a kind of thing.

    The same test the gate applies to a pinned reference, deliberately: a
    merchant that retrieves on words the gate will ignore would pass its own
    search and fail the gate, which is a confusing way to be refused.
    """
    words = set(tokenise(query))
    generic = set(GENERIC_PRODUCT_WORDS)
    if category_value:
        generic |= set(tokenise(category_value))
        generic |= set(CATEGORY_WORDS.get(category_value, ()))
    return words - generic


# --- the arms -------------------------------------------------------------


def bm25_ranking(query: str, documents: list[str]) -> list[int]:
    """Indices of documents, best first, by Okapi BM25."""
    corpus = [tokenise(doc) for doc in documents]
    if not corpus:
        return []
    lengths = [len(doc) for doc in corpus]
    average = sum(lengths) / len(lengths) or 1.0
    total = len(corpus)

    frequencies = [Counter(doc) for doc in corpus]
    containing = Counter()
    for doc in corpus:
        containing.update(set(doc))

    scores = [0.0] * total
    for term in tokenise(query):
        seen = containing.get(term, 0)
        if seen == 0:
            continue
        # The BM25+ idf, which cannot go negative for a term in most documents.
        idf = math.log(1 + (total - seen + 0.5) / (seen + 0.5))
        for i, counts in enumerate(frequencies):
            occurrences = counts.get(term, 0)
            if not occurrences:
                continue
            norm = 1 - BM25_B + BM25_B * (lengths[i] / average)
            scores[i] += idf * (occurrences * (BM25_K1 + 1)) / (occurrences + BM25_K1 * norm)

    ranked = [i for i, score in enumerate(scores) if score > 0]
    ranked.sort(key=lambda i: (-scores[i], i))
    return ranked


def _trigrams(text: str) -> set[str]:
    folded = " ".join(tokenise(text))
    if len(folded) < _TRIGRAM_N:
        return {folded} if folded else set()
    return {folded[i : i + _TRIGRAM_N] for i in range(len(folded) - _TRIGRAM_N + 1)}


def trigram_ranking(query: str, documents: list[str]) -> list[int]:
    """Indices of documents, best first, by character-trigram coverage.

    Coverage of the query rather than symmetric overlap, for the same reason it
    is coverage in semantic/: a fuller product description is not a worse match
    for a short query, and Jaccard would punish it for the extra words.
    """
    wanted = _trigrams(query)
    if not wanted:
        return []
    scores = []
    for i, doc in enumerate(documents):
        coverage = len(wanted & _trigrams(doc)) / len(wanted)
        if coverage >= _TRIGRAM_FLOOR:
            scores.append((i, coverage))
    scores.sort(key=lambda pair: (-pair[1], pair[0]))
    return [i for i, _ in scores]


class DenseRetriever(Protocol):
    def ranking(self, query: str, documents: list[str]) -> list[int]: ...


# --- fusion ---------------------------------------------------------------


@dataclass(frozen=True)
class Hit:
    item: CatalogItem
    score: float
    ranks: dict[str, int]
    # Shares a word with the query that names a product rather than a shelf.
    # An ungrounded hit is the dense arm's paraphrase -- "earbuds" reaching
    # boAt Airdopes 141 -- which is worth surfacing and not worth trusting on
    # its own, so the caller sends those to be confirmed.
    grounded: bool


def fuse(rankings: dict[str, list[int]], count: int) -> list[tuple[int, float, dict[str, int]]]:
    """Reciprocal rank fusion: sum 1 / (k + rank) across the arms that ranked it.

    Positions only. An arm that did not return a document contributes nothing to
    it rather than a zero, so a document found by one arm is not penalised for
    being missed by another.
    """
    scores = [0.0] * count
    places: list[dict[str, int]] = [{} for _ in range(count)]
    for name, ranking in rankings.items():
        for position, index in enumerate(ranking):
            scores[index] += 1.0 / (RRF_K + position + 1)
            places[index][name] = position + 1

    fused = [(i, scores[i], places[i]) for i in range(count) if scores[i] > 0]
    fused.sort(key=lambda row: (-row[1], row[0]))
    return fused


def search(
    query: str,
    items: list[CatalogItem],
    *,
    category_value: str | None = None,
    dense: DenseRetriever | None = None,
) -> list[Hit]:
    """Rank items for a query, or return nothing when the query names none.

    A ranking always has a first element, so ranking alone can never express "we
    do not sell that" -- and that is precisely the answer the merchant owed for
    a MacBook. Two things here can produce nothing: a query that names no
    product at all, and a caller that finds no hit it is willing to act on.

    Grounding, rather than a similarity threshold, is what separates the two
    kinds of hit. A number would need tuning, and a tuned threshold on a model's
    output is how a model ends up deciding. Sharing a distinctive word is not a
    matter of degree.
    """
    if not query or not query.strip() or not items:
        return []

    wanted = distinctive(query, category_value)
    if not wanted:
        # The query named a kind of thing. Retrieval has no opinion, and the
        # caller falls back to offering what it has in that category.
        return []

    documents = [document_for(item) for item in items]
    rankings = {
        "bm25": bm25_ranking(query, documents),
        "trigram": trigram_ranking(query, documents),
    }
    if dense is not None:
        rankings["dense"] = dense.ranking(query, documents)

    return [
        Hit(
            item=items[index],
            score=score,
            ranks=places,
            grounded=bool(wanted & set(tokenise(documents[index]))),
        )
        for index, score, places in fuse(rankings, len(documents))
    ]


def describe(dense: DenseRetriever | None = None) -> dict[str, object]:
    """What actually ran, for the audit trail and for the console to show."""
    return {
        "arms": ["bm25", "trigram"] + (["dense"] if dense is not None else []),
        "fusion": f"reciprocal rank fusion, k={RRF_K}",
        "dense_available": dense is not None,
        "note": (
            "No embedding model is installed, so the dense arm is inert and "
            "retrieval is BM25 fused with character trigrams."
            if dense is None
            else "Dense retrieval is contributing a third ranking."
        ),
    }
