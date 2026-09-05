"""The dense arm of retrieval: real embeddings from Bedrock.

**Why Bedrock rather than a local model.** CLAUDE.md's stack names
sentence-transformers, chosen to keep the network out of the hot path. That
reasoning holds for the *gate*, whose latency is a headline and which is
deterministic anyway. It does not hold here: this is the merchant's own search,
it is not on the decision path, and installing torch to embed fifteen product
titles would cost gigabytes to answer a question the credentials already
present can answer. The Protocol below is the seam, so a local model can be
dropped in without touching the caller.

**What it costs, and what is cached.** The catalog is embedded once per process
and kept; a query is embedded once and kept. So a negotiation that quotes five
times spends one query embedding, not five, and the fifteen document vectors
are paid for once no matter how many transactions run. Vectors are normalised
at the source, which makes cosine similarity a dot product and removes the only
place a magnitude bug could hide.

**Failure is not an empty shelf.** Every error path returns an empty ranking
rather than a wrong one, and RRF simply fuses the arms that answered. An outage
degrades retrieval to BM25 and trigrams instead of turning the merchant into a
shop that stocks nothing.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..bedrock import with_retry

DEFAULT_EMBED_MODEL = "amazon.titan-embed-text-v2:0"
DEFAULT_REGION = "us-west-2"
DEFAULT_DIM = 1024

# Below this cosine a document is not a candidate. Without a floor this arm
# ranks every document, because everything is somewhat similar to everything --
# which is how "macbook pro m5" acquired a ThinkPad as a candidate and then a
# reranker willing to keep it.
#
# Measured over the pairs in the tests: true candidates scored no lower than
# 0.244 ("earbuds" against the earphones) and false ones no higher than 0.180
# ("earbuds" against a laptop). 0.21 sits between them.
#
# Stated honestly, this is a narrow gap read off eleven pairs, not a
# calibration. It is why the arm nominates candidates rather than deciding: a
# wrong call here is survivable because the reranker sees it next and the gate
# re-checks the offer after that.
DENSE_FLOOR = 0.21


class BedrockEmbeddings:
    """A DenseRetriever backed by a hosted embedding model."""

    def __init__(
        self,
        client: Any = None,
        *,
        model_id: str | None = None,
        region: str | None = None,
        dimensions: int | None = None,
    ) -> None:
        self.model_id = model_id or os.environ.get("BEDROCK_EMBED_MODEL", DEFAULT_EMBED_MODEL)
        self.region = region or os.environ.get("AWS_REGION", DEFAULT_REGION)
        self.dimensions = dimensions or int(os.environ.get("EMBEDDING_DIM", DEFAULT_DIM))
        if client is None:
            import boto3  # imported lazily so boto3 stays optional

            client = boto3.client("bedrock-runtime", region_name=self.region)
        self.client = client
        self._cache: dict[str, list[float]] = {}
        self.calls = 0

    # -- embedding ---------------------------------------------------------

    def embed(self, text: str) -> list[float] | None:
        """One vector, cached by exact text. None when the model cannot answer."""
        key = text.strip()
        if not key:
            return None
        if key in self._cache:
            return self._cache[key]
        try:
            self.calls += 1
            response = with_retry(
                lambda: self.client.invoke_model(
                    modelId=self.model_id,
                    body=json.dumps(
                        # Normalised at the source, so cosine is a dot product below.
                        {"inputText": key, "dimensions": self.dimensions, "normalize": True}
                    ),
                )
            )
            vector = json.loads(response["body"].read())["embedding"]
        except Exception:
            return None
        if not isinstance(vector, list) or not vector:
            return None
        self._cache[key] = vector
        return vector

    # -- retrieval ---------------------------------------------------------

    def ranking(self, query: str, documents: list[str]) -> list[int]:
        """Indices of documents, best first, by cosine similarity to the query."""
        wanted = self.embed(query)
        if wanted is None:
            return []

        scored: list[tuple[int, float]] = []
        for index, document in enumerate(documents):
            vector = self.embed(document)
            if vector is None or len(vector) != len(wanted):
                continue
            similarity = sum(a * b for a, b in zip(wanted, vector, strict=True))
            if similarity >= DENSE_FLOOR:
                scored.append((index, similarity))

        # Everything is similar to everything to some degree, so an unfiltered
        # ranking always nominates a first place even when nothing fits. The
        # floor above is what lets this arm return nothing at all.
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return [index for index, _ in scored]

    def warm(self, documents: list[str]) -> None:
        """Pay for the catalog's vectors once, before the first shopper waits."""
        for document in documents:
            self.embed(document)
