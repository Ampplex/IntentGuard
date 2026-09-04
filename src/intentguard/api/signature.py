"""Verifying that a payment really came from Razorpay.

After the browser modal closes, the page hands the server three values it
received from Razorpay's own script. Nothing about that hand-off is trustworthy
on its own: the page is a browser, and a browser is an untrusted party in
exactly the sense the rest of this project uses the word.

The signature is what makes it trustworthy. Razorpay computes
HMAC-SHA256(order_id + "|" + payment_id) with the key secret, which only the
merchant server holds. Recomputing it and finding a match proves the values came
from Razorpay and were not assembled by whoever opened the page.

Compared with hmac.compare_digest rather than ==, so the comparison takes the
same time whatever the input. A plain equality check leaks how much of a forged
signature was right, one byte at a time.
"""

from __future__ import annotations

import hashlib
import hmac

SEPARATOR = "|"


def expected_signature(order_id: str, payment_id: str, key_secret: str) -> str:
    """The signature Razorpay would have produced for this pair."""
    body = f"{order_id}{SEPARATOR}{payment_id}".encode()
    return hmac.new(key_secret.encode(), body, hashlib.sha256).hexdigest()


def signature_matches(order_id: str, payment_id: str, signature: str, key_secret: str) -> bool:
    """Did Razorpay sign this payment for this order?"""
    if not (order_id and payment_id and signature):
        return False
    return hmac.compare_digest(expected_signature(order_id, payment_id, key_secret), signature)
