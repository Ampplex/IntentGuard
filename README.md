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
  core/            schemas, money helpers, the frozen violation codes. No logic.
  policy/          the deterministic engine. Imports core/ and nothing else.
data/gold/
  author.py        hand-authored cases. Cannot import intentguard, and a test enforces it.
  cases.json       the 100 labelled cases
  REVIEW.md        the same cases rendered for review by eye
tests/
  core/            schemas, money, hashing, the no-float invariant
  policy/          one test per violation code the engine can raise
  gold/            the gold set is well formed and internally consistent
  structure/       the import graph and clock gates
```

## Running it

```
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
.venv/bin/python -m pytest          # 597 tests
.venv/bin/python -m ruff check .
.venv/bin/python data/gold/author.py    # regenerate the gold artifacts
```

## Status

Stages 1 to 3 of 12 complete. See the build order table in CLAUDE.md.

| Stage | Gate | State |
|---|---|---|
| 1. `core/` schemas and money | Round-trip tests, no float in the money path | passing |
| 2. `policy/` engine | Import graph gate, a test per violation code | passing |
| 3. Gold set, 100 hand-labelled | Exists, labelled without running the engine | passing |

The gold labels are held out. Nothing is tuned against them and they have not
been scored. Thresholds get derived from the synthetic set at stage 9.
