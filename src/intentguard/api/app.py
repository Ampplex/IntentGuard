"""Razorpay Standard Checkout, wired through the gate rather than around it.

**The one deviation from a stock integration, and the reason for it.**

A stock create-order endpoint takes an amount from the request body and calls
Razorpay with it. Here that would be a hole straight through the thing this
project exists to do: anyone who can reach the endpoint could name their own
figure, and every constraint the engine checks would be irrelevant because the
charge never passed through it.

So `/api/create-order` does not accept an amount. It accepts a mandate and an
offer, runs the gate, and takes the figure from the audit record the gate wrote.
A BLOCK or an ESCALATE returns 409 and no Razorpay call is made at all -- not
made and rolled back, not made. The existing test that asserts this uses a
client which raises if anything calls it, and the HTTP layer is on the same
path.

**Where a browser checkout fits a human-not-present system.** IntentGuard is
built for an agent buying without a person present, and Standard Checkout is a
modal a person interacts with. The two meet at the escalation: when the engine
cannot decide, a person is already being asked, and this is the surface they
answer on. The demo page walks that path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from ..audit.store import AuditLog
from ..core.enums import Outcome
from ..core.intent import IntentLedger
from ..gate import receive
from ..payments import (
    MINIMUM_AMOUNT_PAISE,
    Execution,
    HttpRazorpayClient,
    execute,
)
from .settings import Credentials, credentials
from .signature import signature_matches

STATIC = Path(__file__).parent / "static"
AUDIT_PATH = Path(__file__).resolve().parents[3] / "data" / "api-audit.jsonl"


class CheckoutRequest(BaseModel):
    """A mandate and a cart. Deliberately no amount field.

    An amount here would be a number the caller chose, and the whole point of
    the system is that the number is one the engine derived.
    """

    ledger: dict[str, Any]
    offer: dict[str, Any]


class VerifyRequest(BaseModel):
    razorpay_order_id: str = Field(min_length=1)
    razorpay_payment_id: str = Field(min_length=1)
    razorpay_signature: str = Field(min_length=1)


def create_app(creds: Credentials | None = None, client: Any = None) -> FastAPI:
    """Build the app. Credentials and client are injected so tests need neither."""
    app = FastAPI(title="IntentGuard checkout", version="0.1.0")
    resolved = creds or credentials()
    razorpay = client or HttpRazorpayClient(resolved.key_id, resolved.key_secret)
    log = AuditLog(AUDIT_PATH)

    @app.get("/")
    def page() -> FileResponse:
        return FileResponse(STATIC / "checkout.html")

    @app.get("/api/config")
    def config() -> dict[str, str]:
        """The key id only. The secret has no path to this response."""
        return resolved.public()

    @app.post("/api/create-order")
    def create_order(request: CheckoutRequest) -> JSONResponse:
        """Judge the cart, then create an order for the amount that was judged."""
        try:
            ledger = IntentLedger.model_validate(
                {
                    **request.ledger,
                    "created_at": request.ledger.get("created_at") or datetime.now(UTC),
                }
            )
        except Exception as error:
            raise HTTPException(status_code=400, detail=f"unreadable mandate: {error}") from error

        now = datetime.now(UTC)
        decision, record = receive(ledger, request.offer, now=now, log=log)

        if decision.decision is not Outcome.ALLOW:
            # 409 rather than 400: the request was well formed and the answer is
            # no. Nothing was sent to Razorpay.
            return JSONResponse(
                status_code=409,
                content={
                    "decision": decision.decision.value,
                    "violations": [
                        {"code": v.code.value, "explanation": v.explanation}
                        for v in decision.violations
                    ],
                    "escalation_question": decision.escalation_question,
                    "razorpay_called": False,
                },
            )

        attempt, _ = execute(ledger, record, razorpay, now=now, log=log)

        if attempt.outcome is Execution.BELOW_MINIMUM:
            raise HTTPException(
                status_code=400,
                detail=f"amount is under Razorpay's minimum of {MINIMUM_AMOUNT_PAISE} paise",
            )
        if attempt.outcome is Execution.UNCERTAIN:
            # The request went out and no answer came back. Saying "failed" here
            # would invite a retry, and a retry is how one order becomes two.
            raise HTTPException(
                status_code=504,
                detail=f"{attempt.detail}. Receipt {attempt.receipt} identifies the attempt.",
            )
        if attempt.outcome is not Execution.PLACED:
            raise HTTPException(status_code=502, detail=attempt.detail)

        return JSONResponse(
            content={
                "order_id": attempt.order_id,
                "amount": attempt.amount_paise,
                "currency": ledger.hard.currency,
                "receipt": attempt.receipt,
                "offer_hash": record.offer_hash,
            }
        )

    @app.post("/api/verify-payment")
    def verify_payment(request: VerifyRequest) -> dict[str, Any]:
        """Check Razorpay's signature. Nothing is marked paid without it."""
        if not signature_matches(
            request.razorpay_order_id,
            request.razorpay_payment_id,
            request.razorpay_signature,
            resolved.key_secret,
        ):
            raise HTTPException(
                status_code=400,
                detail="signature does not match; this payment is not treated as made",
            )
        return {
            "verified": True,
            "order_id": request.razorpay_order_id,
            "payment_id": request.razorpay_payment_id,
        }

    return app


def main() -> None:  # pragma: no cover - entry point
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8000)


if __name__ == "__main__":  # pragma: no cover
    main()
