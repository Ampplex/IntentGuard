"""The buyer agent and the negotiation loop.

The buyer acts for the user, so unlike the merchant it is trusted with the
ceiling. That trust creates the leak this module is shaped around: a buyer that
accepts instantly at exactly the ceiling tells a merchant where the ceiling is,
and a merchant that learns it quotes there every time afterwards.

The mitigation is that the buyer negotiates toward a target strictly below the
ceiling and never opens at the ceiling. It will still accept an offer inside the
ceiling rather than lose the order, but only after trying for the target, so the
signal a merchant could read is blurred rather than handed over. This is a
mitigation and not a solution, and the README says so.

**Termination.** The loop is a bounded `for` over a fixed number of rounds. It
is not a `while` with an exit condition, because a `while` is a promise and a
bounded `for` is a proof: there is no merchant behaviour, adversarial or
otherwise, that can make it run longer than `max_rounds` iterations. Stall
detection ends it earlier when the merchant stops conceding meaningfully, but
nothing depends on stall detection working for the loop to end.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from ..core.base import StrictModel
from ..core.intent import IntentLedger
from ..merchant.agent import MerchantAgent
from ..merchant.projection import MerchantView, project

# The buyer opens by asking for this fraction of the ceiling, in basis points so
# the arithmetic stays integer. Nine thousand is ninety percent.
DEFAULT_TARGET_BPS = 9_000
BPS = 10_000

# A concession smaller than this is the merchant running down the clock rather
# than negotiating, so the buyer stops asking.
DEFAULT_MIN_CONCESSION_PAISE = 100

DEFAULT_MAX_ROUNDS = 6


class Ending(StrEnum):
    ACCEPTED_AT_TARGET = "accepted_at_target"
    ACCEPTED_WITHIN_CEILING = "accepted_within_ceiling"
    STALLED = "stalled"
    ROUNDS_EXHAUSTED = "rounds_exhausted"
    NOTHING_ON_OFFER = "nothing_on_offer"


class Round(StrictModel):
    """One exchange, kept for the audit trail and the demo."""

    number: int = Field(ge=1)
    quoted_total_paise: int
    asked_for_paise: int | None = None
    note: str


class Negotiation(StrictModel):
    ending: Ending
    rounds: list[Round] = Field(default_factory=list)
    final_payload: dict | None = None
    target_paise: int
    accepted: bool = False

    @property
    def exchanges(self) -> int:
        """How many times the merchant was actually asked for a better price.

        Distinct from len(rounds), which also holds the final quote the buyer
        settled on. The termination guarantee is about exchanges: the log may
        carry one more entry than that, and it is a record rather than a round
        trip.
        """
        return sum(1 for entry in self.rounds if entry.asked_for_paise is not None)


def target_for(ceiling_paise: int, target_bps: int = DEFAULT_TARGET_BPS) -> int:
    """The figure the buyer aims at. Integer arithmetic, no floats in the money path."""
    return ceiling_paise * target_bps // BPS


class BuyerAgent:
    """Negotiates on the user's behalf, within a mandate it is trusted to see."""

    def __init__(
        self,
        ledger: IntentLedger,
        *,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        target_bps: int = DEFAULT_TARGET_BPS,
        min_concession_paise: int = DEFAULT_MIN_CONCESSION_PAISE,
    ) -> None:
        if max_rounds < 1:
            raise ValueError("a negotiation needs at least one round")
        self.ledger = ledger
        self.max_rounds = max_rounds
        self.target_paise = target_for(ledger.hard.max_total_paise, target_bps)
        self.min_concession_paise = min_concession_paise

    @property
    def view(self) -> MerchantView:
        """What the buyer is willing to tell the merchant. Never the ceiling."""
        return project(self.ledger)

    def negotiate(self, merchant: MerchantAgent) -> Negotiation:
        """Trade offers until one is good enough, or until the rounds run out."""
        view = self.view
        payload = merchant.quote(view)
        if payload is None:
            return Negotiation(ending=Ending.NOTHING_ON_OFFER, target_paise=self.target_paise)

        rounds: list[Round] = []
        ceiling = self.ledger.hard.max_total_paise

        # Bounded on purpose. Nothing the merchant returns can extend this.
        for number in range(1, self.max_rounds + 1):
            quoted = payload["total_paise"]

            if quoted <= self.target_paise:
                rounds.append(
                    Round(number=number, quoted_total_paise=quoted, note="at or under target")
                )
                return Negotiation(
                    ending=Ending.ACCEPTED_AT_TARGET,
                    rounds=rounds,
                    final_payload=payload,
                    target_paise=self.target_paise,
                    accepted=True,
                )

            rounds.append(
                Round(
                    number=number,
                    quoted_total_paise=quoted,
                    asked_for_paise=self.target_paise,
                    note="countered",
                )
            )
            revised = merchant.counter(view, payload, self.target_paise)
            conceded = quoted - revised["total_paise"]

            if conceded < self.min_concession_paise:
                # Not moving, or moving backwards. Take it if it fits, else stop.
                return self._settle(Ending.STALLED, rounds, payload, ceiling)
            payload = revised

        return self._settle(Ending.ROUNDS_EXHAUSTED, rounds, payload, ceiling)

    def _settle(
        self, ending: Ending, rounds: list[Round], payload: dict, ceiling: int
    ) -> Negotiation:
        """Nothing better is coming. Accept it if it is inside the mandate.

        Accepting here rather than walking away is the point of the whole system:
        a guard that refuses every order it did not get a discount on is a guard
        that costs the merchant revenue. Whether the offer really satisfies the
        mandate is not decided here -- the buyer is untrusted too, and the gate
        judges it afterwards.
        """
        # The last concession arrives after the final round's counter, so without
        # this the log ends one quote before the one actually accepted, and the
        # audit trail would not contain the figure the decision was made on.
        rounds = [
            *rounds,
            Round(
                number=len(rounds) + 1,
                quoted_total_paise=payload["total_paise"],
                note="final offer",
            ),
        ]
        within = payload["total_paise"] <= ceiling
        return Negotiation(
            ending=Ending.ACCEPTED_WITHIN_CEILING if within else ending,
            rounds=rounds,
            final_payload=payload,
            target_paise=self.target_paise,
            accepted=within,
        )
