"""A mandate that contradicts itself, caught before any offer exists."""

from __future__ import annotations

from datetime import timedelta

import pytest

from intentguard.core import (
    Category,
    Condition,
    HardConstraints,
    Outcome,
    ViolationCode,
    from_rupees,
)
from intentguard.policy import check_mandate_feasibility, evaluate
from tests.fixtures import CREATED_AT, a_ledger, an_offer

NOW = CREATED_AT + timedelta(minutes=5)


def mandate_with(**updates):
    ledger = a_ledger()
    hard = HardConstraints.model_validate({**ledger.hard.model_dump(), **updates})
    return ledger.model_copy(update={"hard": hard})


def test_asking_for_a_condition_and_excluding_it_escalates() -> None:
    """The extractor can be entirely certain it read this correctly. It still cannot proceed."""
    ledger = mandate_with(condition=Condition.NEW, exclusions=("new",))
    violations = check_mandate_feasibility(ledger)
    assert [v.code for v in violations] == [ViolationCode.MANDATE_INFEASIBLE]
    assert violations[0].outcome is Outcome.ESCALATE


def test_naming_a_product_and_excluding_it_escalates() -> None:
    ledger = mandate_with(product_ref="Nike Revolution 7", exclusions=("Nike",))
    assert check_mandate_feasibility(ledger)


def test_excluding_the_category_you_asked_for_escalates() -> None:
    ledger = mandate_with(category=Category.FOOTWEAR, exclusions=("footwear",))
    assert check_mandate_feasibility(ledger)


def test_a_ceiling_of_nothing_escalates() -> None:
    assert check_mandate_feasibility(mandate_with(max_total_paise=0))


def test_a_coherent_mandate_raises_nothing() -> None:
    ledger = mandate_with(
        condition=Condition.NEW, exclusions=("leather",), max_total_paise=from_rupees(5000)
    )
    assert check_mandate_feasibility(ledger) == []


def test_no_exclusions_and_a_real_ceiling_skips_the_check_entirely() -> None:
    assert check_mandate_feasibility(a_ledger()) == []


def test_the_engine_escalates_on_an_impossible_mandate() -> None:
    ledger = mandate_with(condition=Condition.NEW, exclusions=("new",))
    result = evaluate(ledger, an_offer(), now=NOW)
    assert result.outcome is Outcome.ESCALATE
    assert ViolationCode.MANDATE_INFEASIBLE in {v.code for v in result.violations}


def test_the_explanation_names_the_contradiction() -> None:
    ledger = mandate_with(product_ref="Nike Revolution 7", exclusions=("Nike",))
    explanation = check_mandate_feasibility(ledger)[0].explanation
    assert "Nike" in explanation
    assert "contradict" in explanation.lower()


@pytest.mark.parametrize("excluded", [("Leather",), ("LEATHER",), (" leather ",)])
def test_exclusion_matching_here_is_case_and_space_insensitive(excluded) -> None:
    ledger = mandate_with(product_ref="Leather boots", exclusions=excluded)
    assert check_mandate_feasibility(ledger)
