"""Measurement.

Three principles shape what is computed here.

The outcome space has three values, so a binary confusion matrix would have to
discard or fold the escalations, and escalation is a real outcome rather than an
error path. Everything below is three-class.

The headline is not the money stopped. A gate that blocks everything is a
perfect detector and a useless product, so the first numbers reported are the
completion rate for legitimate orders and the rupee value of good orders wrongly
blocked. The safety numbers come after.

Gold and synthetic results are never blended. A report carries the name of the
dataset it came from and there is deliberately no function to merge two.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import Field

from ..core.base import StrictModel
from ..core.decision import Violation
from ..core.enums import Outcome

OUTCOMES = (Outcome.ALLOW, Outcome.BLOCK, Outcome.ESCALATE)

# Words that mean the explanation was written for whoever built the system.
DEVELOPER_VOCABULARY = (
    "null",
    "none",
    "exception",
    "traceback",
    "schema",
    "parse",
    "validation",
    "field",
    "enum",
    "int",
    "str",
    "boolean",
    "assertion",
    "stack",
)

# An explanation should say what happened to the money, not only what was wrong.
CONSEQUENCE_WORDS = ("charged", "authorized", "authorised", "asking", "confirm")


class Observation(StrictModel):
    """One case, its correct answer, and what the system actually said."""

    case_id: str
    expected: Outcome
    actual: Outcome
    amount_paise: int = 0
    latency_ms: float = 0.0
    violations: list[Violation] = Field(default_factory=list)


class ClassMetrics(StrictModel):
    outcome: Outcome
    support: int
    predicted: int
    true_positive: int
    precision: float
    recall: float
    f1: float


class ExplanationQuality(StrictModel):
    """Deterministic proxy for whether a person could act on what they were told."""

    violations_scored: int
    complete: float
    specific: float
    plain: float
    consequential: float
    overall: float


class MetricReport(StrictModel):
    dataset: str
    cases: int

    # Leading numbers: the product ones.
    authorized_completion_rate: float
    false_block_rate: float
    value_wrongly_blocked_paise: int

    # Safety numbers.
    unauthorized_pass_rate: float
    exposure_prevented_paise: int
    exposure_leaked_paise: int

    # Detection quality.
    accuracy: float
    macro_f1: float
    per_class: list[ClassMetrics]
    confusion: dict[str, dict[str, int]]

    # Escalation, split so the metric measures the extractor and not the mix.
    escalation_rate: float
    escalation_recall: float

    # Performance.
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    latency_max_ms: float

    explanation_quality: ExplanationQuality
    violations_by_code: dict[str, int]


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def percentile(samples: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile. No dependency, no interpolation to argue about."""
    if not samples:
        return 0.0
    ordered = sorted(samples)
    rank = max(1, min(len(ordered), int(-(-fraction * len(ordered) // 1))))
    return ordered[rank - 1]


def score_explanations(observations: Sequence[Observation]) -> ExplanationQuality:
    """Four things an explanation owes the person reading it.

    Complete: it rendered, with no placeholder left in it and no literal None.
    Specific: it names a figure or the offending item rather than a category.
    Plain: it avoids the vocabulary of whoever built the system.
    Consequential: it says what happened to the money.

    This is a proxy and not a judgement of prose. It cannot tell whether wording
    is clear, only whether it is complete, concrete, plain and conclusive, which
    is enough to catch a template that regressed.
    """
    violations = [v for observation in observations for v in observation.violations]
    if not violations:
        return ExplanationQuality(
            violations_scored=0,
            complete=0.0,
            specific=0.0,
            plain=0.0,
            consequential=0.0,
            overall=0.0,
        )

    complete = specific = plain = consequential = 0
    all_four = 0
    for violation in violations:
        text = violation.explanation
        lowered = text.lower()
        is_complete = bool(text) and "{" not in text and "none" not in lowered
        is_specific = any(ch.isdigit() for ch in text) or (
            violation.observed is not None and violation.observed.lower() in lowered
        )
        is_plain = not any(f" {word} " in f" {lowered} " for word in DEVELOPER_VOCABULARY)
        is_consequential = any(word in lowered for word in CONSEQUENCE_WORDS)

        complete += is_complete
        specific += is_specific
        plain += is_plain
        consequential += is_consequential
        all_four += is_complete and is_specific and is_plain and is_consequential

    total = len(violations)
    return ExplanationQuality(
        violations_scored=total,
        complete=complete / total,
        specific=specific / total,
        plain=plain / total,
        consequential=consequential / total,
        overall=all_four / total,
    )


def build_report(dataset: str, observations: Sequence[Observation]) -> MetricReport:
    """Everything, from one pass over the observations."""
    confusion = {expected.value: {actual.value: 0 for actual in OUTCOMES} for expected in OUTCOMES}
    for observation in observations:
        confusion[observation.expected.value][observation.actual.value] += 1

    per_class = []
    correct = 0
    for outcome in OUTCOMES:
        true_positive = confusion[outcome.value][outcome.value]
        support = sum(confusion[outcome.value].values())
        predicted = sum(confusion[e.value][outcome.value] for e in OUTCOMES)
        precision = _rate(true_positive, predicted)
        recall = _rate(true_positive, support)
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        correct += true_positive
        per_class.append(
            ClassMetrics(
                outcome=outcome,
                support=support,
                predicted=predicted,
                true_positive=true_positive,
                precision=precision,
                recall=recall,
                f1=f1,
            )
        )

    should_allow = [o for o in observations if o.expected is Outcome.ALLOW]
    should_block = [o for o in observations if o.expected is Outcome.BLOCK]
    decidable = [o for o in observations if o.expected in (Outcome.ALLOW, Outcome.BLOCK)]
    should_escalate = [o for o in observations if o.expected is Outcome.ESCALATE]

    wrongly_blocked = [o for o in should_allow if o.actual is Outcome.BLOCK]
    leaked = [o for o in should_block if o.actual is Outcome.ALLOW]

    codes: dict[str, int] = {}
    for observation in observations:
        for violation in observation.violations:
            codes[violation.code.value] = codes.get(violation.code.value, 0) + 1

    latencies = [o.latency_ms for o in observations]

    return MetricReport(
        dataset=dataset,
        cases=len(observations),
        authorized_completion_rate=_rate(
            sum(1 for o in should_allow if o.actual is Outcome.ALLOW), len(should_allow)
        ),
        false_block_rate=_rate(len(wrongly_blocked), len(should_allow)),
        value_wrongly_blocked_paise=sum(o.amount_paise for o in wrongly_blocked),
        unauthorized_pass_rate=_rate(len(leaked), len(should_block)),
        exposure_prevented_paise=sum(
            o.amount_paise for o in should_block if o.actual is not Outcome.ALLOW
        ),
        exposure_leaked_paise=sum(o.amount_paise for o in leaked),
        accuracy=_rate(correct, len(observations)),
        macro_f1=sum(c.f1 for c in per_class) / len(per_class) if per_class else 0.0,
        per_class=per_class,
        confusion=confusion,
        escalation_rate=_rate(
            sum(1 for o in decidable if o.actual is Outcome.ESCALATE), len(decidable)
        ),
        escalation_recall=_rate(
            sum(1 for o in should_escalate if o.actual is Outcome.ESCALATE), len(should_escalate)
        ),
        latency_p50_ms=percentile(latencies, 0.50),
        latency_p95_ms=percentile(latencies, 0.95),
        latency_p99_ms=percentile(latencies, 0.99),
        latency_max_ms=max(latencies) if latencies else 0.0,
        explanation_quality=score_explanations(observations),
        violations_by_code=dict(sorted(codes.items())),
    )
