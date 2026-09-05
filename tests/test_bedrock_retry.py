"""Backing off when Bedrock says "later", and not when it says "no".

Throttling was not hypothetical: warming the catalog fires fifteen embedding
calls at once, and the API tests failed on ThrottlingException with a different
test failing each run.
"""

from __future__ import annotations

import pytest

from intentguard.bedrock import is_retryable, with_retry


class Throttles:
    """Fails with a throttle a fixed number of times, then succeeds."""

    def __init__(self, failures: int) -> None:
        self.remaining = failures
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise RuntimeError("ThrottlingException: Too many requests, please wait")
        return "ok"


def test_a_throttled_call_is_retried_until_it_succeeds() -> None:
    work = Throttles(3)
    assert with_retry(work) == "ok"
    assert work.calls == 4


def test_the_last_attempt_raises_rather_than_returning_nothing() -> None:
    """An outage has to keep looking like an outage."""
    work = Throttles(99)
    with pytest.raises(RuntimeError, match="Throttling"):
        with_retry(work, attempts=3)
    assert work.calls == 3


def test_an_error_that_will_not_change_is_raised_immediately() -> None:
    calls = []

    def work():
        calls.append(1)
        raise ValueError("ValidationException: the schema is malformed")

    with pytest.raises(ValueError):
        with_retry(work)
    assert len(calls) == 1, "a permanent failure retried is the same failure five times"


@pytest.mark.parametrize(
    "message",
    [
        "ThrottlingException: Too many requests",
        "TooManyRequestsException",
        "ServiceUnavailableException",
        "ModelTimeoutException",
        "SlowDown",
    ],
)
def test_transient_failures_are_recognised(message: str) -> None:
    assert is_retryable(RuntimeError(message))


@pytest.mark.parametrize(
    "message",
    [
        "ValidationException: bad schema",
        "AccessDeniedException",
        "ResourceNotFoundException: no such model",
        "UnrecognizedClientException: invalid key",
    ],
)
def test_permanent_failures_are_not_retried(message: str) -> None:
    assert not is_retryable(RuntimeError(message))


def test_the_delay_is_jittered_rather_than_fixed(monkeypatch) -> None:
    """Fixed backoff turns one burst into the next one.

    Fifteen embedding calls throttled together and slept for an identical delay
    would wake together and throttle again. The delay is drawn from a range for
    that reason, so the assertion is that a range is what is drawn from.
    """
    drawn: list[tuple[float, float]] = []
    monkeypatch.setattr("intentguard.bedrock.time.sleep", lambda _: None)
    monkeypatch.setattr(
        "intentguard.bedrock.random.uniform",
        lambda low, high: drawn.append((low, high)) or 0.0,
    )
    with pytest.raises(RuntimeError):
        with_retry(Throttles(99), attempts=4)

    assert [low for low, _ in drawn] == [0.0, 0.0, 0.0], "full jitter draws from zero"
    ceilings = [high for _, high in drawn]
    assert ceilings == sorted(ceilings) and ceilings[0] < ceilings[-1], "the ceiling grows"
