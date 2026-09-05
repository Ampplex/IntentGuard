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

import json
import os
import re
import tempfile
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..audit.store import AuditLog
from ..buyer import BuyerAgent
from ..core.enums import Outcome
from ..core.intent import IntentLedger
from ..core.violations import ViolationCode
from ..core.vocabulary import CATEGORY_WORDS, GENERIC_PRODUCT_WORDS
from ..gate import receive
from ..ledger import BedrockExtractor, RuleBasedExtractor, build_ledger
from ..merchant import CATALOG, Concession, Hostility, MerchantAgent, project
from ..merchant.embeddings import BedrockEmbeddings
from ..merchant.rerank import BedrockReranker
from ..merchant.search import document_for
from ..payments import (
    MINIMUM_AMOUNT_PAISE,
    Execution,
    HttpRazorpayClient,
    execute,
)
from .settings import Credentials, credentials, load_env
from .signature import signature_matches

STATIC = Path(__file__).parent / "static"
APP_DIR = STATIC / "app"
DATA_DIR = Path(__file__).resolve().parents[3] / "data"


def _audit_path() -> Path:
    """Where decisions are written, on a host that may not let us write.

    The repository's data directory is right where there is one. A serverless
    filesystem is read-only apart from a scratch directory, so the fallback
    keeps the audit trail working -- but only within one warm instance, and that
    is a real reduction rather than a detail. The compliance receipt rests on the
    record outliving the request that made it. A deployment that needs a durable
    audit trail needs a database, and this function is where it would be wired.
    """
    override = os.environ.get("INTENTGUARD_AUDIT_PATH")
    if override:
        return Path(override)
    repo = DATA_DIR / "api-audit.jsonl"
    probe = DATA_DIR / ".writable"
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        probe.write_text("")
        probe.unlink()
        return repo
    except OSError:
        return Path(tempfile.gettempdir()) / "intentguard-audit.jsonl"


AUDIT_PATH = _audit_path()


class CheckoutRequest(BaseModel):
    """A mandate and a cart. Deliberately no amount field.

    An amount here would be a number the caller chose, and the whole point of
    the system is that the number is one the engine derived.
    """

    ledger: dict[str, Any]
    offer: dict[str, Any]
    # What was on the table when the negotiation opened. A swap partway through
    # is invisible to any check that only sees the final cart.
    negotiated_product: str | None = None


class ExtractRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=2_000)


class NegotiateRequest(BaseModel):
    ledger: dict[str, Any]
    hostility: str = "none"
    concession: str = "haggle"


class VerifyRequest(BaseModel):
    razorpay_order_id: str = Field(min_length=1)
    razorpay_payment_id: str = Field(min_length=1)
    razorpay_signature: str = Field(min_length=1)


def create_app(creds: Credentials | None = None, client: Any = None) -> FastAPI:
    """Build the app. Credentials and client are injected so tests need neither."""
    app = FastAPI(title="IntentGuard checkout", version="0.1.0")

    # The page and the API are served together by default, and separately when
    # the page is on a CDN and the API is on a machine with a filesystem for the
    # audit trail. An allowlist rather than "*": the endpoints here create
    # payment orders, and a wildcard would let any site on the internet drive
    # them from a visitor's browser.
    allowed = [
        o.strip() for o in os.environ.get("INTENTGUARD_ALLOWED_ORIGINS", "").split(",") if o.strip()
    ]
    if allowed:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )

    resolved = creds or credentials()
    razorpay = client or HttpRazorpayClient(resolved.key_id, resolved.key_secret)
    log = AuditLog(AUDIT_PATH)

    if APP_DIR.exists():
        # The built React app. Mounted under /app because Vite emits hashed
        # asset paths, and served at / as well so the demo is one URL.
        app.mount("/app", StaticFiles(directory=APP_DIR, html=True), name="app")

    @app.get("/")
    def page() -> FileResponse:
        """The React app when it has been built, the plain page otherwise.

        Falling back rather than failing means the backend is demonstrable on a
        machine with no node toolchain, which is the situation this was written
        on.
        """
        built = APP_DIR / "index.html"
        return FileResponse(built if built.exists() else STATIC / "checkout.html")

    @app.get("/api/config")
    def config() -> dict[str, str]:
        """The key id only. The secret has no path to this response."""
        return resolved.public()

    @app.post("/api/extract")
    def extract(request: ExtractRequest) -> dict[str, Any]:
        """Read an instruction into a mandate. This is the only model call.

        Bedrock is used when it is configured and the deterministic parser
        otherwise, and the response says which ran. A page that cannot tell you
        whether a model was involved is a page you cannot reason about.
        """
        extractor, backend = _extractor()
        try:
            extracted = extractor.extract(request.instruction)
        except Exception as error:  # noqa: BLE001 - any model failure, not one kind
            # A throttled or unreachable model must not take the shop down. Under
            # concurrent load Bedrock returned ThrottlingException, boto's retries
            # and ours both ran out, and the request became a 500 -- six times in
            # thirty-five. The deterministic parser needs no network and is
            # already the fallback everywhere else, so it is the fallback here.
            # Reading is the only thing a model is used for; nothing about the
            # decision changes, and the response says which parser ran.
            extracted = RuleBasedExtractor().extract(request.instruction)
            backend = f"rule-based (fell back: {type(error).__name__})"

        # The model classifies a category from world knowledge, and does it
        # inconsistently for brand names. Where it returned nothing and the
        # instruction names something on the shelf, the shelf answers.
        resolved_from_catalog = None
        if extracted.category is None:
            resolved_from_catalog = category_from_catalog(request.instruction)
            if resolved_from_catalog is not None:
                extracted = extracted.model_copy(update={"category": resolved_from_catalog})

        proposal = build_ledger(request.instruction, extracted, created_at=datetime.now(UTC))
        return {
            "backend": backend,
            "category_from_catalog": resolved_from_catalog,
            "extracted": json.loads(extracted.model_dump_json()),
            "confidence": {k: round(v, 2) for k, v in proposal.confidence.items()},
            "weak_fields": list(proposal.weak_fields),
            "question": proposal.question,
            "ledger": (json.loads(proposal.ledger.model_dump_json()) if proposal.ledger else None),
        }

    @app.post("/api/negotiate")
    def negotiate(request: NegotiateRequest) -> dict[str, Any]:
        """Run a real negotiation between the buyer and merchant agents."""
        try:
            ledger = IntentLedger.model_validate(request.ledger)
        except Exception as error:
            raise HTTPException(status_code=400, detail=f"unreadable mandate: {error}") from error

        try:
            # Validated before retrieval is touched: a bad behaviour name is a
            # 400, and it should not first pay to embed the whole catalog.
            hostility = Hostility(request.hostility)
            concession = Concession(request.concession)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        dense, reranker, retrieval = _retrieval()
        try:
            merchant = MerchantAgent(hostility, concession, reranker=reranker, dense=dense)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        view = project(ledger)
        # The opening quote must come from the same merchant that negotiates.
        # A fresh neutral merchant here made the gate compare the final hostile
        # offer with an unrelated product and report a false substitution.
        opening = merchant.quote(view)
        buyer = BuyerAgent(ledger)
        negotiation = buyer.negotiate(merchant)

        return {
            "merchant_view": json.loads(view.model_dump_json()),
            "ceiling_visible_to_merchant": "max_total" in view.model_dump_json(),
            "target_paise": negotiation.target_paise,
            "ending": negotiation.ending.value,
            "exchanges": negotiation.exchanges,
            "rounds": [json.loads(r.model_dump_json()) for r in negotiation.rounds],
            "negotiated_product": opening["product"]["title"] if opening else None,
            "offer": negotiation.final_payload,
            "retrieval": {**retrieval, "rerank_calls": merchant.rerank_calls},
            "in_stock": opening is not None,
        }

    @app.get("/api/catalog")
    def catalog() -> list[dict[str, Any]]:
        """What the merchant sells. The gate uses it to spot a second product."""
        return [json.loads(item.model_dump_json()) for item in CATALOG]

    @app.get("/api/metrics")
    def metrics() -> dict[str, Any]:
        """The figures the landing page quotes, read from the last real run.

        Typing them into the page would make them a claim rather than a result.
        Serving the files the benchmark and the revenue experiment wrote means
        the page cannot say anything the run did not produce, and goes empty
        rather than stale if the files are missing.
        """
        out: dict[str, Any] = {"violation_codes": [c.value for c in ViolationCode]}
        for name in ("dashboard", "revenue"):
            path = DATA_DIR / f"{name}.json"
            if path.is_file():
                try:
                    out[name] = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
        return out

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
        decision, record = receive(
            ledger,
            request.offer,
            now=now,
            log=log,
            negotiated_product=request.negotiated_product,
            known_products=[item.title for item in CATALOG],
        )

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


@lru_cache(maxsize=1)
def _bedrock_client() -> Any:
    """One client for every model this process calls.

    Extraction, embeddings and reranking are three jobs, not three services.
    Building a client each time would repeat credential resolution and open a
    new connection pool per call for no benefit.
    """
    load_env()
    if not os.environ.get("AWS_ACCESS_KEY_ID"):
        return None
    try:
        import boto3

        return boto3.client(
            "bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-west-2")
        )
    except Exception:  # pragma: no cover - depends on the environment
        return None


@lru_cache(maxsize=1)
def _retrieval() -> tuple[Any, Any, dict[str, Any]]:
    """The merchant's search: a dense arm and a reranker, if both can be built.

    Cached because the embedding cache lives on the retriever. Rebuilding it per
    request would re-embed the whole catalog every time, which is the difference
    between paying for fifteen vectors once and paying for them all day.
    """
    client = _bedrock_client()
    if client is None:
        return None, None, {"dense": None, "reranker": None, "note": "no Bedrock credentials"}
    dense = reranker = None
    try:
        dense = BedrockEmbeddings(client)
        if os.environ.get("INTENTGUARD_WARM_EMBEDDINGS", "1") != "0":
            # Fifteen calls before the first answer. Worth it on a long-lived
            # server, and the wrong trade on a cold serverless start where it
            # can outlast the invocation itself, so it is switchable.
            dense.warm([document_for(item) for item in CATALOG])
    except Exception:  # pragma: no cover - depends on the environment
        dense = None
    try:
        reranker = BedrockReranker(client)
    except Exception:  # pragma: no cover - depends on the environment
        reranker = None
    return (
        dense,
        reranker,
        {
            "dense": os.environ.get("BEDROCK_EMBED_MODEL") if dense else None,
            "reranker": os.environ.get("BEDROCK_MODEL_ID") if reranker else None,
            "arms": ["bm25", "trigram"] + (["dense"] if dense else []),
            "fusion": "reciprocal rank fusion, k=60",
        },
    )


def category_from_catalog(instruction: str) -> str | None:
    """The category of a product the shop actually sells, read from the shelf.

            # Use the same merchant instance for the opening quote and every
            # counter. Comparing the final offer with a neutral merchant's quote
            # can report a substitution that the selected merchant never made.
            opening = merchant.quote(view)
    well for "running shoes" and inconsistently for "Nike Revolution 7" -- a
    proper noun carries no category word, so the answer rests on world
    knowledge and varies run to run. Watching it fail on a product the shopper
    had just clicked made the position untenable: the shop knows what it sells,
    so it should not need a model to recognise its own stock.

    Deterministic, and a fallback only. It never overrides what the model
    returned, and it is not a decision -- the gate re-checks the offer either
    way. A distinctive word is required, so "Nike" reaches footwear while
    "a laptop" still resolves through the model or asks.
    """
    words = set(re.split(r"[^a-z0-9]+", instruction.lower())) - {""}
    if not words:
        return None

    # Words that name a kind of thing match the wrong shelf: "a laptop"
    # shares "laptop" with the Laptop Backpack and resolved to accessories,
    # which is a worse answer than none. Only a distinctive word counts.
    common = set(GENERIC_PRODUCT_WORDS)
    for group in CATEGORY_WORDS.values():
        common |= set(group)

    best: tuple[int, str] | None = None
    for item in CATALOG:
        identity = f"{item.title} {item.brand or ''}"
        tokens = {
            t for t in re.split(r"[^a-z0-9]+", identity.lower()) if len(t) > 2 and t not in common
        }
        shared = tokens & words
        if shared and (best is None or len(shared) > best[0]):
            best = (len(shared), item.category.value)
    return best[1] if best else None


def _extractor() -> tuple[Any, str]:
    """Bedrock when it is configured, the deterministic parser otherwise.

    Chosen at call time rather than at startup so the server does not need
    restarting when credentials appear, and reported in the response so nobody
    has to guess which one produced a field.
    """
    load_env()
    if os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("BEDROCK_MODEL_ID"):
        try:
            return (
                BedrockExtractor(_bedrock_client()),
                f"bedrock:{os.environ['BEDROCK_MODEL_ID']}",
            )
        except Exception:  # pragma: no cover - depends on the environment
            pass
    return RuleBasedExtractor(), "rule-based (no model configured)"


def main() -> None:  # pragma: no cover - entry point
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8000)


if __name__ == "__main__":  # pragma: no cover
    main()
