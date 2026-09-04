"""The model-backed extractor, exercised without a network.

The client is injected, so the request shape and the agreement logic are both
testable offline. What cannot be tested here is whether a real model returns
good fields; that needs a key and is stated as untested rather than implied.
"""

from __future__ import annotations

from intentguard.ledger import ExtractedIntent
from intentguard.ledger.claude_extractor import MODEL, SYSTEM_PROMPT, ClaudeExtractor


class StubMessages:
    def __init__(self, replies: list[ExtractedIntent]) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies[min(len(self.calls) - 1, len(self.replies) - 1)]
        return type("Response", (), {"parsed_output": reply})()


class StubClient:
    def __init__(self, replies: list[ExtractedIntent]) -> None:
        self.messages = StubMessages(replies)


def intent(**kwargs) -> ExtractedIntent:
    return ExtractedIntent(**{"category": "footwear", "max_total_text": "5000", **kwargs})


def test_the_request_asks_for_the_schema_and_names_the_current_model() -> None:
    client = StubClient([intent()])
    ClaudeExtractor(client, samples_when_doubtful=1).extract("Buy shoes under 5000.")
    call = client.messages.calls[0]
    assert call["model"] == MODEL
    assert call["output_config"]["format"] is ExtractedIntent
    assert call["messages"] == [{"role": "user", "content": "Buy shoes under 5000."}]


def test_the_system_prompt_forbids_judgement_and_arithmetic() -> None:
    lowered = SYSTEM_PROMPT.lower()
    assert "never decide" in lowered
    assert "never compute" in lowered
    assert "reader, not a judge" in lowered


def test_a_confident_extraction_is_taken_at_one_call() -> None:
    """Sampling three times for every instruction would treble cost and latency."""
    client = StubClient([intent()])
    ClaudeExtractor(client, samples_when_doubtful=3).extract("Buy shoes under 5000.")
    assert len(client.messages.calls) == 1


def test_a_doubtful_extraction_is_sampled_again() -> None:
    client = StubClient([intent(max_total_text=None)])
    ClaudeExtractor(client, samples_when_doubtful=3).extract("Buy me something nice.")
    assert len(client.messages.calls) == 3


def test_agreement_keeps_a_field_the_samples_agree_on() -> None:
    samples = [intent(quantity=2), intent(quantity=2), intent(quantity=9)]
    assert ClaudeExtractor._agreed(samples).quantity == 2


def test_disagreement_drops_a_field_rather_than_voting_it_through() -> None:
    """A field the model cannot reproduce is one the instruction did not contain.

    Dropping it to null drives an escalation, which is the safe outcome. A
    plurality vote would produce a confident wrong answer instead.
    """
    samples = [intent(quantity=1), intent(quantity=2), intent(quantity=3)]
    assert ClaudeExtractor._agreed(samples).quantity is None


def test_agreement_unions_the_vague_phrases() -> None:
    """Any sample noticing imprecision is worth keeping; missing it is the risk."""
    samples = [intent(vague_phrases=["decent"]), intent(vague_phrases=["cheap"]), intent()]
    assert set(ClaudeExtractor._agreed(samples).vague_phrases) == {"decent", "cheap"}


def test_agreement_never_invents_a_permission() -> None:
    samples = [intent(recurring_allowed=True), intent(), intent()]
    agreed = ClaudeExtractor._agreed(samples)
    assert agreed.recurring_allowed is False


def test_agreement_returns_a_valid_extraction() -> None:
    samples = [intent(exclusions=["leather"]), intent(exclusions=["leather"]), intent()]
    agreed = ClaudeExtractor._agreed(samples)
    assert isinstance(agreed, ExtractedIntent)
    assert agreed.exclusions == ["leather"]
    assert agreed.quantity_mode == "exact"
