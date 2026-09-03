"""The deterministic decision engine.

Imports nothing but core/. No model client, no database, no clock.
"""

from .checks import chargeable_total, outcome_for
from .engine import evaluate
from .normalise import to_category, to_condition

__all__ = ["chargeable_total", "evaluate", "outcome_for", "to_category", "to_condition"]
