"""The Razorpay adapter.

Endpoints and field names below were read from Razorpay's live documentation
rather than recalled, because a plausible-looking wrong API call is worse than
an honest gap. What was verified:

    POST /v1/orders                     create an order
    GET  /v1/orders/{id}                fetch one
    GET  /v1/orders/{id}/payments       fetch its payments

`amount` is an integer in the smallest currency subunit -- paise for INR -- with
a minimum of 100, which is one rupee. `receipt` is at most 40 ASCII characters
and is documented as acting as the idempotency key. Authentication is HTTP Basic
with the key id and secret.

**No idempotency header is documented**, so none is sent. Idempotency rests on
`receipt` alone, which is what Razorpay says it is for. Inventing a header that
looks right would be exactly the failure this file's docstring exists to
prevent.

Test mode only, enforced at construction rather than by convention.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any, Protocol

API_ROOT = "https://api.razorpay.com/v1"

# Razorpay's own minimum for INR. An authorization for less cannot be executed,
# and finding that out from a 400 after the fact is worse than refusing here.
MINIMUM_AMOUNT_PAISE = 100

# Test keys carry this prefix. The invariant is "no live keys, fail loudly at
# startup", so the check is in the constructor and not in a code review.
TEST_KEY_PREFIX = "rzp_test_"

DEFAULT_TIMEOUT_SECONDS = 10.0


class LiveKeyRefused(RuntimeError):
    """Raised when a key that is not a test key is supplied."""


class PaymentTimeout(RuntimeError):
    """The request went out and the answer did not come back.

    Distinct from a failure. A timeout means the order may or may not exist, and
    the only safe response is to stop and ask Razorpay rather than to retry.
    """


class PaymentRefused(RuntimeError):
    """Razorpay answered, and the answer was no."""


class RazorpayClient(Protocol):
    def create_order(
        self, *, amount_paise: int, currency: str, receipt: str, notes: dict[str, str]
    ) -> dict[str, Any]: ...

    def fetch_order(self, order_id: str) -> dict[str, Any]: ...

    def fetch_order_payments(self, order_id: str) -> dict[str, Any]: ...


class HttpRazorpayClient:
    """Talks to Razorpay over HTTPS using the standard library.

    urllib rather than a client library: the dependency list stays boring and
    the request shape stays visible, which matters for a file whose whole claim
    is that it matches published documentation.
    """

    def __init__(
        self,
        key_id: str,
        key_secret: str,
        *,
        api_root: str = API_ROOT,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not key_id.startswith(TEST_KEY_PREFIX):
            raise LiveKeyRefused(
                f"key id must begin with {TEST_KEY_PREFIX!r}; this project is test mode only "
                "and will not execute against real money"
            )
        self.key_id = key_id
        self.key_secret = key_secret
        self.api_root = api_root.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _auth_header(self) -> str:
        raw = f"{self.key_id}:{self.key_secret}".encode()
        return "Basic " + base64.b64encode(raw).decode("ascii")

    def _request(self, method: str, path: str, body: dict | None = None) -> dict[str, Any]:
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            f"{self.api_root}{path}",
            data=payload,
            method=method,
            headers={
                "Authorization": self._auth_header(),
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except TimeoutError as error:
            # socket.timeout is an alias of TimeoutError from Python 3.10, so one
            # clause covers both. A timeout is not a failure and must not be
            # collapsed into one: a failure means nothing happened, a timeout
            # means nobody knows.
            raise PaymentTimeout(f"{method} {path} timed out") from error
        except urllib.error.URLError as error:
            if isinstance(getattr(error, "reason", None), TimeoutError):
                raise PaymentTimeout(f"{method} {path} timed out") from error
            raise PaymentRefused(f"{method} {path} failed: {error}") from error

    def create_order(
        self, *, amount_paise: int, currency: str, receipt: str, notes: dict[str, str]
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/orders",
            {
                "amount": amount_paise,
                "currency": currency,
                "receipt": receipt,
                "notes": notes,
            },
        )

    def fetch_order(self, order_id: str) -> dict[str, Any]:
        return self._request("GET", f"/orders/{order_id}")

    def fetch_order_payments(self, order_id: str) -> dict[str, Any]:
        return self._request("GET", f"/orders/{order_id}/payments")


class RefusingClient:
    """A client that raises if anything calls it.

    Used wherever the rail must not be reached. "Gated" means the call is never
    made, not that it is made and rolled back, and the only way to test the
    difference is a client that cannot be called quietly.
    """

    class Called(AssertionError):
        pass

    def create_order(self, **kwargs: Any) -> dict[str, Any]:
        raise self.Called(f"the payment rail was reached with {kwargs}")

    def fetch_order(self, order_id: str) -> dict[str, Any]:
        raise self.Called(f"the payment rail was reached for order {order_id}")

    def fetch_order_payments(self, order_id: str) -> dict[str, Any]:
        raise self.Called(f"the payment rail was reached for order {order_id}")
