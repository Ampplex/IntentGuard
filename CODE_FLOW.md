# IntentGuard: Code Flow

This document explains how the implementation behaves when a request moves through the system. Read it as a journey through the code: a user gives an instruction, a mandate is built, a merchant proposes a cart, the gate evaluates that cart, and Razorpay is reached only after the decision and its evidence exist.

The central runtime path is:

```text
User instruction
    |
    v
POST /api/extract
    |
    v
Extractor
    |
    v
build_ledger()
    |
    v
Usable mandate?
    |
    +-- No  --> Mandate question
    |
    +-- Yes --> IntentLedger
                         |
                         v
              Merchant projection
                         |
                         v
   Buyer and merchant negotiation
                         |
                         v
                 Final offer payload
                         |
                         v
                POST /api/create-order
                         |
                         v
         receive(): validate untrusted payload
                         |
                         v
                     run_gate()
                         |
                         v
                 policy.evaluate()
                         |
                         v
          Semantic drift and substitution
                         |
                         v
                     Decision
                 /      |       \
             BLOCK  ESCALATE   ALLOW
                 |      |          |
                 v      v          v
             Audit  Persist      Audit
              only  question   then execute
                                          |
                                          v
                              Razorpay test API
                                          |
                                          v
                              Verify payment signature
```

The important boundary is between the merchant-side code and `gate.receive()`. Before that boundary, values are suggestions from an untrusted agent. After that boundary, the trusted side parses, checks, hashes, audits, and controls payment execution.

## 1. Application startup and dependency wiring

The process starts in `src/intentguard/api/app.py`. `create_app()` constructs the FastAPI application and wires the trusted payment and audit dependencies.

When the application starts, `create_app()` resolves credentials through `api.settings.credentials()`. That function calls `load_env()` to read `.env` without overwriting existing environment variables. It requires `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET`, then rejects any key that does not begin with `rzp_test_`. This makes test mode an executable rule rather than a deployment convention.

`create_app()` then creates an `HttpRazorpayClient` and an `AuditLog` pointed at `data/api-audit.jsonl`. The browser receives only `Credentials.public()`, which returns the key id. The secret remains inside the server process.

If the compiled React application exists under `api/static/app`, FastAPI mounts it. Otherwise, the root route serves the fallback checkout page. This is presentation wiring; it does not participate in authorization.

## 2. Turning a human instruction into a mandate

The first request is `POST /api/extract`, handled by the nested `extract()` route in `api/app.py`.

The route calls `_extractor()`. This function chooses the extraction implementation at request time:

- If AWS credentials and `BEDROCK_MODEL_ID` are configured, it tries `BedrockExtractor`.
- If Bedrock cannot be constructed or is not configured, it uses `RuleBasedExtractor`.

Both implementations satisfy the `Extractor` protocol and return the same `ExtractedIntent` schema. The important design is that extraction has no authorization output. It extracts fields such as category, amount text, quantity, condition, product reference, recurrence permission, EMI permission, add-on permission, and exclusions. It does not return a payment decision.

`RuleBasedExtractor.extract()` is the deterministic fallback. It first removes the instruction's surrounding whitespace and identifies a money expression with `_amount()`. `_amount()` checks bounded phrases such as “under”, “budget”, and “up to”, while avoiding confusion between a small quantity and a price. It then calls `_quantity()` on the text with the amount removed, so a budget such as “5000 rupees” is not misread as five thousand items. `_category()`, `_condition()`, `_product_ref()`, `_brand()`, and `_exclusions()` map language onto structured fields and controlled vocabulary.

The optional Bedrock extractor performs the same conceptual job with a schema-constrained model response. Its prompt and response schema are deliberately limited to extraction. The money field remains text at this stage; integer conversion happens in deterministic code.

The route passes the extracted result to `ledger.build.build_ledger()`. This is the first important transformation from language into an authorization object.

### 2.1 `build_ledger()` creates a proposal, not blind approval

`build_ledger()` calls `score_extraction()` to produce confidence per constraint. The confidence code looks for evidence in the original wording rather than trusting a model's self-reported confidence. Vague terms such as “decent” or “nothing too pricey”, missing bound words, competing amounts, hedged quantities, and ambiguous multi-item budgets reduce confidence.

`_ceiling_paise()` converts the extracted amount into integer paise using `parse_rupees()`. An explicit per-unit marker causes multiplication by quantity. Without a clear per-unit or total marker, an ambiguous multi-item budget is not guessed.

`meaningful_product_ref()` prevents generic phrases from pinning a mandate to a fictional exact product. “Running shoes” remains a category-level request; a phrase such as “Asics Gel-Contend 9” becomes a product reference.

If the required ceiling or category is missing, `build_ledger()` returns a `LedgerProposal` with `ledger=None` and a question from `_question_for()`. If the fields exist but confidence is weak, it creates the ledger with status `AWAITING_CONFIRMATION` and also returns a question. Otherwise, the ledger is `ACTIVE`.

The resulting `IntentLedger` contains two kinds of constraints:

- `HardConstraints` can block payment: category, maximum total, currency, quantity, condition, product identity, exclusions, recurrence, EMI, and add-ons.
- `SoftPreferences` influence ranking and drift but never block by themselves: brand, colour, and delivery preference.

The route returns the extracted fields, confidence, weak fields, question, and serialized ledger to the browser. At this point no merchant has been contacted and no payment is possible.

## 3. Human confirmation before spending

If extraction is incomplete or ambiguous, `gate.ask_about_mandate()` turns the proposal's question into a persisted `PendingQuestion`. `render_question()` turns it into human-readable text that states what is unclear and confirms that nothing has been charged.

When the user answers, `resolve_mandate()` checks that the answer references the current question. A declined or mismatched answer stops the flow. An approved answer calls `ledger.build.confirm()`, which changes the status to `ACTIVE`, marks `human_confirmed=True`, and restarts the TTL from the answer time. The original confidence remains on the ledger for evidence and calibration; human confirmation does not rewrite history.

`EscalationBook` stores pending questions as JSONL. Its `ask()`, `pending()`, `find()`, and `for_intent()` methods allow a question to survive beyond the original HTTP request.

This branch is important because confirmation is not an authorization override. It resolves an unclear interpretation. A later hard violation still blocks when the offer is re-evaluated.

## 4. Giving the merchant only a bounded view

The next request is `POST /api/negotiate`, handled by `negotiate()` in `api/app.py`. The submitted ledger is parsed again with `IntentLedger.model_validate()`. The server does not trust a browser copy merely because it was produced by an earlier response.

`merchant.projection.project()` constructs a `MerchantView` by explicitly selecting permitted fields. The merchant sees the category, quantity, quantity mode, currency, permitted recurrence/EMI/add-ons, product reference, exclusions, and soft preferences.

The merchant does not see `max_total_paise`, confidence, or `raw_instruction`. This is why projection is an allow-list rather than a copy with a few fields removed: a new sensitive field stays private until deliberately exposed.

## 5. Selecting a catalog product

The merchant catalog is defined as typed `CatalogItem` values in `merchant/catalog.py`. Each item carries a product id, title, category, condition, integer price, brand, colour, and materials.

The catalog lookup begins in `matching(view, dense=...)`:

1. It filters `CATALOG` by the requested category.
2. If a condition is present, it filters by exact condition.
3. If there is no meaningful product reference, it returns the matching category sorted by price.
4. If there is a product reference, it calls `merchant.search.search()`.

`search()` builds searchable documents with `document_for()`. A document combines title, brand, colour, product id, category words, synonyms, and materials. It then produces lexical rankings with `bm25_ranking()` and `trigram_ranking()`.

BM25 is useful for rare product identifiers such as `T480` or `Airdopes`. Character-trigram coverage tolerates spelling, spacing, case, and plural differences. `fuse()` combines the rankings using reciprocal rank fusion, so the two scoring systems do not need an arbitrary shared scale.

A product reference that has no lexical hit is allowed to produce no result. This matters: the merchant must be able to say that it does not stock a named product rather than silently substituting the cheapest item in the category.

If Bedrock credentials are configured, `api._retrieval()` creates a cached `BedrockEmbeddings` instance and a `BedrockReranker`. `BedrockEmbeddings.warm()` embeds catalog documents once per process. `ranking()` embeds the query, compares normalized vectors, applies a minimum similarity floor, and returns candidate positions. The dense arm is fused with BM25 and trigrams, but a dense-only hit is marked ungrounded.

`BedrockReranker.keep()` receives only retrieved candidates and can return only their existing product ids. It cannot invent a product, set a price, or authorize an order. If it fails, retrieval remains available. `MerchantAgent._narrow()` caches reranking per query and candidate shelf so negotiation rounds do not repeat the same model call.

This is retrieval, not authorization. Catalog selection can be wrong or malicious; the final offer still crosses the trusted gate.

## 6. Merchant quote and bounded negotiation

`MerchantAgent.quote()` converts the selected `CatalogItem` into a plain dictionary. It deliberately sends a wire payload instead of constructing an `Offer`, allowing hostile tests to send malformed structures and unknown keys.

The normal quote contains a product, quantity, currency, line items, total, recurring charges, EMI terms, and raw description. Hostility modes can add hidden shipping, subscriptions, paid add-ons, currency changes, quantity inflation, substitutions, total mismatches, unknown fields, excluded materials, or prompt-injection text.

`BuyerAgent.negotiate()` starts with the merchant's quote and obtains the buyer's target from `target_for()`. The target uses integer basis points and is below the user's ceiling. `stated_total()` reads a merchant total only when it is an integer and the payload contains line items; malformed values become an unusable quote instead of crashing the buyer.

The negotiation loop is a bounded `for` loop over `max_rounds`. If the quote reaches the target, it returns `ACCEPTED_AT_TARGET`. Otherwise it calls `MerchantAgent.counter()`, checks whether the concession is meaningful, and stops on malformed or stalled responses. `_settle()` records the final quote and accepts it only if it is within the ceiling. This acceptance is not the final authorization; it only decides which payload is sent to the gate.

The API response includes the merchant view, negotiation rounds, target, ending reason, final offer, retrieval metadata, and whether anything was in stock.

## 7. The untrusted offer crosses the boundary

`POST /api/create-order` is the security-critical route. `CheckoutRequest` contains a ledger, offer, and optional `negotiated_product`; it intentionally has no amount field.

The route validates the ledger, injects a creation time if needed, and calls `gate.receive()` with the raw offer dictionary. It also supplies known catalog product names so the gate can detect a product swap or multi-product description.

`receive()` is the wire boundary. It calls `Offer.model_validate(payload)` and distinguishes two kinds of failure:

- Unknown fields are represented as `UNMODELLED_FIELD` and escalate because they may contain an obligation the schema does not understand.
- Other schema failures become `OFFER_MALFORMED` and block because the system cannot safely judge an unreadable offer.

`unknown_fields()` extracts Pydantic's `extra_forbidden` locations. `_other_problems()` formats all other validation errors. `rejection_violations()` combines both classes of error instead of returning only the first one.

If validation fails, `_refuse()` creates a decision and an audit record anyway. It hashes the raw payload with `payload_hash()` so even a rejected document has an exact identity. It records the merchant's claimed total only as a claim; it does not pretend that the malformed document was evaluated.

If validation succeeds, `receive()` passes the typed `Offer` to `run_gate()`.

## 8. The gate evaluates the offer

`run_gate()` is the trusted orchestration point. It starts timing outside the policy package, calls the deterministic engine, runs semantic analysis, assembles the complete `Decision`, and writes the `AuditRecord` before anything can execute payment.

The first call is `policy.evaluate(ledger, offer, now=now)`. The required timestamp makes the result reproducible and keeps clock access out of `policy/`.

### 8.1 Deterministic checks

`policy.engine.evaluate()` computes `chargeable_total()` and then collects violations from every check. It does not stop at the first failure.

`check_ledger_state()` handles `ACTIVE`, `AWAITING_CONFIRMATION`, `SPENT`, `EXPIRED`, and `EXECUTION_UNCERTAIN`. It computes the deadline from `created_at + ttl_seconds`. A mandate awaiting human confirmation does not age while paused.

`check_mandate_feasibility()` catches contradictory constraints before judging an offer. `check_confidence()` turns weak fields into escalation unless human confirmation has already resolved them.

`check_currency()` requires the offer currency to match INR exactly after normalization. There is no conversion. `check_totals()` verifies that line items add to `total_paise`, rejects negative totals except where discounts are allowed, and compares the effective checked amount to the mandate ceiling.

`chargeable_total()` uses the offer total for ordinary purchases. For EMI, it uses the larger of the declared total and the sum of all installments, so merchant-supplied financing terms cannot make an expensive purchase appear cheap.

`check_quantity()` applies exact, at-most, or at-least semantics. `check_recurrence()` blocks future obligations unless recurrence was authorized, including a zero-cost trial that later converts. `check_emi()` independently checks whether financing was authorized. `check_addons()` checks add-on cost; recurrence and distinct-product concerns remain separate checks.

`check_condition()` and `check_category()` normalize merchant strings into controlled enums. A mismatch blocks; an unknown value escalates because the system cannot confidently judge it. `check_product_identity()` compares a meaningful product reference exactly, without an embedding threshold. `check_exclusions()` searches product and line-item text for ruled-out terms while accounting for negated forms.

`outcome_for()` maps the collected violations to the three outcomes. `PolicyResult` validates that `ALLOW` has no violations and that `BLOCK` or `ESCALATE` explains itself.

### 8.2 Semantic checks

After deterministic checks, `run_gate()` calls `score_drift()` and `assess_substitution()`.

`score_drift()` compares soft preferences such as brand, colour, and delivery speed. Drift is evidence for review, not a hard authorization rule.

`assess_substitution()` compares the product named at negotiation start with the final product. `product_match_score()` uses asymmetric token coverage so extra descriptive words do not penalize a genuine match. Added identifiers containing digits reduce the score because model numbers, capacities, and tiers often identify different products. `names_another_product()` checks the rest of the merchant shelf for a distinct product named in the final description.

A similarity signal can only create an escalation. It cannot create a block by itself. This keeps probabilistic retrieval and semantic matching away from the final money decision.

`escalation_question()` assembles a question from deterministic violation explanations. It does not ask a model to invent a reason or choose an outcome.

## 9. Audit is written before payment

`run_gate()` creates an `AuditRecord` containing the intent id, offer id, canonical mandate hash, canonical offer hash, decision, violations, checked amount, ceiling, latency, engine version, timestamp, and human-confirmation flag.

`content_hash()` serializes typed models using `canonical_json()`: sorted keys, compact separators, UTF-8, and no insignificant whitespace. `offer_hash()` hashes the entire offer, including raw merchant description, because the description is part of the evidence.

If an `AuditLog` is supplied, `append()` reads the current `head()`, assigns the next sequence number, stores the previous hash, and appends one JSON line. The first record links to `GENESIS`. `verify_chain()` recomputes each record's hash and reports the first broken sequence.

`issue_receipt()` creates a `ComplianceReceipt` only for `ALLOW`. The receipt names the exact mandate and offer hashes, authorized amount, checks performed, and engine version. It is the merchant's later evidence that a particular cart was evaluated before payment.

## 10. Branch: BLOCK

When the decision is `BLOCK`, the API returns HTTP 409 with the decision and all violation explanations. It sets `razorpay_called` to `false`.

No rollback is needed because the payment rail was never reached. This behavior is enforced in tests with `RefusingClient`, whose methods raise if a blocked path attempts to call Razorpay.

## 11. Branch: ESCALATE

When the decision is `ESCALATE`, the API also returns HTTP 409, but includes `escalation_question`. `gate.ask_about_offer()` creates a `PendingQuestion` linked to the specific intent and offer, then `pause()` changes the ledger to `AWAITING_CONFIRMATION` so its TTL stops.

`resolve_offer()` checks the question id and the user's answer. A rejection ends without payment. An approval calls `confirm()` if the mandate was paused, then calls `receive()` again with `human_confirmed=True`.

The offer is therefore revalidated from scratch. If the re-check finds a hard violation, the result remains blocked even though a human approved the previous uncertainty. If the re-check passes, the escalation is converted to `ALLOW` and the audit record records human confirmation.

## 12. Branch: ALLOW and Razorpay execution

Only an `ALLOW` reaches `payments.execute()`.

`execute()` takes the amount from `AuditRecord.checked_total_paise`, never from the HTTP request or merchant payload. It first checks that the decision record belongs to the same intent, that the mandate is still `ACTIVE`, and that the amount meets Razorpay's minimum.

`receipt_for()` derives a stable short receipt from the intent id and offer hash. The same intent and exact offer therefore reuse the same payment identity during reconciliation; a changed cart gets a different identity.

Before the network request, `execute()` appends an execution record when an audit log is available. It then calls `RazorpayClient.create_order()` through `HttpRazorpayClient`, which uses HTTPS, Basic authentication, integer paise, INR, receipt, and audit-related notes.

A successful response with an order id changes the returned ledger to `SPENT` and returns `PaymentAttempt(PLACED)`. The original frozen ledger is not mutated.

A normal Razorpay refusal returns `REFUSED`. A timeout is different: the request may have reached Razorpay, so `execute()` returns `UNCERTAIN` and changes the ledger to `EXECUTION_UNCERTAIN`. It never blindly retries.

`reconcile()` repeats the same receipt, obtains the existing order identity, fetches its payments, and marks the ledger `SPENT` only when a payment is captured or authorized. If no payment settled, the ledger can return to `ACTIVE`.

The API then returns HTTP 504 for an uncertain execution so the caller knows reconciliation is required instead of treating the transaction as safely failed.

Finally, `POST /api/verify-payment` calls `signature_matches()`. The function computes HMAC-SHA256 over `order_id|payment_id` with the server-side secret and compares signatures with `hmac.compare_digest()`. A mismatch returns HTTP 400 and does not mark the payment verified.

## 13. Reading and verifying audit evidence later

The audit package provides two different kinds of verification.

`verify_trail()` asks whether the complete append-only chain is intact and returns record counts grouped by decision. `find()` retrieves records by intent id, offer id, or offer hash for investigation.

`verify_receipt()` is independent of the issuer's process. It re-hashes the supplied `Offer` and optional `IntentLedger`, compares those hashes to the receipt, confirms the receipt says `ALLOW`, and confirms that constraints were named. A changed cart, changed mandate, non-authorization, or empty constraint list invalidates the receipt.

`inspect.py` contains the human-facing renderers: `render_decision()`, `render_record()`, `render_receipt()`, and `render_trail()`. These do not make decisions; they turn already-created evidence into readable output.

## 14. Benchmark and evidence flow

The benchmark path starts in `bench/generator.py`, which creates cases from the written scenario categories without importing the policy implementation. This keeps the data generator from labeling cases using the detector it is supposed to measure.

`bench.harness.run_case()` reconstructs an `IntentLedger`, fixes the benchmark epoch, sends the offer through `gate.receive()`, and records the expected outcome, actual outcome, amount, latency, and violations as an `Observation`.

`run()` applies that path to a case set. `report_for()` sends observations to `metrics.build_report()`.

`build_report()` keeps the three outcomes separate and computes:

- legitimate authorization completion;
- false blocks and the value wrongly blocked;
- unauthorized passes and exposure prevented or leaked;
- per-class precision, recall, F1, and confusion matrix;
- escalation rate over decidable cases and escalation recall;
- p50, p95, p99, and maximum latency;
- counts by violation code; and
- deterministic explanation-quality proxies.

`injection_experiment()` creates or reads paired cases where hostile text is added only to `raw_description`. It reruns both cases and reports changed decisions. Because the current policy path does not read that description, this is a structural transport test, not a claim that a model resisted prompt injection.

`bench.export` runs scenario demonstrations and exports dashboard data. `bench.dashboard` places the generated data into the HTML dashboard template. These modules visualize and measure the same runtime path; they do not create a second authorization implementation.

## 15. The whole flow in one sentence

`api.app` extracts a typed proposal, `ledger.build` decides whether it is sufficiently clear to activate, `merchant` retrieves and negotiates a catalog offer without seeing the ceiling, `gate.boundary.receive` validates the untrusted document, `policy.engine.evaluate` checks every hard constraint, `semantic` adds only advisory uncertainty, `audit` records the exact decision, and `payments.executor.execute` can reach Razorpay only when that recorded decision is `ALLOW`.
