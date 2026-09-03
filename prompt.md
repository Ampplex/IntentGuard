# Prompts for Claude Code

Copy-paste, one at a time. Keep this open next to the terminal.

The thing that breaks builds like this is a single "build IntentGuard" prompt. You get twelve modules that look finished and die on stage. Every prompt below is scoped to one stage with one gate.

---

## Session 0 — orient, no code

Run this first. Do not let it write anything yet.

```
Read CLAUDE.md in full before doing anything else.

Don't write any code this session. I want three things:

1. Tell me back what this project is and why it exists, in your own
   words. If your version doesn't match the doc, we have a problem
   worth finding now.

2. List every place the spec is ambiguous, contradictory, or silent
   on something you'd need to decide. Include the open problems
   section, but I especially want the ones I haven't noticed.

3. Propose your plan for stage 1 only — files, schemas, tests.
   Nothing beyond stage 1.

Ask me questions. I'd rather answer five now than find out in stage 4
that you guessed.
```

If it starts writing code anyway, stop it and re-run. That behaviour won't improve later.

---

## Stage 1 — core schemas

```
Stage 1 only. Build src/core/: schemas, money helpers, violation codes.

Gate: round-trip tests pass, and no float appears anywhere in the
money path including fixtures. Write a test that greps for float
usage in money fields if that's the cleanest way to enforce it.

Don't build the policy engine. Don't scaffold other modules.

When you're done, tell me anything you're unsure about.
```

---

## Stage 2 — policy engine

The one that matters most. It's the whole thesis in one module.

```
Stage 2: src/policy/. The deterministic engine.

Read the "Fixed: decision semantics" section again before you start.
Write tests first — one per violation code, including the ₹0-trial
recurrence trap and the free-shipping-passes case.

Gate: a test that walks the import graph and fails if policy/ imports
semantic/, ledger/, or any model client.

Constraints: no model calls in this package at all. Report every
violation, not the first.

Flag any decision rule you had to interpret rather than read.
```

---

## Stage 3 — gold set

This one is unusual and worth doing carefully.

```
Stage 3: the gold set. 100 hand-labelled cases in data/gold/.

Important: label these from the decision semantics written in
CLAUDE.md, not by running the policy engine. The prose spec is the
ground truth here. If a case is genuinely ambiguous under the prose,
that's a finding — mark it and tell me, don't resolve it silently.

Cover every category including ambiguous-intent and unmodelled-field
cases where ESCALATE is the correct answer.

Output a format I can review by eye. I'm going to spot-check these.
```

Spot-check at least twenty yourself. Labels produced by the same family of model that wrote the detector aren't fully independent, and you want to be able to say honestly that you reviewed them.

---

## Stage 4 — extraction and confidence

```
Stage 4: src/ledger/. Extraction, confidence scoring, persistence, TTL.

Confidence scoring is an open problem in CLAUDE.md. Pick an approach,
implement it, then check whether your confidence numbers actually
correlate with correctness on the gold set. Show me that check.

If the 0.85 threshold turns out to be wrong given real data, change it
and tell me what the data said. That number was invented.
```

---

## Stages 5–12 — template

Swap in the stage and gate from the table.

```
Stage N: <name>.

Gate: <gate from the CLAUDE.md table>.

Stay inside this stage. If you need something from a later stage,
stub it and tell me rather than building ahead.

When done: what you built, what you're confident in, what you're not.
```

---

## Starting a fresh session

Context resets. Use this rather than assuming it remembers.

```
Read CLAUDE.md, then look at what's already built and the git log.

Tell me which stages are complete, which gates are passing, and where
you think we are. Don't start work until I confirm.
```

---

## When something's wrong

```
Stop adding code. Explain what's actually happening and why, before
proposing a fix.

If the root cause is a rule in CLAUDE.md that doesn't survive contact
with a real case, say that. The doc is a hypothesis and I'd rather
change it than work around it.
```

Two patterns to watch for: fixing symptoms one at a time without naming a cause, and quietly loosening a test to make it pass. Both mean stop and re-scope.

---

## Before submitting

```
Read CLAUDE.md again, then audit the repo against it.

For each invariant in the "Fixed" section, show me the test or the
code that enforces it. If any is unenforced, say so plainly.

Then: what in this repo would you attack if you were trying to break
the central claim, and what's the weakest thing we're shipping?
```

That last question is the one to run before the pitch video. Whatever it says is what a panel will find.

---

## Things not to say

**"Build IntentGuard."** You'll get all twelve stages half-done.

**"Make the tests pass."** Invites loosening tests. Say "find why this fails."

**"Just get it working, we'll clean it up."** Deadline is tomorrow. There is no later.

**"Skip the gold set for now, we can add it after."** The gold set is worthless once the policy engine exists — its whole value is being independent of it. It's stage 3 for a reason.

---

## One note on pace

If time runs short, stages 1, 2, 3 and 8 give you a real submission: a working deterministic gate, honest metrics on hand-labelled data, and a Razorpay integration that provably doesn't fire on a block.

A demo of those four, with an honest account of what isn't built yet, beats twelve half-finished modules. Their bar asks for one failure handled gracefully — it doesn't ask for everything.
