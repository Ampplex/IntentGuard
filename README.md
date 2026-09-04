# IntentGuard

The authorization layer that lets a Razorpay merchant safely accept an order from an AI buyer.

Built for the Razorpay AI Buildathon, Track 01.

Verifying a signature proves the user authorized *something*. It does not prove *this cart*
is that something. IntentGuard is the deterministic check that sits between a signed AP2
Intent Mandate and the payment rail, and answers ALLOW / BLOCK / ESCALATE before any money
moves.

An LLM never produces a decision here. Models extract structured fields; a deterministic
engine decides on integers.

See [CLAUDE.md](CLAUDE.md) for the full specification and
[SPEC-DECISIONS.md](SPEC-DECISIONS.md) for the amendments that win on contradiction.

## Stated limitations

These are deliberate scope decisions, not oversights.

**Single-currency, INR only.** Every amount in this system is integer paise. The `currency`
field exists so that a non-INR quote is an immediate BLOCK, never a silent conversion. The
money helpers are not written for multi-currency and the field names say so. Implied
generality you do not have is worse than a stated limitation.

**The buyer agent sees the spending ceiling; the merchant never does.** The buyer agent acts
for the user, so it is trusted with `max_total_paise`. This leaks the ceiling behaviourally
across repeated negotiation rounds — a merchant watching the buyer accept instantly at
exactly the ceiling can infer where the line is. The mitigation is that the buyer negotiates
toward a target strictly below the ceiling rather than accepting at it. This is a known
limitation, not a solved problem.

**A mandate is single-use.** One ALLOW consumes it and the ledger moves to SPENT. Multi-order
fulfilment against a single mandate is future work.

**Fraud detection is out of scope.** An implausibly low price on an identical item is recorded
as drift and never acted on. That is Track 02's problem.

## Layout

```
src/intentguard/
  core/       schemas, money helpers, the twenty-one violation codes. No logic.
  policy/     the deterministic engine. Imports core/ and nothing else.
  ledger/     extraction, confidence scoring, mandate building.
  merchant/   untrusted: catalog, bounded view, quoting, hostile modes.
  buyer/      the user's agent: negotiation, bounded and always terminating.
  semantic/   substitution and drift. Advisory to an escalation, never a block.
  gate/       orchestration, the untrusted wire boundary, timing, audit write.
  audit/      the tamper-evident decision trail.
  metrics/    measurement. Cannot import policy/, does no file I/O.
data/
  gold/       100 hand-labelled cases, held out. Cannot import intentguard.
  dev/        60-case confidence set and 24-pair substitution set. Same import ban.
tests/
  core/       schemas, money, hashing, the no-float invariant
  policy/     one test per violation code, the threat table, regressions
  ledger/     extraction, calibration, injection reaching the extractor
  merchant/   the bounded-view gate, hostile quotes over the wire
  buyer/      termination under adversarial merchants
  semantic/   substitution calibration, drift weights, mid-negotiation swaps
  gate/       decision assembly, the boundary, receipts
  audit/      chain integrity and tamper detection
  metrics/    checked against hand-computed answers
  gold/       the gold set is well formed and internally consistent
  structure/  import graph, clock reads, orphan codes, dataset independence
```

## Running it

```
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
.venv/bin/python -m pytest          # the full suite
.venv/bin/python -m ruff check .
.venv/bin/python data/gold/author.py    # regenerate the gold artifacts
.venv/bin/python data/dev/author.py     # regenerate the confidence set
.venv/bin/python data/dev/substitutions.py  # regenerate the substitution set
```

## Status

Stages 1 to 7 of 12 complete. See the build order table in CLAUDE.md.

| Stage | Gate | State |
|---|---|---|
| 1. `core/` schemas and money | Round-trip tests, no float in the money path | passing |
| 2. `policy/` engine | Import graph gate, a test per violation code | passing |
| 3. Gold set, 100 hand-labelled | Exists, labelled without running the engine | passing |
| 4. `ledger/` extraction and confidence | Confidence correlates with correctness | passing |
| 5. `merchant/` and bounded view | No ceiling in the serialised merchant view | passing |
| 6. `buyer/` and negotiation | Terminates, always | passing |
| 7. `semantic/` substitution and drift | Substitution cases classified correctly | passing |

Audit and metrics are built rather than deferred, because the track's bar asks
to see an audit trail and a graceful failure, and both sat near the end of the
original plan.

Extraction runs without an API key: the rule-based extractor is a real fallback,
not a mock. Set `ANTHROPIC_API_KEY` and install the `llm` extra to use the
model-backed path, which is wired but untested against a live model.

The gold labels are held out. Nothing is tuned against them and they have not
been scored. Thresholds get derived from the synthetic set at stage 9.
