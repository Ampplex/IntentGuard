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

---

# Amendment 2 — review of stages 1 to 3

Written by Claude after re-reading the engine adversarially rather than
running it. Three defects, one of them severe, plus two gaps that are not
defects but should not be discovered by a judge first.

## The rule that found them

Every check was read with one question: *which values does an untrusted party
control, and does any of them decide **which** number gets checked, rather than
supplying a number that gets checked?*

Untrusted input may raise the figure under scrutiny. It may never choose it.
Supplying a value to a comparison is safe because the comparison still happens.
Selecting which value is compared is not, because the ceiling is then enforced
against a number the attacker picked.

## Defect 1: instalment terms could lower the checked total (severe)

`chargeable_total` replaced the offer total with the sum of instalments whenever
an offer carried EMI terms. Both inputs come from the merchant.

A merchant facing a mandate with `emi_allowed: true` could therefore attach one
instalment of one paisa to a ninety thousand rupee cart. The ceiling check
compared five thousand rupees against one paisa and returned ALLOW. The invariant
that a payment over the ceiling never reaches the rail was fully defeated, and no
existing test caught it because every EMI test used terms where the instalment
sum was the larger number.

Fixed by taking the maximum of the two rather than substituting one for the
other. Interest still raises the checked figure, which was the point of the
original rule; nothing can now lower it. `check_totals` also takes the figure as
an argument instead of recomputing it, so the number the engine reports and the
number it checks cannot drift apart.

## Defect 2: a mandate could be denominated in a foreign currency

`HardConstraints.currency` was an unvalidated string defaulting to INR. The
system is single-currency by decision, and nothing enforced it. A mandate built
with USD would have made a USD offer pass the currency check, which is the one
check the specification calls an immediate block.

Now validated on parse: case is normalised, anything but INR is refused with a
message saying why the field exists. Note the honest boundary — pydantic
validators run on `model_validate`, which is how untrusted data enters, and not
on `model_copy`, which is internal construction. The invariant holds where
attacker-controlled data crosses the line, which is the place that matters.

## Defect 3: explanations could contain the word None

`explain` filled unsupplied placeholders with `None` and rendered it verbatim
into the sentence a person reads while deciding whether they are about to lose
money. A half-written explanation is worse than a missing one because it looks
finished.

`explain` now refuses to render a template it was not given every value for.
Adding that guard immediately surfaced a second live instance: a mandate already
marked EXPIRED produced "Your authorization expired at None and this offer
arrived at None." Both are fixed, and the guard is what found the second one.

## Gap 1: the injection experiment is currently vacuous

The planned headline is that running the benchmark with injections spliced into
every description changes no decision. Today that result would be true by
construction and worth nothing: `raw_description` is never read by anything.
The engine decides on integers and enums, and no model is in the path at all.

The claim only becomes evidence when injections are spliced into text that
actually reaches a model — the user instruction the extractor parses at stage 4,
and the product text the substitution matcher reads at stage 7. Until then the
correct statement is the structural one: the description cannot move a decision
because nothing reads it. That is a real property and it should be stated as
such, not dressed up as an experimental result.

## Gap 2: category is merchant-asserted and trivially spoofable

`check_category` compares the mandate's category against a string the untrusted
merchant supplies. A merchant selling a bluetooth speaker can simply write
"footwear" and pass. The check catches honest mistakes and lazy hostility, not a
merchant who reads the schema.

This is not fixable inside `policy/`, because detecting that a product titled
"Bluetooth speaker" is not footwear requires judgement about the title. It
belongs with substitution matching in `semantic/` at stage 7, and the honest
description of the current check is that it verifies the merchant's own
declaration is consistent with the mandate, not that the product is what the
merchant says it is.

---

# Amendment 3 — external review, corrections and positioning

An external review of the HLD converged with the internal audit on the two known
weaknesses, which is reassuring, and raised one contradiction the internal audit
had missed. It also contained two claims about this system that are wrong, and
those are corrected here so a demo does not get built on them.

## The contradiction: a probabilistic score must not block

The review classified product similarity as "advisory". The specification does
not: `PRODUCT_SUBSTITUTION` sits in the blocking set, and substitution detection
is planned as embedding similarity. Those cannot both stand. CLAUDE.md says drift
never blocks precisely because a probabilistic score gating a payment is the
thing this project exists to argue against, and an embedding threshold is exactly
such a score wearing a different name.

Resolved by splitting the signal by how it is computed, not by what it is about:

- **Deterministic identity mismatch blocks.** Where the mandate pins the agreed
  product and the offer carries a different one, that is an exact comparison with
  no model in it, and it raises `PRODUCT_SUBSTITUTION`.
- **Similarity-based suspicion escalates and never blocks.** Where nothing is
  pinned and only an embedding distance suggests a swap, the honest outcome is
  that the system cannot decide, so it asks.

This keeps `semantic/` advisory to an escalation rather than authoritative over a
payment, and it holds the invariant that no probabilistic number can move money.
It also confirms the schema gap: the blocking half needs a field on
`HardConstraints` naming the agreed product, which does not exist yet.

## Correction 1: the review's escalation scenario does not escalate

The review proposes demonstrating ESCALATE with "buy a laptop under 70k" answered
by a refurbished MacBook at 62k. Run against the engine, that scenario produces:

    mandate silent on condition          ALLOW     no violations
    mandate says new                     BLOCK     CONDITION_MISMATCH
    merchant writes an unknown condition ESCALATE  UNCLASSIFIABLE_CONDITION

Refurbished is a recognised member of the condition enum, so it is a definite
mismatch rather than an uncertainty. Escalation on condition requires a string
the enum cannot rank at all.

The correct escalation demo is the failure the problem statement itself names:
an instruction the extractor cannot turn into a defensible ceiling, such as "get
me a decent laptop, nothing too pricey". That is `gold_065`, and it is the
failure the track asks to see handled gracefully.

## Correction 2: the engine returning no decision

Checking the review's scenario surfaced a real defect. A mandate built through
`model_copy` skips validation and can hold a plain string where the annotation
says enum; the engine reached for `.value` on it and raised `AttributeError`.

A raised exception is not a safe failure. It returns no decision at all, which is
strictly worse than a wrong one, because a caller holding no decision has nothing
to refuse on. The engine now coerces through the enum and a regression test
asserts it returns one of the three outcomes rather than raising.

## Metric added: authorized transaction completion rate

    legitimate authorized transactions allowed
    -----------------------------------------
    legitimate authorized transactions

Already implied by the existing headline metrics, now named as a single ratio
because it states the danger directly. The risk is not only missing a violation.
It is blocking legitimate commerce, which is a revenue number rather than a
safety number, and it is the one that connects this system to a merchant's
interest in deploying it.

## Positioning

The AP2 paragraph is rescoped. "AP2 does not specify who checks the cart" invites
the reply that Razorpay already ships agentic payments with spending limits and
granular controls. The defensible framing is narrower: AP2 establishes delegated
authorization and mandate provenance, and what stays open is transaction-level
evaluation of a dynamically generated, negotiated cart against the constraints
the mandate represents. The pitch is not that anyone forgot authorization. It is
that delegated commerce becomes dynamic, and a dynamic cart needs enforcement at
the transaction rather than at the credential.

## Scope

The review's strongest advice is to add nothing. Agreed and recorded: no voice,
no recommendations, no reputation scoring, no fraud detection, no third agent.
The remaining work is finishing stages 4 to 9 and proving the security properties
experimentally, starting with making the injection experiment non-vacuous.

---

# Amendment 4 — closing the two gaps the gold set found

The gold set was written before the detector could express two of the
constraints it labelled. That is the mechanism working: an independent set of
labels measured a gap rather than an author asserting one. This closes both.

## HardConstraints gains two fields

**`product_ref: str | None`** pins the product when the user named one. It is
what gives `PRODUCT_SUBSTITUTION` something to violate. Comparing against it is
an exact match after folding punctuation and case, with no model and no
similarity score in it, which is precisely what makes it safe to block on. Where
nothing is pinned, a suspected swap is `semantic/`'s to raise and escalates
instead, per Amendment 3.

**`exclusions: tuple[str, ...]`** carries the terms the user ruled out. The
problem statement lists exclusions among the hard constraints and nothing in the
schema held them.

## Violation code 20: EXCLUDED_ITEM

Blocks. An exclusion is a hard constraint, so a better price never buys past it.

## Exclusion matching is literal, and the negation guard is the interesting part

The check folds case, matches on word boundaries, and searches the product title,
brand, colour and every line item label -- a merchant can keep the excluded thing
out of the title and still charge for it on a line.

The subtle part is what it refuses to match. "Leather-free" contains "leather"
and means the opposite of it. A naive literal matcher blocks exactly the products
the user asked for, and a false block costs a merchant real revenue, which is the
metric this project leads with. Matches preceded by "no", "non", "without" or
"free of", or followed by "-free", are skipped. Substrings inside longer words
never match at all, so an exclusion of "Nike" does not fire on "Nikecraft".

This is a deterministic floor and not a complete answer. It catches a merchant
offering the excluded thing by name, which is the common case, and it will miss a
synonym: recognising that cowhide satisfies an exclusion of leather needs
judgement about words. That belongs to `semantic/` and escalates rather than
blocks.

## What changed in the gold set, and what did not

Four substitution mandates gained a `product_ref` and four exclusion mandates
gained their `exclusions`, moving off the `spec_only_constraints` holding field.

**No label changed.** Verified by capturing all 100 labels before the edit and
diffing after: zero moved. Only the representation of the mandate changed, not
the answer, and the answers were written from the prose before either field
existed. Flagged cases drop from nine to one -- `gold_063`, the free smartphone
bundled with a laptop, which is genuinely ambiguous under the distinct-product
clause rather than merely unexpressible.

---

# Amendment 5 — observability and measurement

Audit was demoted from stage 10 to a cross-cutting requirement in the first
correction to CLAUDE.md, and this is where that lands. Three packages, built
before stage 4 so that every decision from here on is recorded and measured.

## audit/ -- the trail is a hash chain, not a log file

Each record carries the hash of the record before it. A record altered after the
fact breaks every link downstream, and `verify_chain` reports where the first
break is rather than only that something is wrong.

The reason is what a dispute actually turns on. It is not whether a decision was
recorded; it is whether the record was written before the payment or edited
after it. An append-only file cannot answer that and a chained one can. A
deleted record breaks the chain too, so silence is detectable as well as
alteration.

Every decision is recorded, blocks included. A trail that only records approvals
cannot answer why something was refused, which is the question a blocked
merchant will ask.

## gate/ -- timing lives outside the engine

Measuring elapsed time means reading a clock, and a clock inside `policy/` would
make the engine's output depend on when it ran. Keeping the stopwatch in the gate
preserves both properties at once: the decision stays reproducible and it is
still observable. A test asserts that two runs of the same inputs produce the
same decision and the same violations despite the timings differing.

The escalation question is assembled from the violations the engine already
produced, not generated by a model, so it cannot say anything the deterministic
checks did not find.

A compliance receipt is issued only on ALLOW, and it names the eleven checks that
actually ran rather than claiming "all constraints". A merchant defending a
chargeback needs the list.

## metrics/ -- three-class, and the product number leads

Three-class throughout. A binary confusion matrix would have to discard or fold
the escalations, and escalation is a real outcome rather than an error path.

The first numbers in the report are the authorized completion rate and the rupee
value of good orders wrongly blocked, because a gate that blocks everything is a
perfect detector and a useless product. Exposure prevented comes after those, not
before.

Escalation rate is computed only over cases whose expected label is ALLOW or
BLOCK, so it measures the extractor rather than the dataset's category mix.
Escalation recall is reported separately over the cases where escalating is the
correct answer.

Two structural rules, both tested: `metrics/` cannot import `policy/`, because a
measurement module that can call the engine can re-run a case until the number
improves and no reader could tell from the report; and it does no file I/O, so a
report is computed from observations rather than read from somewhere convenient.

## Explanation quality, and what it found

The concept's measurement list included explanation quality and there was no
metric for it. There is now: four deterministic components, scored per violation.
Complete means it rendered with no placeholder left in it. Specific means it
names a figure or the offending item. Plain means it avoids the vocabulary of
whoever built the system. Consequential means it says what happened to the money.

This is a proxy and not a judgement of prose. It cannot tell whether wording is
clear, only whether it is complete, concrete, plain and conclusive, which is
enough to catch a template that regressed.

Run against the twenty templates it immediately found two that never said what
happened to the money: `CONDITION_MISMATCH` and `LEDGER_ALREADY_SPENT`. Both are
fixed. The score is now 90 percent overall, and the missing ten percent is
honest rather than fixable: `LEDGER_ALREADY_SPENT` and `LEDGER_NOT_CONFIRMED`
score zero on specificity because the fault is the mandate's state and there is
no figure in the offer to name. Exempting them would be gaming the metric.
