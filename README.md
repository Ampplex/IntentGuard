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

**Test mode only, enforced rather than intended.** A Razorpay key that does not
begin with `rzp_test_` is refused when the client is constructed, and a test
scans the whole repository for a committed live key. Endpoints and field names
were read from Razorpay's live documentation, not recalled; no idempotency
header is sent because none is documented, and idempotency rests on `receipt`,
which Razorpay documents as serving that purpose.

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
  payments/   Razorpay adapter, idempotency, the uncertain-execution path.
  bench/      generator (imports nothing from intentguard), harness, export, dashboard.
  gate/       orchestration, the wire boundary, escalation, timing, audit write.
  audit/      the tamper-evident trail, plus rendering and receipt verification.
  metrics/    measurement. Cannot import policy/, does no file I/O.
dashboard/
  template.html   the page, with one placeholder for a real run
data/
  gold/       100 hand-labelled cases, held out. Cannot import intentguard.
  dev/        60-case confidence set and 30-pair substitution set. Same import ban.
  synthetic/  1,884 generated cases, a fifth of every kind and label held out.
tests/
  core/       schemas, money, hashing, the no-float invariant
  policy/     one test per violation code, the threat table, regressions
  ledger/     extraction, calibration, injection reaching the extractor
  merchant/   the bounded-view gate, hostile quotes over the wire
  buyer/      termination under adversarial merchants
  semantic/   substitution calibration, drift weights, mid-negotiation swaps
  payments/   no call on a block, the timeout path, test-mode enforcement
  bench/      generator independence, holdout stability, injection twins
  gate/       decision assembly, the boundary, receipts
  escalation/ pause, ask, resume, and what a human answer may and may not do
  audit/      chain integrity, tamper detection, receipt verification, rendering
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
PYTHONPATH=src .venv/bin/python -m intentguard.bench.generator   # regenerate the benchmark
PYTHONPATH=src .venv/bin/python -m intentguard.bench.harness     # report the training slice
PYTHONPATH=src .venv/bin/python -m intentguard.bench.export      # run everything, write data/dashboard.json
PYTHONPATH=src .venv/bin/python -m intentguard.bench.dashboard \
    dashboard/template.html dashboard/index.html               # build the page from that run
```

## Status

All twelve stages complete. See the build order table in CLAUDE.md.

| Stage | Gate | State |
|---|---|---|
| 1. `core/` schemas and money | Round-trip tests, no float in the money path | passing |
| 2. `policy/` engine | Import graph gate, a test per violation code | passing |
| 3. Gold set, 100 hand-labelled | Exists, labelled without running the engine | passing |
| 4. `ledger/` extraction and confidence | Confidence correlates with correctness | passing |
| 5. `merchant/` and bounded view | No ceiling in the serialised merchant view | passing |
| 6. `buyer/` and negotiation | Terminates, always | passing |
| 7. `semantic/` substitution and drift | Substitution cases classified correctly | passing |
| 8. `payments/` and idempotency | No call on BLOCK; timeout path tested | passing |
| 9. `bench/` generator and harness | Generator import test passes; full run reports | passing |
| 10. Compliance receipt and audit rendering | Every decision inspectable | passing |
| 11. Escalation end to end | Ambiguous instruction pauses, asks, resumes | passing |
| 12. Dashboard | Renders a real run, not fixtures | passing |

Audit and metrics are built rather than deferred, because the track's bar asks
to see an audit trail and a graceful failure, and both sat near the end of the
original plan.

Extraction runs without an API key: the rule-based extractor is a real fallback,
not a mock. Set `ANTHROPIC_API_KEY` and install the `llm` extra to use the
model-backed path, which is wired but untested against a live model.

## Reading the benchmark honestly

The engine scores 100 percent on the synthetic training slice, including on the
225 boundary cases that sit exactly on a ceiling, one paisa over it, or at a
quantity mode's edge. **That number is not evidence that the system is correct.**
It means the engine and the generator read the specification the same way, which
is what CLAUDE.md predicts when one repository writes both.

Four mitigations, all structural rather than promised.

The generator imports nothing from `intentguard` at all, enforced by a test.

Every violation kind is paired with a compliant offer of the same shape, so the
set measures discrimination rather than the shape of a payload. Without those,
thirteen of eighteen kinds carried a single label and "block anything with a
shipping line" would have scored perfectly on hidden costs. The set is now
roughly half allowed and half blocked.

A fifth of every kind and label is held out, stratified rather than hashed per
case. Hashing was uniform overall and still left the holdout nine points off the
training slice on label mix; the splits now agree to within a fifth of a point.

And the hand-labelled gold set has never been scored, with nothing ever tuned
against it.

Gold and synthetic are always reported separately. There is deliberately no
function that merges two reports, and a test asserts there is not: they are
different kinds of claim, and averaging them describes neither.

The injection result is reported as what it currently is. Nothing reads
`raw_description`, so zero changed decisions across 129 twin pairs is a fact
about transport, not about a model resisting persuasion. It becomes evidence
about a model when a model reads that field.
