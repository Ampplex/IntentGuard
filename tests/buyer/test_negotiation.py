"""The stage 6 gate: negotiation terminates, always.

The strong form of that claim is structural. The loop is a bounded `for`, so
there is no merchant behaviour that can extend it, and the AST test in
tests/structure asserts no unbounded loop exists in the package. These tests
attack it behaviourally as well: a merchant that never concedes, one that
concedes a single paisa, one that oscillates without converging, and one that
raises its price every round.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from intentguard.buyer import BuyerAgent, Ending, target_for
from intentguard.core import HardConstraints, Offer, Outcome, from_rupees
from intentguard.gate import receive
from intentguard.merchant import Concession, Hostility, MerchantAgent
from tests.fixtures import CREATED_AT, a_ledger

NOW = CREATED_AT + timedelta(minutes=5)


def mandate(rupees: int = 5000):
    ledger = a_ledger()
    hard = HardConstraints.model_validate(
        {**ledger.hard.model_dump(), "max_total_paise": from_rupees(rupees)}
    )
    return ledger.model_copy(update={"hard": hard})


class NeverTerminatingMerchant(MerchantAgent):
    """Concedes one paisa forever. The classic way a loop fails to end."""

    def counter(self, view, previous, target_paise):
        revised = dict(previous)
        revised["line_items"] = [dict(i) for i in previous["line_items"]]
        revised["line_items"][0]["amount_paise"] -= 1
        revised["total_paise"] = sum(i["amount_paise"] for i in revised["line_items"])
        return revised


class EscalatingMerchant(MerchantAgent):
    """Raises the price every round, which is a negative concession."""

    def counter(self, view, previous, target_paise):
        revised = dict(previous)
        revised["line_items"] = [dict(i) for i in previous["line_items"]]
        revised["line_items"][0]["amount_paise"] += from_rupees(500)
        revised["total_paise"] = sum(i["amount_paise"] for i in revised["line_items"])
        return revised


# --- termination ----------------------------------------------------------


@pytest.mark.parametrize(
    "merchant",
    [
        MerchantAgent(concession=Concession.MEET),
        MerchantAgent(concession=Concession.HAGGLE),
        MerchantAgent(concession=Concession.STUBBORN),
        MerchantAgent(concession=Concession.OSCILLATING),
        NeverTerminatingMerchant(),
        EscalatingMerchant(),
    ],
    ids=["meet", "haggle", "stubborn", "oscillating", "one_paisa_forever", "escalating"],
)
def test_negotiation_ends_against_every_merchant(merchant) -> None:
    result = BuyerAgent(mandate()).negotiate(merchant)
    assert result.ending in set(Ending)
    assert result.exchanges <= BuyerAgent(mandate()).max_rounds


@pytest.mark.parametrize("max_rounds", [1, 2, 3, 10])
def test_the_round_cap_is_never_exceeded(max_rounds: int) -> None:
    buyer = BuyerAgent(mandate(), max_rounds=max_rounds)
    result = buyer.negotiate(NeverTerminatingMerchant())
    assert result.exchanges <= max_rounds
    assert len(result.rounds) <= max_rounds + 1, "at most one record beyond the last exchange"


def test_a_stubborn_merchant_ends_it_early_rather_than_at_the_cap() -> None:
    """Stall detection is an optimisation. The cap is the guarantee.

    Priced so the opening quote of Rs 4,100 sits above the Rs 3,870 target and
    below the Rs 4,300 ceiling. A looser mandate would be accepted on the first
    round and this would pass without ever reaching the stall path.
    """
    result = BuyerAgent(mandate(4300), max_rounds=6).negotiate(
        MerchantAgent(concession=Concession.STUBBORN)
    )
    assert result.exchanges == 1


@settings(max_examples=60, deadline=None)
@given(
    ceiling=st.integers(min_value=1, max_value=10_000_000),
    max_rounds=st.integers(min_value=1, max_value=12),
    target_bps=st.integers(min_value=1, max_value=10_000),
    concession=st.sampled_from(list(Concession)),
    hostility=st.sampled_from(list(Hostility)),
)
def test_it_always_terminates(ceiling, max_rounds, target_bps, concession, hostility) -> None:
    """Every combination of mandate and merchant behaviour, still bounded."""
    buyer = BuyerAgent(mandate(), max_rounds=max_rounds, target_bps=target_bps)
    buyer.target_paise = target_for(ceiling, target_bps)
    result = buyer.negotiate(MerchantAgent(hostility, concession))
    assert result.exchanges <= max_rounds


def test_a_negotiation_needs_at_least_one_round() -> None:
    with pytest.raises(ValueError, match="at least one round"):
        BuyerAgent(mandate(), max_rounds=0)


# --- the ceiling leak -----------------------------------------------------


def test_the_buyer_aims_below_the_ceiling() -> None:
    """The mitigation for a real leak: accepting at the ceiling reveals it."""
    buyer = BuyerAgent(mandate(5000))
    assert buyer.target_paise == from_rupees(4500)
    assert buyer.target_paise < buyer.ledger.hard.max_total_paise


def test_the_target_is_integer_paise() -> None:
    value = target_for(from_rupees(3333), 9_000)
    assert isinstance(value, int) and not isinstance(value, bool)


def test_the_merchant_is_never_told_the_ceiling_during_negotiation() -> None:
    """What crosses the wire in a counter is a target, not a limit."""
    buyer = BuyerAgent(mandate(5000))
    serialised = buyer.view.model_dump_json()
    assert "500000" not in serialised
    assert str(buyer.target_paise) not in serialised


# --- outcomes -------------------------------------------------------------


def test_a_generous_merchant_is_accepted_at_the_target() -> None:
    result = BuyerAgent(mandate()).negotiate(MerchantAgent(concession=Concession.MEET))
    assert result.ending is Ending.ACCEPTED_AT_TARGET
    assert result.accepted
    assert result.final_payload["total_paise"] <= result.target_paise


def test_an_offer_inside_the_ceiling_is_taken_rather_than_lost() -> None:
    """A guard that refuses every order it did not discount costs the merchant revenue."""
    result = BuyerAgent(mandate(4300)).negotiate(MerchantAgent(concession=Concession.STUBBORN))
    assert result.accepted
    assert result.ending is Ending.ACCEPTED_WITHIN_CEILING
    assert from_rupees(3870) < result.final_payload["total_paise"] <= from_rupees(4300)


def test_an_offer_over_the_ceiling_is_not_accepted() -> None:
    result = BuyerAgent(mandate(1000)).negotiate(MerchantAgent(concession=Concession.STUBBORN))
    assert not result.accepted
    assert result.final_payload["total_paise"] > from_rupees(1000)


def test_nothing_in_the_catalog_is_reported_rather_than_crashing() -> None:
    ledger = mandate()
    hard = HardConstraints.model_validate({**ledger.hard.model_dump(), "product_ref": None})
    from intentguard.core import Category

    hard = HardConstraints.model_validate(
        {**hard.model_dump(), "category": Category.GROCERY, "condition": "refurbished"}
    )
    result = BuyerAgent(ledger.model_copy(update={"hard": hard})).negotiate(MerchantAgent())
    assert result.ending is Ending.NOTHING_ON_OFFER
    assert result.final_payload is None


# --- the buyer is not trusted either --------------------------------------


def test_what_the_buyer_accepts_is_still_judged_by_the_gate() -> None:
    """The gate trusts nobody, the user's own agent included."""
    ledger = mandate(5000)
    result = BuyerAgent(ledger).negotiate(MerchantAgent(Hostility.TRIAL_SUBSCRIPTION))
    assert result.accepted, "the buyer sees a price it likes"
    decision, _ = receive(ledger, result.final_payload, now=NOW)
    assert decision.decision is Outcome.BLOCK, "and the gate blocks it anyway"


def test_an_accepted_negotiation_produces_a_parseable_offer() -> None:
    result = BuyerAgent(mandate()).negotiate(MerchantAgent(concession=Concession.HAGGLE))
    assert result.final_payload is not None
    Offer.model_validate(result.final_payload)


def test_the_round_log_records_what_was_asked_for() -> None:
    result = BuyerAgent(mandate()).negotiate(MerchantAgent(concession=Concession.HAGGLE))
    assert result.rounds
    assert result.rounds[0].quoted_total_paise > 0
    countered = [r for r in result.rounds if r.asked_for_paise is not None]
    assert all(r.asked_for_paise == result.target_paise for r in countered)


def test_the_log_ends_on_the_quote_that_was_actually_accepted() -> None:
    """The last concession arrives after the final counter.

    Without recording it the log ends one quote before the figure the decision
    was made on, and the audit trail would not contain the number that mattered.
    """
    result = BuyerAgent(mandate()).negotiate(MerchantAgent(concession=Concession.HAGGLE))
    assert result.rounds[-1].quoted_total_paise == result.final_payload["total_paise"]


# --- the merchant is untrusted here too -----------------------------------
# Everything the buyer reads from a quote was written by the other side. These
# were all crashes: a missing, null or non-numeric total ended the negotiation
# with an exception, which is a denial of service against the user's own agent
# rather than a negotiating position.


class MalformedMerchant(MerchantAgent):
    """Sends whatever it likes, whenever it likes."""

    def __init__(self, payload: dict, *, only_on_counter: bool = False) -> None:
        super().__init__()
        self._payload = payload
        self._only_on_counter = only_on_counter

    def quote(self, view):
        return super().quote(view) if self._only_on_counter else self._payload

    def counter(self, view, previous, target_paise):
        return self._payload


BAD_PAYLOADS = {
    "no total": {"offer_id": "x", "line_items": [{"amount_paise": 100}]},
    "total is text": {"offer_id": "x", "total_paise": "cheap", "line_items": [{"a": 1}]},
    "total is null": {"offer_id": "x", "total_paise": None, "line_items": [{"a": 1}]},
    "total is a bool": {"offer_id": "x", "total_paise": True, "line_items": [{"a": 1}]},
    "no line items": {"offer_id": "x", "total_paise": 100},
    "empty line items": {"offer_id": "x", "total_paise": 100, "line_items": []},
    "not a dict at all": {"offer_id": "x"},
}


@pytest.mark.parametrize("payload", BAD_PAYLOADS.values(), ids=list(BAD_PAYLOADS))
def test_a_malformed_opening_quote_ends_the_negotiation_rather_than_the_process(payload) -> None:
    result = BuyerAgent(mandate()).negotiate(MalformedMerchant(payload))
    assert result.ending is Ending.UNUSABLE_QUOTE
    assert not result.accepted


@pytest.mark.parametrize("payload", BAD_PAYLOADS.values(), ids=list(BAD_PAYLOADS))
def test_a_malformed_counter_falls_back_to_the_last_readable_quote(payload) -> None:
    """A counter nobody can read is not a concession, and not a reason to crash."""
    result = BuyerAgent(mandate(4300)).negotiate(MalformedMerchant(payload, only_on_counter=True))
    assert result.ending in {Ending.ACCEPTED_WITHIN_CEILING, Ending.STALLED}
    assert result.final_payload["total_paise"] == from_rupees(4100)


def test_an_unreadable_quote_is_still_handed_to_the_gate() -> None:
    """The buyer cannot reason about it. It is not entitled to refuse it either."""
    payload = BAD_PAYLOADS["total is text"]
    result = BuyerAgent(mandate()).negotiate(MalformedMerchant(payload))
    assert result.final_payload == payload, "pydantic copies it; the content is what matters"
    decision, _ = receive(mandate(), result.final_payload, now=NOW)
    assert decision.decision is Outcome.BLOCK


def test_an_empty_quote_is_not_silently_accepted() -> None:
    """This one was worse than a crash: a payload with no items reached accepted."""
    result = BuyerAgent(mandate()).negotiate(MalformedMerchant(BAD_PAYLOADS["empty line items"]))
    assert not result.accepted


# --- configuration footguns ----------------------------------------------


@pytest.mark.parametrize("bps", [10_001, 20_000, 0, -1])
def test_a_target_at_or_above_the_ceiling_is_refused(bps: int) -> None:
    """Aiming above the ceiling defeats the reason a target exists."""
    with pytest.raises(ValueError, match="target_bps"):
        BuyerAgent(mandate(), target_bps=bps)


def test_the_target_stays_under_the_ceiling_across_the_whole_valid_range() -> None:
    ceiling = from_rupees(5000)
    for bps in (1, 5_000, 9_000, 9_999, 10_000):
        assert target_for(ceiling, bps) <= ceiling
