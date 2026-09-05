"""Talking to Bedrock without assuming every model accepts the same request.

The extractor and the reranker both need one thing from a model: an answer in a
schema, not prose. Bedrock spells that `toolChoice`, and models disagree about
which spellings they accept -- `mistral.mistral-large-2407-v1:0` rejects
`{"tool": {"name": ...}}` outright with a ValidationException, while accepting
`{"any": {}}`, which for a single-tool request means the same thing.

Discovering that per call would spend a failed request every time. Discovering
it per model, once, and remembering it costs one failure for the life of the
process.

The order below is deliberate. `tool` and `any` both *require* a tool call, so
the schema is still a guarantee; `auto` merely permits one, so it is last and a
caller that lands there has to cope with prose. That difference is why this is a
negotiation over spellings rather than a fallback to whatever works.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")

# Bedrock throttles per account, and a warm-up that embeds a whole catalog is
# exactly the burst that trips it. These were not chosen to be generous: five
# attempts with the delays below spans roughly eight seconds in the worst case,
# which is under a request timeout and long enough for a per-minute bucket to
# refill.
RETRY_ATTEMPTS = 5
RETRY_BASE_SECONDS = 0.4
RETRY_CAP_SECONDS = 8.0

# Retried because the same request may succeed later. Anything else -- bad
# credentials, a malformed schema, a model that does not exist -- will fail
# identically five times, so it is raised the first time.
_RETRYABLE = (
    "throttl",
    "toomanyrequests",
    "serviceunavailable",
    "service unavailable",
    "internalserver",
    "internal server",
    "modeltimeout",
    "model timeout",
    "modelnotready",
    "requesttimeout",
    "request timeout",
    "slowdown",
)


def is_retryable(error: BaseException) -> bool:
    text = f"{type(error).__name__} {error}".lower()
    return any(marker in text for marker in _RETRYABLE)


def with_retry(work: Callable[[], T], *, attempts: int = RETRY_ATTEMPTS) -> T:
    """Run `work`, backing off with full jitter when Bedrock says "later".

    Full jitter -- a delay drawn uniformly from [0, cap] rather than the cap
    itself -- because the failure this exists for is a burst. Fixed backoff
    would have every caller in that burst wake at the same moment and produce
    the next burst; a random delay spreads them out. This matters here rather
    than in theory: warming the catalog fires fifteen embedding calls at once.

    The last attempt raises, so an outage still reads as an outage.
    """
    delay = RETRY_BASE_SECONDS
    for attempt in range(attempts):
        try:
            return work()
        except Exception as error:  # noqa: BLE001 - the client's exception types vary
            if attempt == attempts - 1 or not is_retryable(error):
                raise
            time.sleep(random.uniform(0, min(delay, RETRY_CAP_SECONDS)))
            delay *= 2
    raise AssertionError("unreachable")  # pragma: no cover


# Most specific first. Every entry but the last compels a tool call.
_CHOICES: tuple[dict[str, Any] | None, ...] = (None, {"any": {}}, {"auto": {}})

# model id -> the index in _CHOICES that this model accepted.
_ACCEPTED: dict[str, int] = {}


def converse_with_tool(
    client: Any,
    *,
    model_id: str,
    system: str,
    messages: list[dict[str, Any]],
    tool_spec: dict[str, Any],
    max_tokens: int,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """One Converse call that insists on a tool call, in whichever dialect works.

    Raises whatever the client raises once no spelling is left, so a real
    outage still looks like an outage rather than an empty answer.
    """
    tool_name = tool_spec["toolSpec"]["name"]
    start = _ACCEPTED.get(model_id, 0)
    last_error: Exception | None = None

    for index in range(start, len(_CHOICES)):
        choice = _CHOICES[index]
        config: dict[str, Any] = {"tools": [tool_spec]}
        config["toolChoice"] = {"tool": {"name": tool_name}} if choice is None else choice
        try:
            response = with_retry(
                lambda config=config: client.converse(
                    modelId=model_id,
                    system=[{"text": system}],
                    messages=messages,
                    toolConfig=config,
                    inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
                )
            )
        except Exception as error:  # noqa: BLE001 - the client's exception types vary
            if "toolChoice" not in str(error):
                # Not a dialect problem. Retrying a different spelling would
                # turn a credential or quota failure into three of them.
                raise
            last_error = error
            continue
        _ACCEPTED[model_id] = index
        return response

    assert last_error is not None
    raise last_error


def reset_dialect_cache() -> None:
    """Forget what every model accepted.

    Process-level state is right for a capability that cannot change under a
    running server, and wrong for a test suite, where one test's stub would
    otherwise inherit a dialect negotiated against a different model.
    """
    _ACCEPTED.clear()


def tool_choice_used(model_id: str) -> str:
    """Which spelling this model settled on, for the audit trail."""
    index = _ACCEPTED.get(model_id)
    if index is None:
        return "not yet called"
    return ("tool", "any", "auto")[index]
