"""Shared model configuration.

Two settings, both load-bearing.

``extra="forbid"`` is how unmodelled offer fields get detected. A merchant that
sends a key IntentGuard has no slot for produces a validation error rather than
being silently ignored. The gate translates that error into UNMODELLED_FIELD and
escalates -- see the note in decision.py.

``frozen=True`` matters because an Offer's hash is its identity in the audit
trail. A record that can be mutated after hashing is not evidence.
"""

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
