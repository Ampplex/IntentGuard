"""The stage 11 gate: an ambiguous instruction pauses, asks, and resumes.

This is the failure the track asks to see handled gracefully, and the one the
problem statement names: the user says something the extractor cannot turn into
a defensible ceiling, and the system neither guesses nor silently passes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from intentguard.audit import AuditLog, render_receipt
from intentguard.core import LedgerStatus, LineItem, LineItemKind, Outcome, from_rupees
from intentguard.gate import (
    Answer,
    EscalationBook,
    QuestionKind,
    Resolution,
    ask_about_mandate,
    ask_about_offer,
    issue_receipt,
    receive,
    render_question,
    resolve_mandate,
    resolve_offer,
)
from intentguard.ledger import RuleBasedExtractor, build_ledger
from tests.fixtures import a_ledger, an_offer

ASKED = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
ANSWERED = ASKED + timedelta(hours=6)  # a person who took their time

EXTRACT = RuleBasedExtractor()
AMBIGUOUS = "Get me a decent laptop, nothing too pricey."
CLEAR = "Buy me a pair of new running shoes, budget 5000 rupees."


def proposal_for(instruction: str, *, created_at: datetime = ASKED):
    return build_ledger(instruction, EXTRACT.extract(instruction), created_at=created_at)


def answer(question, approved: bool, at: datetime = ANSWERED) -> Answer:
    return Answer(question_id=question.question_id, approved=approved, answered_at=at)


# --- a mandate that could not be built ------------------------------------


def test_an_ambiguous_instruction_pauses_instead_of_guessing() -> None:
    proposal = proposal_for(AMBIGUOUS)
    question = ask_about_mandate(proposal, now=ASKED)

    assert proposal.ledger is None, "no ceiling was defensible, so no mandate was built"
    assert question is not None
    assert question.kind is QuestionKind.MANDATE
    assert "max_total_paise" in question.weak_fields


def test_the_question_names_the_phrase_it_could_not_read() -> None:
    """ "We need more information" is not a question anyone can answer."""
    question = ask_about_mandate(proposal_for(AMBIGUOUS), now=ASKED)
    assert "decent" in question.question
    assert "how much you want to spend" in question.question


def test_a_clear_instruction_asks_nothing() -> None:
    """A guard that questions every purchase is not a product."""
    assert ask_about_mandate(proposal_for(CLEAR), now=ASKED) is None


def test_confirming_a_reading_produces_a_live_mandate() -> None:
    proposal = proposal_for("Get me 3 shirts, budget 2000.")
    question = ask_about_mandate(proposal, now=ASKED)
    assert proposal.ledger.status is LedgerStatus.AWAITING_CONFIRMATION

    resolved = resolve_mandate(question, answer(question, True), proposal, now=ANSWERED)
    assert resolved.resolution is Resolution.CONFIRMED
    assert resolved.ledger.status is LedgerStatus.ACTIVE


def test_the_clock_restarts_rather_than_resuming() -> None:
    """Six hours spent deciding is not six hours the authorization was live.

    Resuming the clock would expire a transaction the person was mid-approval
    of, which is a bad product and a worse demo.
    """
    proposal = proposal_for("Get me 3 shirts, budget 2000.")
    question = ask_about_mandate(proposal, now=ASKED)
    resolved = resolve_mandate(question, answer(question, True), proposal, now=ANSWERED)

    assert resolved.ledger.created_at == ANSWERED
    decision, _ = receive(resolved.ledger, shirts_payload(), now=ANSWERED + timedelta(minutes=1))
    assert decision.decision is not Outcome.BLOCK or all(
        v.code.value != "LEDGER_EXPIRED" for v in decision.violations
    )


def test_confirming_does_not_quietly_change_the_constraints() -> None:
    proposal = proposal_for("Get me 3 shirts, budget 2000.")
    question = ask_about_mandate(proposal, now=ASKED)
    resolved = resolve_mandate(question, answer(question, True), proposal, now=ANSWERED)
    assert resolved.ledger.hard == proposal.ledger.hard


def test_declining_produces_no_mandate() -> None:
    proposal = proposal_for("Get me 3 shirts, budget 2000.")
    question = ask_about_mandate(proposal, now=ASKED)
    resolved = resolve_mandate(question, answer(question, False), proposal, now=ANSWERED)
    assert resolved.resolution is Resolution.DECLINED
    assert resolved.ledger is None


def test_approving_a_mandate_that_was_never_built_is_refused() -> None:
    """Approving a reading that does not exist would invent constraints."""
    proposal = proposal_for(AMBIGUOUS)
    question = ask_about_mandate(proposal, now=ASKED)
    resolved = resolve_mandate(question, answer(question, True), proposal, now=ANSWERED)
    assert resolved.resolution is Resolution.DECLINED
    assert "needs restating" in resolved.detail


def test_an_answer_to_a_different_question_is_refused() -> None:
    proposal = proposal_for("Get me 3 shirts, budget 2000.")
    question = ask_about_mandate(proposal, now=ASKED)
    stray = Answer(question_id="q_somebody_else", approved=True, answered_at=ANSWERED)
    assert (
        resolve_mandate(question, stray, proposal, now=ANSWERED).resolution is Resolution.OVERTAKEN
    )


# --- a cart the engine could not judge ------------------------------------


def shirts_payload() -> dict:
    """A cart that matches the three-shirts mandate.

    The fixture offer is footwear at 4200, so reusing it against an apparel
    mandate with a 2000 ceiling would fail on category and price rather than on
    what the test is about.
    """
    offer = an_offer(
        offer_id="off_shirts",
        quantity=3,
        line_items=[
            LineItem(label="Shirt x3", amount_paise=from_rupees(1900), kind=LineItemKind.PRODUCT)
        ],
        total_paise=from_rupees(1900),
    )
    return offer.model_copy(
        update={
            "product": offer.product.model_copy(update={"category": "apparel", "title": "Shirt"})
        }
    ).model_dump(mode="json")


def unjudgeable_payload() -> dict:
    offer = an_offer()
    return offer.model_copy(
        update={"product": offer.product.model_copy(update={"condition": "gently loved"})}
    ).model_dump(mode="json")


def test_an_unjudgeable_cart_asks_rather_than_deciding() -> None:
    ledger = a_ledger()
    decision, _ = receive(ledger, unjudgeable_payload(), now=ASKED)
    question, paused = ask_about_offer(decision, ledger, now=ASKED)

    assert decision.decision is Outcome.ESCALATE
    assert question is not None
    assert question.kind is QuestionKind.OFFER
    assert "gently loved" in question.question
    assert paused.status is LedgerStatus.AWAITING_CONFIRMATION, "the clock stops"


def test_a_slow_answer_does_not_expire_the_transaction() -> None:
    """The failure the specification names, and the reason the clock stops.

    Six hours pass between the question and the answer, well past the one hour
    TTL. Leaving the mandate live meant the person's own deliberation expired
    the order they were approving.
    """
    ledger = a_ledger()
    payload = unjudgeable_payload()
    decision, _ = receive(ledger, payload, now=ASKED)
    question, paused = ask_about_offer(decision, ledger, now=ASKED)

    resolved, _ = resolve_offer(question, answer(question, True), paused, payload, now=ANSWERED)
    assert resolved.resolution is Resolution.CONFIRMED
    assert resolved.decision.decision is Outcome.ALLOW


def test_an_allowed_cart_asks_nothing_and_keeps_its_clock() -> None:
    ledger = a_ledger()
    decision, _ = receive(ledger, an_offer().model_dump(mode="json"), now=ASKED)
    question, unchanged = ask_about_offer(decision, ledger, now=ASKED)
    assert question is None
    assert unchanged.status is ledger.status


def test_approving_resolves_the_uncertainty_and_records_who_did() -> None:
    ledger = a_ledger()
    payload = unjudgeable_payload()
    decision, _ = receive(ledger, payload, now=ASKED)
    question, paused = ask_about_offer(decision, ledger, now=ASKED)

    resolved, record = resolve_offer(
        question, answer(question, True), paused, payload, now=ANSWERED
    )
    assert resolved.resolution is Resolution.CONFIRMED
    assert resolved.decision.decision is Outcome.ALLOW
    assert record.human_confirmed is True


def test_a_human_approval_is_a_distinct_class_of_evidence() -> None:
    """The receipt has to say a person decided, not that the engine did."""
    ledger = a_ledger()
    payload = unjudgeable_payload()
    decision, _ = receive(ledger, payload, now=ASKED)
    question, paused = ask_about_offer(decision, ledger, now=ASKED)
    _, record = resolve_offer(question, answer(question, True), paused, payload, now=ANSWERED)

    assert "human confirmed  yes" in render_receipt(issue_receipt(record))


def test_declining_a_cart_charges_nothing() -> None:
    ledger = a_ledger()
    payload = unjudgeable_payload()
    decision, _ = receive(ledger, payload, now=ASKED)
    question, paused = ask_about_offer(decision, ledger, now=ASKED)

    resolved, record = resolve_offer(
        question, answer(question, False), paused, payload, now=ANSWERED
    )
    assert resolved.resolution is Resolution.DECLINED
    assert record is None


def test_an_approval_cannot_override_a_definite_violation() -> None:
    """The property that keeps the answer from being "someone clicked yes".

    A person can resolve something the engine could not judge. They cannot
    resolve something it judged and refused.
    """
    ledger = a_ledger()
    offer = an_offer()
    unjudgeable_and_over_budget = offer.model_copy(
        update={
            "product": offer.product.model_copy(update={"condition": "gently loved"}),
            "line_items": [
                LineItem(label="Shoes", amount_paise=from_rupees(9000), kind=LineItemKind.PRODUCT)
            ],
            "total_paise": from_rupees(9000),
        }
    ).model_dump(mode="json")

    decision, _ = receive(ledger, unjudgeable_and_over_budget, now=ASKED)
    assert decision.decision is Outcome.BLOCK, "a definite breach outranks the uncertainty"

    # Ask anyway, as though the escalation had been raised on an earlier cart.
    forced, paused = ask_about_offer(
        decision.model_copy(
            update={"decision": Outcome.ESCALATE, "escalation_question": "go ahead?"}
        ),
        ledger,
        now=ASKED,
    )
    resolved, _ = resolve_offer(
        forced, answer(forced, True), paused, unjudgeable_and_over_budget, now=ANSWERED
    )
    assert resolved.resolution is Resolution.OVERTAKEN
    assert resolved.decision.decision is Outcome.BLOCK
    assert "not a breach" in resolved.detail


def test_a_cart_that_expired_while_the_person_thought_is_not_waved_through() -> None:
    """Re-running rather than overriding is what catches this."""
    ledger = a_ledger()
    payload = unjudgeable_payload()
    decision, _ = receive(ledger, payload, now=ASKED)
    question, _paused = ask_about_offer(decision, ledger, now=ASKED)

    spent = ledger.model_copy(update={"status": LedgerStatus.SPENT})
    resolved, _ = resolve_offer(question, answer(question, True), spent, payload, now=ANSWERED)
    assert resolved.resolution is Resolution.OVERTAKEN
    assert resolved.decision.decision is Outcome.BLOCK


def test_a_paused_mandate_is_made_live_before_the_recheck() -> None:
    """Otherwise the re-run refuses it for being paused, which is circular."""
    proposal = proposal_for("Get me 3 shirts, budget 2000.")
    assert proposal.ledger.status is LedgerStatus.AWAITING_CONFIRMATION

    payload = shirts_payload()
    decision, _ = receive(proposal.ledger, payload, now=ASKED)
    question, paused = ask_about_offer(decision, proposal.ledger, now=ASKED)
    assert question is not None, "a paused mandate escalates on LEDGER_NOT_CONFIRMED"

    resolved, _ = resolve_offer(question, answer(question, True), paused, payload, now=ANSWERED)
    assert resolved.ledger.status is LedgerStatus.ACTIVE


# --- questions that outlive the process -----------------------------------


def test_a_question_can_be_answered_tomorrow(tmp_path) -> None:
    """A person asked to confirm a purchase does not answer within a request."""
    book = EscalationBook(tmp_path / "questions.jsonl")
    proposal = proposal_for("Get me 3 shirts, budget 2000.")
    asked = book.ask(ask_about_mandate(proposal, now=ASKED))

    reopened = EscalationBook(tmp_path / "questions.jsonl")
    found = reopened.find(asked.question_id)
    assert found is not None
    assert found.question == asked.question
    assert len(reopened) == 1


def test_questions_can_be_listed_for_an_intent(tmp_path) -> None:
    book = EscalationBook(tmp_path / "questions.jsonl")
    proposal = proposal_for("Get me 3 shirts, budget 2000.")
    question = book.ask(ask_about_mandate(proposal, now=ASKED))
    assert book.for_intent(question.intent_id) == [question]
    assert book.for_intent("int_nobody") == []


def test_the_rendered_question_tells_the_person_nothing_was_charged(tmp_path) -> None:
    question = ask_about_mandate(proposal_for(AMBIGUOUS), now=ASKED)
    text = render_question(question)
    assert "Nothing has been charged" in text
    assert "decent" in text
    assert "max total" in text


# --- the whole flow -------------------------------------------------------


def test_pause_ask_resume_end_to_end(tmp_path) -> None:
    """The demo, as one test."""
    log = AuditLog(tmp_path / "audit.jsonl")
    book = EscalationBook(tmp_path / "questions.jsonl")

    proposal = proposal_for("Get me 3 shirts, budget 2000.")
    question = book.ask(ask_about_mandate(proposal, now=ASKED))
    assert question is not None, "it paused"

    resolved = resolve_mandate(question, answer(question, True), proposal, now=ANSWERED)
    assert resolved.resolution is Resolution.CONFIRMED, "it resumed"

    decision, record = receive(
        resolved.ledger, shirts_payload(), now=ANSWERED + timedelta(minutes=2), log=log
    )
    assert decision.decision is Outcome.ALLOW
    assert log.verify_chain() is None


def test_a_confirmed_mandate_stops_being_asked_about() -> None:
    """Without this the escalation path could never complete.

    A mandate confirmed by a person still carried the extractor's low confidence
    score, so LOW_CONFIDENCE fired on every subsequent offer and every answer
    produced another question. Confirmation supersedes the score rather than
    overwriting it: the original assessment stays on the record.
    """
    proposal = proposal_for("Get me 3 shirts, budget 2000.")
    assert proposal.confidence["max_total_paise"] < 0.85
    assert proposal.ledger.human_confirmed is False

    question = ask_about_mandate(proposal, now=ASKED)
    resolved = resolve_mandate(question, answer(question, True), proposal, now=ANSWERED)

    assert resolved.ledger.human_confirmed is True
    assert resolved.ledger.confidence["max_total_paise"] < 0.85, (
        "the extractor's own assessment is kept, not rewritten"
    )

    decision, _ = receive(resolved.ledger, shirts_payload(), now=ANSWERED + timedelta(minutes=2))
    assert decision.decision is Outcome.ALLOW


def test_an_unconfirmed_mandate_is_still_asked_about() -> None:
    proposal = proposal_for("Get me 3 shirts, budget 2000.")
    live = proposal.ledger.model_copy(update={"status": LedgerStatus.ACTIVE})
    decision, _ = receive(live, shirts_payload(), now=ASKED + timedelta(minutes=2))
    assert decision.decision is Outcome.ESCALATE
    assert any(v.code.value == "LOW_CONFIDENCE" for v in decision.violations)
