"""Engine semantics: report everything, decide deterministically, stay pure."""

from __future__ import annotations

from datetime import timedelta

import pytest

from intentguard.core import (
    EmiTerms,
    LineItem,
    LineItemKind,
    Outcome,
    ViolationCode,
    from_rupees,
)
from intentguard.policy import evaluate
from tests.fixtures import CREATED_AT, a_ledger, a_trial_recurrence, an_offer

NOW = CREATED_AT + timedelta(minutes=5)

# Codes the deterministic engine cannot produce, and who owns each. Asserted so
# that "a test per violation code" cannot be satisfied by quietly narrowing the
# engine's remit.
# PRODUCT_SUBSTITUTION left this list at Amendment 3. Blocking on it is an exact
# comparison against a pinned product_ref with no model in it. The similarity
# half of substitution stays with semantic/ and escalates rather than blocks.
NOT_POLICYS_TO_RAISE = {
    ViolationCode.LOW_CONFIDENCE: "ledger/ at stage 4",
    ViolationCode.UNMODELLED_FIELD: "gate/, translated from a parse failure",
    ViolationCode.OFFER_MALFORMED: "gate/, translated from a parse failure",
}


def codes(result) -> set[ViolationCode]:
    return {violation.code for violation in result.violations}


def test_every_violation_is_reported_not_just_the_first() -> None:
    """An offer that breaks budget and adds a subscription says both."""
    offer = an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(9000), kind=LineItemKind.PRODUCT)
        ],
        total_paise=from_rupees(9000),
        recurring=[a_trial_recurrence()],
        emi=EmiTerms(installment_paise=from_rupees(1000), installment_count=9),
        currency="USD",
    )
    result = evaluate(a_ledger(), offer, now=NOW)
    assert {
        ViolationCode.TOTAL_EXCEEDS_MAX,
        ViolationCode.RECURRING_NOT_AUTHORIZED,
        ViolationCode.EMI_NOT_AUTHORIZED,
        ViolationCode.CURRENCY_MISMATCH,
    } <= codes(result)


def test_a_definite_block_outranks_an_escalation() -> None:
    offer = an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(9000), kind=LineItemKind.PRODUCT)
        ],
        total_paise=from_rupees(9000),
    )
    product = offer.product.model_copy(update={"condition": "gently loved"})
    result = evaluate(a_ledger(), offer.model_copy(update={"product": product}), now=NOW)
    assert ViolationCode.UNCLASSIFIABLE_CONDITION in codes(result)
    assert result.outcome is Outcome.BLOCK


def test_the_same_inputs_always_give_the_same_answer() -> None:
    ledger, offer = a_ledger(), an_offer(total_paise=from_rupees(4000))
    first = evaluate(ledger, offer, now=NOW)
    second = evaluate(ledger, offer, now=NOW)
    assert first == second


def test_the_clock_is_an_argument_not_an_ambient_fact() -> None:
    ledger = a_ledger()
    fresh = evaluate(ledger, an_offer(), now=CREATED_AT + timedelta(seconds=10))
    stale = evaluate(ledger, an_offer(), now=CREATED_AT + timedelta(days=1))
    assert fresh.outcome is Outcome.ALLOW
    assert stale.outcome is Outcome.BLOCK


def test_every_violation_explains_itself_to_a_person() -> None:
    offer = an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(9000), kind=LineItemKind.PRODUCT)
        ],
        total_paise=from_rupees(9000),
        recurring=[a_trial_recurrence()],
    )
    result = evaluate(a_ledger(), offer, now=NOW)
    assert result.violations
    for violation in result.violations:
        assert violation.explanation
        assert "{" not in violation.explanation, violation.code
        assert violation.explanation[0].isupper()


def test_the_ceiling_explanation_names_real_money() -> None:
    offer = an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(9000), kind=LineItemKind.PRODUCT)
        ],
        total_paise=from_rupees(9000),
    )
    result = evaluate(a_ledger(), offer, now=NOW)
    ceiling = next(v for v in result.violations if v.code is ViolationCode.TOTAL_EXCEEDS_MAX)
    assert "₹9,000.00" in ceiling.explanation
    assert "₹5,000.00" in ceiling.explanation


@pytest.mark.parametrize("code", sorted(NOT_POLICYS_TO_RAISE), ids=lambda c: c.value)
def test_policy_does_not_claim_codes_it_cannot_decide(code: ViolationCode) -> None:
    """These need a model, an embedding or a parser. None belong in the engine."""
    import inspect

    import intentguard.policy as policy_pkg

    sources = [
        inspect.getsource(module)
        for module in vars(policy_pkg).values()
        if inspect.ismodule(module) and module.__name__.startswith("intentguard.policy")
    ]
    sources.append(inspect.getsource(policy_pkg))
    assert not any(code.name in source for source in sources), NOT_POLICYS_TO_RAISE[code]


def test_an_allow_carries_the_total_that_was_checked() -> None:
    result = evaluate(a_ledger(), an_offer(), now=NOW)
    assert result.outcome is Outcome.ALLOW
    assert result.checked_total_paise == from_rupees(4200)
