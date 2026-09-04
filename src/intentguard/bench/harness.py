"""Runs the benchmark and reports it.

The harness may import the implementation. The generator may not, and that
asymmetry is the point: the cases are written from the specification, and only
the measuring is allowed to know how the system works.

Two things are reported separately and never merged. Train and holdout, because
a number quoted from data that thresholds were derived against is not evidence.
And gold against synthetic, because they are different kinds of claim: gold is
hand-labelled and small, synthetic is generated and large, and averaging them
produces a figure that describes neither.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..core.enums import Outcome
from ..core.intent import IntentLedger
from ..gate import receive
from ..metrics import MetricReport, Observation, build_report

# Cases are written relative to an anchor rather than wall-clock time, so a TTL
# case means the same thing whenever the benchmark is run.
EPOCH = datetime(2026, 9, 4, 10, 0, 0, tzinfo=UTC)

SYNTHETIC_PATH = Path(__file__).resolve().parents[3] / "data" / "synthetic" / "cases.json"
GOLD_PATH = Path(__file__).resolve().parents[3] / "data" / "gold" / "cases.json"


def load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_case(case: dict) -> Observation:
    """Put one case through the same entry point a merchant's payload uses."""
    ledger = IntentLedger.model_validate({**case["ledger"], "created_at": EPOCH})
    now = EPOCH + timedelta(seconds=case["now_offset_seconds"])

    started = time.perf_counter()
    decision, _ = receive(ledger, case["offer"], now=now)
    elapsed_ms = (time.perf_counter() - started) * 1000

    stated_total = case["offer"].get("total_paise")
    return Observation(
        case_id=case["case_id"],
        expected=Outcome(case["label"]),
        actual=decision.decision,
        amount_paise=stated_total if isinstance(stated_total, int) else 0,
        latency_ms=elapsed_ms,
        violations=decision.violations,
    )


def run(cases: Iterable[dict]) -> list[Observation]:
    return [run_case(case) for case in cases]


def report_for(dataset: str, cases: Sequence[dict]) -> MetricReport:
    return build_report(dataset, run(cases))


def injection_experiment(cases: Sequence[dict]) -> dict:
    """Does hostile text in a description move any decision?

    Stated precisely, because the sloppy version of this claim is worth nothing.
    Each injected case is a copy of a real one with text spliced into
    raw_description and no other field touched. A changed decision would mean
    the description reached something that decides.

    Today nothing reads raw_description, so a null result here is a structural
    fact rather than an experimental finding, and it is reported as such. It
    becomes evidence about a model when a model reads that field.
    """
    by_id = {case["case_id"]: case for case in cases}
    pairs = [c for c in cases if c.get("injection_of") in by_id]
    changed = []
    for twin in pairs:
        original = by_id[twin["injection_of"]]
        if run_case(twin).actual is not run_case(original).actual:
            changed.append(twin["case_id"])
    return {
        "pairs": len(pairs),
        "decisions_changed": len(changed),
        "changed_case_ids": changed,
        "claim": (
            "structural: raw_description is not read by any component that decides, "
            "so this measures transport rather than model resistance"
        ),
    }


def _money(paise: int) -> str:
    return f"Rs {paise // 100:,}"


def render(report: MetricReport) -> str:
    lines = [
        f"=== {report.dataset} ===  {report.cases} cases",
        "",
        "  product",
        f"    authorized completion rate   {report.authorized_completion_rate:.1%}",
        f"    false block rate             {report.false_block_rate:.1%}",
        f"    value wrongly blocked        {_money(report.value_wrongly_blocked_paise)}",
        "",
        "  safety",
        f"    unauthorized pass rate       {report.unauthorized_pass_rate:.1%}",
        f"    exposure prevented           {_money(report.exposure_prevented_paise)}",
        f"    exposure leaked              {_money(report.exposure_leaked_paise)}",
        "",
        "  detection",
        f"    accuracy {report.accuracy:.1%}   macro F1 {report.macro_f1:.3f}",
    ]
    for entry in report.per_class:
        lines.append(
            f"      {entry.outcome.value:<9} support {entry.support:<5} "
            f"precision {entry.precision:.3f}  recall {entry.recall:.3f}  f1 {entry.f1:.3f}"
        )
    lines += [
        f"    escalation rate {report.escalation_rate:.1%} (over decidable cases)",
        f"    escalation recall {report.escalation_recall:.1%}",
        "",
        "  performance",
        f"    p50 {report.latency_p50_ms:.3f} ms   p95 {report.latency_p95_ms:.3f} ms   "
        f"p99 {report.latency_p99_ms:.3f} ms",
        "",
        "  explanation quality",
        f"    complete {report.explanation_quality.complete:.0%}  "
        f"specific {report.explanation_quality.specific:.0%}  "
        f"plain {report.explanation_quality.plain:.0%}  "
        f"consequential {report.explanation_quality.consequential:.0%}  "
        f"-> overall {report.explanation_quality.overall:.0%}",
    ]
    return "\n".join(lines)


def main(include_holdout: bool = False, include_gold: bool = False) -> None:
    """Report the training slice by default.

    The holdout and the gold set are opt-in because looking at them is the thing
    that spends them. A number from data you have been iterating against is not
    evidence, and the only way to keep that true is to make reading it a
    deliberate act.
    """
    cases = load(SYNTHETIC_PATH)
    train = [c for c in cases if c["split"] == "train"]

    print(render(report_for("synthetic / train", train)))
    print()
    experiment = injection_experiment(cases)
    print(
        f"=== injection ===  {experiment['pairs']} twin pairs, "
        f"{experiment['decisions_changed']} decisions changed"
    )
    print(f"    {experiment['claim']}")

    if include_holdout:
        holdout = [c for c in cases if c["split"] == "holdout"]
        print()
        print(render(report_for("synthetic / holdout", holdout)))
    if include_gold:
        print()
        print(render(report_for("gold (held out, hand-labelled)", load(GOLD_PATH))))


if __name__ == "__main__":
    import sys

    main(
        include_holdout="--holdout" in sys.argv,
        include_gold="--gold" in sys.argv,
    )
