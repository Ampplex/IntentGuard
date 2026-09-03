# SPEC-DECISIONS.md

Amendment to CLAUDE.md, resolving the session 0 review. Where this contradicts CLAUDE.md, this wins. Commit both.

---

## Corrections to CLAUDE.md, made by me not you

Three of these came out of the review and are genuine errors in the original doc.

**Audit is not stage 10.** It's a cross-cutting requirement from stage 2 onward. Every decision writes a record from the first moment a decision exists. Stage 10 shrinks to *presentation* — the compliance receipt and the readable rendering. The review is right that "show the audit trail and one failure handled gracefully" is the literal bar and both sat near the end of a twelve-stage plan. Fixed.

**The AP2 claim was too broad.** Corrected wording below.

**Escalation rate as written was nearly meaningless.** Corrected below.

---

## Blocking answers — stage 1 can proceed on these

**IntentLedger lives in `core/`.** Confirmed. `ledger/` owns extraction, confidence, persistence and TTL enforcement — the machinery, not the type. It being thinner than the layout implies is fine.

**Clock is injected.** `now: datetime` is a required parameter on the policy entrypoint. The engine never calls `datetime.now()`. Good catch and it would have been painful at stage 7.

**Discounts are negative line items.** `kind: discount` may carry a negative `amount_paise`. No other kind may. Two invariants: only discount can be negative, and the sum cannot be below zero (`NEGATIVE_TOTAL`).

**Quantity gets a mode enum.** `exact | at_most | at_least`, extractor records which, default `exact`.

**`total_paise` is what gets charged now.** Recurring obligations are not in `line_items` and not in `total_paise` — they live only in the `recurring` list. This makes the ₹0-trial trap cleaner rather than subtler: the total looks legitimate, the recurring list is non-empty, `recurring_allowed` is false, block. That's the demo.

**Paise stays, and INR-only is a deliberate scope decision.** The system is single-currency. `currency` exists so a non-INR quote is an instant BLOCK rather than a silent conversion. Renaming to `minor_units` would imply multi-currency support that isn't being built, and implied generality you don't have is worse than a stated limitation. Say it plainly in the README.

**Violation codes freeze at stage 1.** The review is right that the gate is self-referential otherwise. The list:

```
TOTAL_EXCEEDS_MAX          TOTAL_MISMATCH
NEGATIVE_TOTAL             CURRENCY_MISMATCH
QUANTITY_MISMATCH          RECURRING_NOT_AUTHORIZED
EMI_NOT_AUTHORIZED         ADDON_NOT_AUTHORIZED
CONDITION_MISMATCH         CATEGORY_MISMATCH
PRODUCT_SUBSTITUTION       LEDGER_EXPIRED
LEDGER_ALREADY_SPENT       UNMODELLED_FIELD      (escalates)
LOW_CONFIDENCE             (escalates)
UNCLASSIFIABLE_CONDITION   (escalates)
```

Adding one after stage 1 requires an explicit amendment to this file. Don't add quietly.

**Hypothesis: approved,** money module only.

---

## EMI

`emi_allowed` is not redundant with `recurring_allowed`. The distinction is what you're getting for the money.

**Recurrence** is a new ongoing obligation for additional goods or services — a subscription, a protection plan. You keep paying and you keep receiving something.

**EMI** is a financing decomposition of a single purchase. Same goods, payment split over time. Nothing new is being bought.

Different economic events, different user consent, both stay.

**The checked total for a financed offer is the sum of all installments.** ₹50,000 financed at ₹4,500 × 12 is ₹54,000 against `max_total_paise`, because the authorization is about money leaving the user's account, not sticker price. If `emi_allowed` is false it blocks on EMI regardless — and per the report-all rule, if the installment total also exceeds the ceiling, report both violations.

---

## Category

Your instinct is right, and it's better than a compromise.

`policy/` does exact match against a controlled category enum. Anything outside the enum is ESCALATE. Product-level similarity lives entirely in `semantic/` as substitution.

This isn't a workaround for the import constraint — it's how catalogs actually work. Real commerce runs on controlled taxonomies, and an agent-readable catalog is one of the track's own example directions. The enum is the merchant's taxonomy. "Sneakers under shoes" is a taxonomy question with a right answer, not a semantic judgment.

It does push work onto the extractor, which is correct: mapping loose human language onto a controlled vocabulary is exactly the extractor's job, and low confidence there escalates like anything else.

---

## Drift

**Drift never blocks. High drift plus low confidence escalates.**

Your guess was right. Soft preferences are not decorative — they rank offers that already passed the hard checks, and they feed the escalation signal. But no drift threshold alone changes an outcome, because a probabilistic score gating a payment is the thing this project exists to argue against.

---

## Metrics corrections

**Escalation rate is computed only over cases whose gold label is ALLOW or BLOCK.** You're right that the synthetic set has a structural escalation floor of roughly 13% before any extractor weakness exists, which made the 15% threshold meaningless. Cases where ESCALATE is the correct label get reported separately as escalation recall — a different and also useful number.

**Gold does not get split. It gets tuned on never.**

The review's fix was 60/40 within gold, and it correctly flagged that 40 cases is thin evidence. Better answer: tune everything on the synthetic set and hold all 100 gold cases untouched until the final run. Synthetic is your train set — the generator is blind to `policy/`, so tuning against it is legitimate — and gold is your test set. That's the standard setup, it gives you volume for threshold derivation, and gold stays clean evidence you can defend without qualification.

The 20% holdout was ambiguous in the original doc. It's a holdout of the synthetic set. Gold is 100% held out by definition.

**The injection test needs a control run.** Approved and important. Temperature 0, cached extraction, plus a control pass — same benchmark twice, no injections — establishing that the baseline decision-change rate is zero. Without that control the headline result is dismissible as sampling variance, and a skeptical judge will say so.

---

## AP2, precisely

Rewrite the "What this is" paragraph to scope the claim to one flow. The unqualified version is wrong and would not survive a panel that knows the protocol.

The accurate version:

> AP2 defines three mandates — Intent, Cart and Payment. In the human-present flow, the user cryptographically signs the Cart Mandate, so the exact cart carries the user's signature and there is no gap. In the **human-not-present** flow, the user signs a detailed Intent Mandate upfront and the agent then generates the Cart Mandate algorithmically once conditions are met, with the Intent Mandate's signature providing the binding authorization. AP2 specifies the credential and the chain of custody. It does not specify who evaluates whether the cart actually satisfies the mandate's constraints, or what happens on partial compliance. IntentGuard is that evaluator.

Delegated, human-not-present commerce is the whole point of agentic checkout, so scoping the claim costs nothing and makes it defensible.

---

## Remaining items — rulings, briefly

**Mandate is single-use.** One ALLOW consumes it, status goes SPENT. Multi-order fulfilment is noted as future work. Keeps the state machine trivial and the idempotency key still matters for the timeout path.

**No Razorpay call on ESCALATE either.** Extending the invariant — you were right that leaving it unstated is the kind of gap a hostile path finds. The rule is: the payment rail is reached only on ALLOW.

**TTL pauses during escalation.** A human being slow must not produce `LEDGER_EXPIRED` on a transaction they were mid-approval of. Resolution amends the ledger with a fresh TTL, and the receipt records `human_confirmed: true` as a distinct evidence class.

**Buyer agent sees the ceiling.** It's the user's agent. The behavioural leak you identified is real — accepting instantly at exactly ₹X reveals the line across repeated rounds — and the mitigation is that the buyer negotiates toward a target below the ceiling rather than accepting at it. Note it as a known limitation in the README. Don't spend deadline hours solving it.

**Lower price alone: log as drift, never block.** You're right that a 60% discount on an identical item is a counterfeit signal in real commerce. It's also fraud detection, which is explicitly Track 02 and explicitly out of scope. Record it, don't act on it.

**Pydantic forbids extra fields.** Approved — that converts unmodelled-field detection into a parser setting for anything arriving as structured JSON. You're right it doesn't help for obligations buried in prose, which stays the harder half and stays open.

**Confidence scoring: your hybrid is approved.** Rules-based penalties for known-vague phrasings on the default path, multi-sample agreement only for fields the rules flag. Latency story survives. Validate whatever comes out against synthetic, not gold, and move the 0.85 threshold if the data disagrees with it — that number was invented and should be treated as such.

---

## Stage 1 plan

Approved as written, including all three deviations. `hashing.py` at stage 1 is the right call for the reason given — audit records written before canonicalization exists are unverifiable. Building the import walker a stage early is worth the hour.

Proceed.

---

# Amendment 1 — stage 1 close

Written by Claude at the end of stage 1, resolving the items flagged in the
stage 1 report. Everything here is reversible; it is recorded rather than
assumed so that a later stage cannot be built on a silent interpretation.

## Confidence attaches as a parallel map, not a wrapper

`HardConstraints` holds plain ints, strings and enums. `IntentLedger.confidence`
is a validated `dict[str, float]` whose keys must name real constraint fields.

The reason is structural rather than cosmetic. With a parallel map, `policy/`
compares nothing but integers and enums, so a probabilistic number is incapable
of reaching a money comparison — not by convention, but because the type it
would have to travel in is not there. `ConfidenceField` remains in `core/` for
the extractor's own use at stage 4.

## Per-unit ceilings

`max_total_paise` is always the order total. The question was what the extractor
does with a per-unit phrasing, and the ruling is:

- An explicit per-unit marker ("each", "per pair", "apiece") means multiply by
  quantity. "3 shirts under ₹2000 each" becomes a ceiling of ₹6000.
- No marker means order total. "3 shirts for under ₹2000" becomes ₹2000.
- A phrasing that carries a quantity and a budget with no marker either way
  ("get me 3 shirts, budget 2000") is ESCALATE. It is genuinely ambiguous to a
  human reader, and guessing it wrong either blocks a legitimate order or
  authorizes triple what the user meant.

This is a labelling convention as much as a code rule, so it is settled before
the gold set exists rather than during it.

## Three violation codes added — the list is now nineteen

Each of these existed as an outcome the specification requires but had no code
to express. Adding them is what the freeze rule asks for: an explicit amendment,
not a quiet addition. A list that keeps growing during implementation would
itself be a signal that the semantics were underspecified, so it is worth
noting that these are the only three, and that all three are about states the
engine can reach rather than new kinds of violation.

**`OFFER_MALFORMED`** (blocks). The offer models forbid extra fields, so an
unknown key raises a validation error carrying `extra_forbidden`, which the gate
translates into `UNMODELLED_FIELD` and escalates. A validation failure for any
other reason had nothing to express it. It blocks rather than escalates: a human
cannot usefully adjudicate an order that could not be read, and refusing it is
safe.

**`UNCLASSIFIABLE_CATEGORY`** (escalates). The category ruling says anything
outside the controlled enum escalates, but only condition had a code for it.
Overloading `UNMODELLED_FIELD` would have worked and been slightly dishonest —
the field is modelled, the value is unrecognised. This mirrors
`UNCLASSIFIABLE_CONDITION` exactly.

**`LEDGER_NOT_CONFIRMED`** (escalates). A mandate in `AWAITING_CONFIRMATION` has
not been authorized by the user yet. `SPENT` and `EXPIRED` each had a code and
this state did not, which would have left the engine either silently allowing an
unconfirmed mandate or blocking with a code that means something else.

`EXECUTION_UNCERTAIN` deliberately does **not** get a code. It maps to
`LEDGER_ALREADY_SPENT`, because in both states a payment attempt has consumed
the authorization and the correct behaviour is identical. Flagging it as an
interpretation rather than a reading.

## The Decision coherence validator stays

`Decision` refuses to be constructed as an ALLOW carrying violations, or as a
BLOCK or ESCALATE carrying none. This is logic in a package specified as having
none, and it stays, because the alternative is an audit trail that can contain a
record asserting two contradictory things at once. It validates the shape of a
record rather than deciding anything, which is the distinction that matters.
