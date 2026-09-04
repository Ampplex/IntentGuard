"""The checkout surface, and the hole it must not open.

A stock create-order endpoint takes an amount from the request body. Here that
would let anyone who can reach the endpoint name their own figure, and every
constraint the engine checks would be beside the point. These tests are mostly
about that.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from intentguard.api.app import CheckoutRequest, create_app
from intentguard.api.settings import Credentials
from intentguard.api.signature import expected_signature
from intentguard.core import LineItem, LineItemKind, from_rupees
from intentguard.payments import RefusingClient
from tests.fixtures import a_ledger, a_trial_recurrence, an_offer

SECRET = "test_secret_never_leaves_the_server"
CREDS = Credentials(key_id="rzp_test_abc123", key_secret=SECRET)


class FakeRazorpay:
    def __init__(self) -> None:
        self.orders: list[dict[str, Any]] = []

    def create_order(self, **kwargs: Any) -> dict[str, Any]:
        self.orders.append(kwargs)
        return {
            "id": f"order_{len(self.orders):04d}",
            "amount": kwargs["amount_paise"],
            "currency": kwargs["currency"],
            "receipt": kwargs["receipt"],
            "status": "created",
        }

    def fetch_order(self, order_id: str) -> dict[str, Any]:
        return {"id": order_id, "status": "created"}

    def fetch_order_payments(self, order_id: str) -> dict[str, Any]:
        return {"entity": "collection", "count": 0, "items": []}


def body(ledger=None, offer=None) -> dict[str, Any]:
    """A request as a caller would actually send one.

    created_at is omitted so the server stamps it. Sending the fixture's own
    timestamp made every mandate arrive already expired against wall-clock time,
    which is the engine being right about a fixture being stale.
    """
    ledger = ledger or a_ledger()
    offer = offer or an_offer()
    payload = json.loads(ledger.model_dump_json())
    payload.pop("created_at", None)
    return {"ledger": payload, "offer": json.loads(offer.model_dump_json())}


def over_budget():
    return an_offer(
        line_items=[
            LineItem(label="Shoes", amount_paise=from_rupees(9000), kind=LineItemKind.PRODUCT)
        ],
        total_paise=from_rupees(9000),
    )


@pytest.fixture
def gateway():
    fake = FakeRazorpay()
    return TestClient(create_app(CREDS, fake)), fake


# --- the hole that must not exist ----------------------------------------


def test_the_request_has_nowhere_to_put_an_amount() -> None:
    """Structural, not a validation rule.

    The endpoint accepts a mandate and an offer. There is no amount field to
    supply, so a caller cannot name a figure even by trying.
    """
    assert set(CheckoutRequest.model_fields) == {"ledger", "offer", "negotiated_product"}
    for name in CheckoutRequest.model_fields:
        assert "amount" not in name and "paise" not in name


def test_a_blocked_offer_never_reaches_razorpay(gateway) -> None:
    """The project's central invariant, over HTTP.

    The client raises if anything calls it, so a regression cannot pass quietly.
    """
    client = TestClient(create_app(CREDS, RefusingClient()))
    response = client.post("/api/create-order", json=body(offer=over_budget()))

    assert response.status_code == 409
    payload = response.json()
    assert payload["decision"] == "BLOCK"
    assert payload["razorpay_called"] is False
    assert any(v["code"] == "TOTAL_EXCEEDS_MAX" for v in payload["violations"])


def test_a_hidden_subscription_never_reaches_razorpay() -> None:
    client = TestClient(create_app(CREDS, RefusingClient()))
    response = client.post(
        "/api/create-order", json=body(offer=an_offer(recurring=[a_trial_recurrence()]))
    )
    assert response.status_code == 409
    assert any(v["code"] == "RECURRING_NOT_AUTHORIZED" for v in response.json()["violations"])


def test_an_escalation_never_reaches_razorpay_either() -> None:
    offer = an_offer()
    unjudgeable = offer.model_copy(
        update={"product": offer.product.model_copy(update={"condition": "gently loved"})}
    )
    client = TestClient(create_app(CREDS, RefusingClient()))
    response = client.post("/api/create-order", json=body(offer=unjudgeable))

    assert response.status_code == 409
    assert response.json()["decision"] == "ESCALATE"
    assert response.json()["escalation_question"]


def test_a_refusal_explains_itself_to_the_person_reading_it(gateway) -> None:
    client = TestClient(create_app(CREDS, RefusingClient()))
    violations = client.post("/api/create-order", json=body(offer=over_budget())).json()[
        "violations"
    ]
    assert "you authorized at most" in violations[0]["explanation"]


# --- the allowed path -----------------------------------------------------


def test_an_allowed_offer_creates_an_order(gateway) -> None:
    client, fake = gateway
    response = client.post("/api/create-order", json=body())

    assert response.status_code == 200
    payload = response.json()
    assert payload["order_id"] == "order_0001"
    assert payload["currency"] == "INR"
    assert len(fake.orders) == 1


def test_the_amount_comes_from_the_decision_not_the_request(gateway) -> None:
    """The figure Razorpay is given is the one the engine checked."""
    client, fake = gateway
    payload = client.post("/api/create-order", json=body()).json()
    assert payload["amount"] == from_rupees(4200)
    assert fake.orders[0]["amount_paise"] == from_rupees(4200)


def test_the_order_carries_the_intent_and_offer_hash(gateway) -> None:
    client, fake = gateway
    client.post("/api/create-order", json=body())
    notes = fake.orders[0]["notes"]
    assert notes["intent_id"].startswith("int_")
    assert notes["offer_hash"].startswith("sha256:")


def test_an_unreadable_mandate_is_a_bad_request(gateway) -> None:
    client, _ = gateway
    response = client.post("/api/create-order", json={"ledger": {"nonsense": 1}, "offer": {}})
    assert response.status_code == 400
    assert "unreadable mandate" in response.json()["detail"]


# --- the secret ------------------------------------------------------------


def test_the_config_endpoint_serves_the_key_id_only(gateway) -> None:
    client, _ = gateway
    payload = client.get("/api/config").json()
    assert payload == {"key_id": "rzp_test_abc123"}
    assert "secret" not in json.dumps(payload).lower()


def test_the_secret_appears_in_no_response(gateway) -> None:
    """Checked across every endpoint rather than trusted to one review."""
    client, _ = gateway
    responses = [
        client.get("/api/config"),
        client.post("/api/create-order", json=body()),
        client.post("/api/create-order", json=body(offer=over_budget())),
        client.post(
            "/api/verify-payment",
            json={
                "razorpay_order_id": "order_1",
                "razorpay_payment_id": "pay_1",
                "razorpay_signature": "wrong",
            },
        ),
    ]
    for response in responses:
        assert SECRET not in response.text


def test_the_secret_is_not_in_the_page_served_to_the_browser(gateway) -> None:
    client, _ = gateway
    page = client.get("/").text
    assert SECRET not in page
    assert "rzp_test_abc123" not in page, "the key id is fetched, not baked in"
    assert "checkout.razorpay.com/v1/checkout.js" in page


# --- signature verification -----------------------------------------------


def test_a_genuine_signature_verifies(gateway) -> None:
    client, _ = gateway
    order_id, payment_id = "order_abc", "pay_xyz"
    response = client.post(
        "/api/verify-payment",
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": expected_signature(order_id, payment_id, SECRET),
        },
    )
    assert response.status_code == 200
    assert response.json()["verified"] is True


def test_a_forged_signature_is_refused_and_nothing_is_marked_paid(gateway) -> None:
    client, _ = gateway
    response = client.post(
        "/api/verify-payment",
        json={
            "razorpay_order_id": "order_abc",
            "razorpay_payment_id": "pay_xyz",
            "razorpay_signature": "f" * 64,
        },
    )
    assert response.status_code == 400
    assert "not treated as made" in response.json()["detail"]


def test_a_signature_from_a_different_order_does_not_verify(gateway) -> None:
    """Otherwise a signature could be replayed across orders."""
    client, _ = gateway
    stolen = expected_signature("order_other", "pay_xyz", SECRET)
    response = client.post(
        "/api/verify-payment",
        json={
            "razorpay_order_id": "order_abc",
            "razorpay_payment_id": "pay_xyz",
            "razorpay_signature": stolen,
        },
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        {"razorpay_order_id": "", "razorpay_payment_id": "p", "razorpay_signature": "s"},
        {"razorpay_order_id": "o", "razorpay_payment_id": "p"},
        {},
    ],
    ids=["blank order", "missing signature", "empty"],
)
def test_missing_fields_are_a_bad_request(gateway, payload: dict) -> None:
    client, _ = gateway
    assert client.post("/api/verify-payment", json=payload).status_code in {400, 422}


def test_a_mandate_without_a_timestamp_is_stamped_on_arrival(gateway) -> None:
    """A caller that sends no created_at gets one, rather than an expiry."""
    client, _ = gateway
    assert client.post("/api/create-order", json=body()).status_code == 200


def test_a_stale_mandate_is_still_refused(gateway) -> None:
    """Stamping the missing case must not become ignoring the supplied one."""
    client, _ = gateway
    stale = body()
    stale["ledger"]["created_at"] = "2020-01-01T00:00:00+00:00"
    response = client.post("/api/create-order", json=stale)
    assert response.status_code == 409
    assert any(v["code"] == "LEDGER_EXPIRED" for v in response.json()["violations"])


# --- the pipeline the React app drives ------------------------------------
# Every endpoint the page calls, exercised against the same app object the
# server runs. The page has no other way to reach the system.


def test_the_built_app_is_served_at_the_root(gateway) -> None:
    client, _ = gateway
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_extraction_reports_which_backend_read_the_instruction(gateway) -> None:
    """A page that cannot tell you whether a model was involved is a page you
    cannot reason about."""
    client, _ = gateway
    payload = client.post(
        "/api/extract",
        json={"instruction": "Buy me a pair of new running shoes, budget 5000 rupees."},
    ).json()
    assert payload["backend"]
    assert payload["ledger"]["hard"]["max_total_paise"] == from_rupees(5000)


def test_an_instruction_with_no_ceiling_returns_a_question_not_a_mandate(gateway) -> None:
    client, _ = gateway
    payload = client.post(
        "/api/extract", json={"instruction": "Get me a decent laptop, nothing too pricey."}
    ).json()
    assert payload["ledger"] is None
    assert payload["question"]
    assert "max_total_paise" in payload["weak_fields"]


def test_negotiation_runs_the_real_agents_and_hides_the_ceiling(gateway) -> None:
    client, _ = gateway
    mandate = client.post(
        "/api/extract",
        json={"instruction": "Buy me a pair of new running shoes, budget 5000 rupees."},
    ).json()
    deal = client.post(
        "/api/negotiate",
        json={"ledger": mandate["ledger"], "hostility": "none", "concession": "haggle"},
    ).json()

    assert deal["ceiling_visible_to_merchant"] is False
    assert deal["rounds"], "a negotiation with no rounds did not happen"
    assert deal["offer"]["total_paise"] > 0


def test_a_hostile_merchant_is_refused_through_the_whole_chain(gateway) -> None:
    """Extraction, negotiation and the gate, in the order the page calls them."""
    client, _ = gateway
    mandate = client.post(
        "/api/extract",
        json={
            "instruction": "Buy me a pair of new running shoes, budget 5000 rupees. "
            "No subscriptions."
        },
    ).json()
    deal = client.post(
        "/api/negotiate",
        json={
            "ledger": mandate["ledger"],
            "hostility": "trial_subscription",
            "concession": "meet",
        },
    ).json()
    verdict = client.post(
        "/api/create-order",
        json={
            "ledger": mandate["ledger"],
            "offer": deal["offer"],
            "negotiated_product": deal["negotiated_product"],
        },
    )
    assert verdict.status_code == 409
    assert any(v["code"] == "RECURRING_NOT_AUTHORIZED" for v in verdict.json()["violations"])


def test_an_unknown_merchant_behaviour_is_rejected(gateway) -> None:
    client, _ = gateway
    mandate = client.post(
        "/api/extract", json={"instruction": "Buy shoes under 5000 rupees."}
    ).json()
    response = client.post(
        "/api/negotiate", json={"ledger": mandate["ledger"], "hostility": "made_up"}
    )
    assert response.status_code == 400


def test_the_catalog_is_readable_so_a_swap_can_be_spotted(gateway) -> None:
    client, _ = gateway
    catalog = client.get("/api/catalog").json()
    assert len(catalog) > 5
    assert all("title" in item and "price_paise" in item for item in catalog)
