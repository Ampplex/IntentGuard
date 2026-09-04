"""Measurement, checked against hand-computed answers.

A metrics module nobody verifies is a way to report a number that is wrong in
the direction you were hoping for.
"""

from __future__ import annotations

import pytest

from intentguard.core import Outcome, Violation, ViolationCode, from_rupees
from intentguard.metrics import Observation, build_report, percentile, score_explanations


def obs(case_id, expected, actual, amount=0, latency=1.0, violations=()):
    return Observation(
        case_id=case_id,
        expected=expected,
        actual=actual,
        amount_paise=amount,
        latency_ms=latency,
        violations=list(violations),
    )


A, B, E = Outcome.ALLOW, Outcome.BLOCK, Outcome.ESCALATE


def test_a_perfect_run() -> None:
    report = build_report("t", [obs("1", A, A), obs("2", B, B), obs("3", E, E)])
    assert report.accuracy == 1.0
    assert report.macro_f1 == 1.0
    assert report.false_block_rate == 0.0
    assert report.authorized_completion_rate == 1.0
    assert report.unauthorized_pass_rate == 0.0


def test_a_gate_that_blocks_everything_scores_badly_where_it_should() -> None:
    """A perfect detector and a useless product. The metrics have to show that."""
    report = build_report(
        "t",
        [
            obs("1", A, B, amount=from_rupees(5000)),
            obs("2", A, B, amount=from_rupees(3000)),
            obs("3", B, B),
            obs("4", B, B),
        ],
    )
    assert report.unauthorized_pass_rate == 0.0, "it never lets a bad order through"
    assert report.authorized_completion_rate == 0.0, "and it never lets a good one through either"
    assert report.false_block_rate == 1.0
    assert report.value_wrongly_blocked_paise == from_rupees(8000)


def test_leaked_exposure_is_counted_separately_from_prevented() -> None:
    report = build_report(
        "t",
        [obs("1", B, B, amount=from_rupees(9000)), obs("2", B, A, amount=from_rupees(7000))],
    )
    assert report.exposure_prevented_paise == from_rupees(9000)
    assert report.exposure_leaked_paise == from_rupees(7000)
    assert report.unauthorized_pass_rate == 0.5


def test_escalation_rate_ignores_cases_where_escalating_is_correct() -> None:
    """The original threshold measured the dataset's category mix, not the extractor.

    Four cases, two of which should escalate. One decidable case escalates, so
    the rate is one in two, not one in four.
    """
    report = build_report("t", [obs("1", A, A), obs("2", B, E), obs("3", E, E), obs("4", E, E)])
    assert report.escalation_rate == 0.5
    assert report.escalation_recall == 1.0


def test_escalation_recall_is_reported_even_when_the_rate_is_zero() -> None:
    report = build_report("t", [obs("1", E, B), obs("2", E, E)])
    assert report.escalation_rate == 0.0
    assert report.escalation_recall == 0.5


def test_per_class_precision_and_recall() -> None:
    report = build_report("t", [obs("1", A, A), obs("2", A, B), obs("3", B, B), obs("4", B, B)])
    by_outcome = {c.outcome: c for c in report.per_class}
    assert by_outcome[A].recall == 0.5
    assert by_outcome[A].precision == 1.0
    assert by_outcome[B].recall == 1.0
    assert by_outcome[B].precision == pytest.approx(2 / 3)


def test_the_confusion_matrix_covers_all_nine_cells() -> None:
    report = build_report("t", [obs("1", A, E)])
    assert set(report.confusion) == {"ALLOW", "BLOCK", "ESCALATE"}
    assert report.confusion["ALLOW"]["ESCALATE"] == 1
    assert report.confusion["ALLOW"]["ALLOW"] == 0
    assert sum(sum(row.values()) for row in report.confusion.values()) == 1


def test_an_empty_dataset_does_not_divide_by_zero() -> None:
    report = build_report("t", [])
    assert report.cases == 0
    assert report.accuracy == 0.0
    assert report.latency_p95_ms == 0.0


@pytest.mark.parametrize(
    ("fraction", "expected"), [(0.5, 5.0), (0.95, 10.0), (0.99, 10.0), (0.1, 1.0)]
)
def test_percentile(fraction: float, expected: float) -> None:
    assert percentile([float(n) for n in range(1, 11)], fraction) == expected


def test_percentile_of_nothing_is_zero() -> None:
    assert percentile([], 0.5) == 0.0


def test_latency_percentiles_come_from_the_observations() -> None:
    report = build_report("t", [obs(str(n), A, A, latency=float(n)) for n in range(1, 101)])
    assert report.latency_p50_ms == 50.0
    assert report.latency_p95_ms == 95.0
    assert report.latency_max_ms == 100.0


def test_violations_are_counted_by_code() -> None:
    v = Violation(code=ViolationCode.TOTAL_EXCEEDS_MAX, outcome=B, explanation="over by 100.")
    report = build_report("t", [obs("1", B, B, violations=[v]), obs("2", B, B, violations=[v])])
    assert report.violations_by_code == {"TOTAL_EXCEEDS_MAX": 2}


# --- explanation quality --------------------------------------------------


def scored(explanation: str, observed: str | None = None):
    v = Violation(
        code=ViolationCode.TOTAL_EXCEEDS_MAX, outcome=B, explanation=explanation, observed=observed
    )
    return score_explanations([obs("1", B, B, violations=[v])])


def test_a_good_explanation_scores_full_marks() -> None:
    q = scored(
        "This order comes to Rs 5,499.00, but you authorized at most "
        "Rs 5,000.00. Nothing was charged."
    )
    assert q.overall == 1.0


def test_a_hole_in_the_text_fails_completeness() -> None:
    assert scored("You authorized None, but this order is for 3.").complete == 0.0


def test_developer_vocabulary_fails_plainness() -> None:
    assert scored("Offer failed schema validation at field total_paise.").plain == 0.0


def test_a_vague_explanation_fails_specificity() -> None:
    assert scored("Something about this order was not authorized.").specific == 0.0


def test_not_saying_what_happened_to_the_money_fails() -> None:
    q = scored("You asked for a new item, but this one is refurbished.")
    assert q.consequential == 0.0
    assert q.overall == 0.0


def test_nothing_to_score_is_not_a_perfect_score() -> None:
    q = score_explanations([obs("1", A, A)])
    assert q.violations_scored == 0
    assert q.overall == 0.0
