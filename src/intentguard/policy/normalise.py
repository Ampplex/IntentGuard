"""Untrusted merchant strings onto controlled vocabularies.

A merchant writes what it likes. "Open Box", "open-box" and "OPEN BOX" all mean
the same thing and all should match; "gently loved" means something the engine
has no way to rank against the four conditions it knows, so it maps to nothing
and the caller escalates.

Normalising is not the same as guessing. Case and separators are noise. A word
that is not in the vocabulary is not noise, and this module will not stretch to
reach it.
"""

from __future__ import annotations

from ..core.enums import Category, Condition


def _key(raw: str) -> str:
    return raw.strip().lower().replace("-", "_").replace(" ", "_")


def to_condition(raw: str | None) -> Condition | None:
    """The condition, or None if it is not one the engine can judge."""
    if raw is None:
        return None
    try:
        return Condition(_key(raw))
    except ValueError:
        return None


def to_category(raw: str | None) -> Category | None:
    """The taxonomy entry, or None if the merchant used a word outside it."""
    if raw is None:
        return None
    try:
        return Category(_key(raw))
    except ValueError:
        return None
