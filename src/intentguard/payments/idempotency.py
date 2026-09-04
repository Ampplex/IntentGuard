"""Deriving a stable receipt for one authorization of one offer.

Razorpay documents `receipt` as acting as the idempotency key, capped at 40
ASCII characters. That cap is why this is a hash rather than a readable join:
an intent id and an offer hash concatenated would run well past it.

The key is derived from the intent and the exact offer, so re-executing the same
authorization against the same cart reuses the receipt, and any change to either
produces a different one. That is the property that stops a retry after a
timeout from becoming a second charge.
"""

from __future__ import annotations

import hashlib

RECEIPT_PREFIX = "ig_"
# 40 is Razorpay's documented maximum. Three for the prefix leaves 37; 32 hex
# characters is 128 bits of the digest, which is far more than enough to make a
# collision between two carts a non-event, and leaves headroom under the cap.
DIGEST_CHARS = 32
MAX_RECEIPT_CHARS = 40


def receipt_for(intent_id: str, offer_hash: str) -> str:
    """A stable, ASCII-safe receipt for this authorization of this cart."""
    digest = hashlib.sha256(f"{intent_id}|{offer_hash}".encode()).hexdigest()
    receipt = f"{RECEIPT_PREFIX}{digest[:DIGEST_CHARS]}"
    assert len(receipt) <= MAX_RECEIPT_CHARS, "receipt exceeds Razorpay's documented cap"
    return receipt
