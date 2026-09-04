"""The harness, and the reporting discipline around it."""

from __future__ import annotations

from intentguard.bench import generator
from intentguard.bench.harness import injection_experiment, render, report_for, run_case
from intentguard.core import Outcome

CASES = generator.generate(seed=99)
TRAIN = [case for case in CASES if case["split"] == "train"]
HOLDOUT = [case for case in CASES if case["split"] == "holdout"]


def test_a_case_runs_through_the_same_entry_point_a_merchant_uses() -> None:
    """Not a private path. What the benchmark measures has to be what runs."""
    observation = run_case(CASES[0])
    assert observation.case_id == CASES[0]["case_id"]
    assert observation.actual in set(Outcome)
    assert observation.latency_ms > 0


def test_unmodelled_cases_reach_a_decision_rather_than_an_exception() -> None:
    """They never parse into an Offer, so they exercise the wire boundary."""
    unmodelled = [case for case in CASES if case["offer_carries_unknown_field"]]
    assert unmodelled
    for case in unmodelled[:20]:
        assert run_case(case).actual is Outcome.ESCALATE


def test_train_and_holdout_are_reported_separately() -> None:
    """A number quoted from data thresholds were derived against is not evidence."""
    train = report_for("train", TRAIN[:120])
    holdout = report_for("holdout", HOLDOUT[:60])
    assert train.dataset != holdout.dataset
    assert train.cases != holdout.cases


def test_there_is_no_way_to_merge_two_reports() -> None:
    """Gold and synthetic are different kinds of claim, and averaging describes neither."""
    from intentguard import metrics

    assert not any(name.startswith(("merge", "combine", "blend")) for name in dir(metrics))


def test_the_rendered_report_leads_with_the_product_numbers() -> None:
    """A gate that blocks everything is a perfect detector and a useless product.

    Exposure prevented reads well and says nothing about whether the thing is
    deployable, so it comes after the numbers that do.
    """
    text = render(report_for("sample", TRAIN[:80]))
    assert text.index("authorized completion rate") < text.index("exposure prevented")
    assert text.index("false block rate") < text.index("unauthorized pass rate")


def test_the_report_states_the_escalation_denominator() -> None:
    text = render(report_for("sample", TRAIN[:80]))
    assert "over decidable cases" in text


def test_the_injection_experiment_reports_what_it_actually_measures() -> None:
    """A null result here is a structural fact today, not an experimental finding.

    Nothing reads raw_description, so the claim being made is about transport.
    Reporting it as evidence of model resistance would be dishonest, and the
    harness says so in the result rather than in a comment.
    """
    result = injection_experiment(CASES)
    assert result["pairs"] > 0
    assert result["decisions_changed"] == 0
    assert "structural" in result["claim"]
    assert "raw_description is not read" in result["claim"]


def test_latency_is_measured_per_case() -> None:
    report = report_for("sample", TRAIN[:200])
    assert report.latency_p50_ms > 0
    assert report.latency_p95_ms >= report.latency_p50_ms
    assert report.latency_p99_ms >= report.latency_p95_ms


def test_the_engine_agrees_with_the_specs_boundaries() -> None:
    """The only part of a self-generated set that can disagree for a good reason.

    Everything else in the benchmark is written from the same reading of the
    spec the engine was built from, so agreement there mostly means the two
    readings match. These are the corners where two honest readings diverge.
    """
    boundaries = [case for case in CASES if case["kind"] == "boundary"]
    assert len(boundaries) >= 150
    wrong = [case["case_id"] for case in boundaries if run_case(case).actual.value != case["label"]]
    assert wrong == [], f"the engine disagrees with the spec at: {wrong[:5]}"
