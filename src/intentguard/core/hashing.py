"""Canonical hashing.

This is here at stage 1 rather than with the payments adapter because the
idempotency key and the compliance receipt both depend on it, and any audit
record written before canonicalization exists cannot be verified afterwards.

Canonical form is JSON with sorted keys, no insignificant whitespace and no
ASCII escaping, so the same offer hashes identically whatever produced it.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel

HASH_PREFIX = "sha256"


def canonical_json(model: BaseModel) -> str:
    return json.dumps(
        model.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def content_hash(model: BaseModel) -> str:
    digest = hashlib.sha256(canonical_json(model).encode("utf-8")).hexdigest()
    return f"{HASH_PREFIX}:{digest}"


def payload_hash(payload: dict) -> str:
    """Hash a raw wire payload, for offers that never became a model.

    An offer rejected at the boundary still has to be identifiable afterwards.
    "We refused something" is not an audit trail; "we refused this exact
    document, here is its hash" is.
    """
    text = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return f"{HASH_PREFIX}:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def offer_hash(offer: BaseModel) -> str:
    """The offer's identity in the audit trail and half of the idempotency key.

    Hashes the whole offer including raw_description: the untrusted text is part
    of what the merchant put in front of the user, so it is part of the evidence.
    """
    return content_hash(offer)
