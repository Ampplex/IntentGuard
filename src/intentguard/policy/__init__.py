"""The deterministic decision engine.

Imports nothing but core/. No model client, no database, no clock.
"""

from .checks import (
    CHECKS_PERFORMED,
    chargeable_total,
    check_confidence,
    check_exclusions,
    check_mandate_feasibility,
    check_product_identity,
    outcome_for,
)
from .engine import evaluate
from .normalise import to_category, to_condition

__all__ = [
    "CHECKS_PERFORMED",
    "chargeable_total",
    "check_confidence",
    "check_exclusions",
    "check_mandate_feasibility",
    "check_product_identity",
    "evaluate",
    "outcome_for",
    "to_category",
    "to_condition",
]
