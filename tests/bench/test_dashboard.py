"""The stage 12 gate: the dashboard renders a real run, not fixtures.

The gate is enforced by there being nowhere to put a fixture. The template has a
single placeholder, the build fills it from export output, and it raises if that
output is missing rather than falling back to something plausible.
"""

from __future__ import annotations

import json

import pytest

from intentguard.bench import export
from intentguard.bench.dashboard import PLACEHOLDER, build

TEMPLATE = '<html><script id="run">' + PLACEHOLDER + "</script></html>"


@pytest.fixture(scope="module")
def run() -> dict:
    """A genuine run of the whole system, produced the way the page is."""
    return export.build()


def test_the_build_refuses_to_invent_data(tmp_path) -> None:
    """No fixture fallback. A dashboard nobody can trust is worse than none."""
    template = tmp_path / "t.html"
    template.write_text(TEMPLATE, encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="real run"):
        build(template, tmp_path / "out.html", data_path=tmp_path / "missing.json")


def test_the_build_refuses_a_template_with_nowhere_to_put_the_run(tmp_path) -> None:
    template = tmp_path / "t.html"
    template.write_text("<html>no placeholder</html>", encoding="utf-8")
    data = tmp_path / "run.json"
    data.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="placeholder|DASHBOARD_DATA"):
        build(template, tmp_path / "out.html", data_path=data)


def test_the_built_page_contains_the_run_and_no_placeholder(tmp_path, run) -> None:
    template = tmp_path / "t.html"
    template.write_text(TEMPLATE, encoding="utf-8")
    data = tmp_path / "run.json"
    data.write_text(json.dumps(run), encoding="utf-8")

    out = build(template, tmp_path / "out.html", data_path=data)
    html = out.read_text(encoding="utf-8")
    assert PLACEHOLDER not in html
    assert run["scenarios"][0]["name"] in html


def test_hostile_text_cannot_close_the_script_block(tmp_path) -> None:
    """The merchant descriptions in this data are injection strings by design.

    An unescaped closing tag inside the embedded JSON would end the script early
    and turn the page into whatever the merchant wrote.
    """
    template = tmp_path / "t.html"
    template.write_text(TEMPLATE, encoding="utf-8")
    data = tmp_path / "run.json"
    data.write_text(json.dumps({"hostile": "</script><script>alert(1)</script>"}), encoding="utf-8")

    out = build(template, tmp_path / "out.html", data_path=data)
    html = out.read_text(encoding="utf-8")
    assert "</script><script>alert(1)" not in html
    assert "<\\/script>" in html


# --- the run itself -------------------------------------------------------


def test_every_scenario_ran_the_whole_pipeline(run: dict) -> None:
    assert len(run["scenarios"]) >= 5
    for scenario in run["scenarios"]:
        assert scenario["decision"] in {"ALLOW", "BLOCK", "ESCALATE"}
        assert scenario["negotiation"]["rounds"], "a negotiation with no rounds did not happen"
        assert scenario["latency_ms"] > 0


def test_the_merchant_never_saw_a_ceiling_in_any_scenario(run: dict) -> None:
    assert all(scenario["merchant_view_has_ceiling"] is False for scenario in run["scenarios"])


def test_the_rail_is_reached_only_where_the_decision_allowed_it(run: dict) -> None:
    """The invariant, checked against the run rather than asserted on the page."""
    for scenario in run["scenarios"]:
        reached = scenario["payment"]["reached_the_rail"]
        assert reached == (scenario["decision"] == "ALLOW"), scenario["name"]


def test_a_receipt_exists_exactly_where_money_moved(run: dict) -> None:
    for scenario in run["scenarios"]:
        has_receipt = scenario["compliance_receipt"] is not None
        assert has_receipt == (scenario["decision"] == "ALLOW"), scenario["name"]


def test_the_run_shows_a_swap_being_caught(run: dict) -> None:
    """A demo where nothing is ever caught demonstrates nothing."""
    swapped = [
        s for s in run["scenarios"] if s.get("negotiated_product") != s.get("delivered_product")
    ]
    assert swapped, "no scenario exercises substitution"
    assert all(s["decision"] != "ALLOW" for s in swapped)


def test_the_run_shows_at_least_one_of_each_outcome(run: dict) -> None:
    outcomes = {s["decision"] for s in run["scenarios"]}
    assert {"ALLOW", "BLOCK"} <= outcomes


def test_the_timeout_path_reconciles_and_never_retries(run: dict) -> None:
    timeout = run["timeout"]
    assert timeout["attempt"] == "uncertain"
    assert timeout["ledger_after_timeout"] == "EXECUTION_UNCERTAIN"
    assert timeout["retried"] is False
    assert timeout["reconciled_order"]
    assert timeout["ledger_after_reconciling"] == "SPENT"


def test_the_escalation_pauses_and_does_not_expire(run: dict) -> None:
    answered = [e for e in run["mandate_escalations"] if e.get("resolution")]
    assert answered
    assert all(e["expired_while_waiting"] is False for e in answered)
    assert all(e["hours_to_answer"] >= 6 for e in answered)


def test_an_offer_escalation_records_the_human(run: dict) -> None:
    escalation = run["offer_escalation"]
    assert escalation["decision"] == "ESCALATE"
    assert escalation["clock_paused"] == "AWAITING_CONFIRMATION"
    assert escalation["decision_after"] == "ALLOW"
    assert escalation["human_confirmed"] is True


def test_the_threat_table_covers_every_hostile_mode(run: dict) -> None:
    from intentguard.merchant import Hostility

    assert {row["attack"] for row in run["threat_table"]} == {h.value for h in Hostility}
    # Injection is expected to be allowed, and that is the finding rather than a
    # gap: hostile text in a description does not move a decision, because
    # nothing that decides reads it.
    expected_allow = {"none", "injection"}
    for row in run["threat_table"]:
        if row["attack"] in expected_allow:
            assert row["decision"] == "ALLOW", row
        else:
            assert row["decision"] != "ALLOW", row
            assert row["codes"], f"{row['attack']} was refused without naming why"


def test_the_audit_chain_is_intact_after_the_whole_run(run: dict) -> None:
    assert run["audit"]["intact"] is True
    assert run["audit"]["records"] >= 5
    assert set(run["audit"]["decisions"]) & {"ALLOW", "BLOCK"}


def test_the_page_states_what_the_benchmark_number_does_not_mean(run: dict) -> None:
    """The caveat is part of the deliverable, not a footnote to add later."""
    assert run["benchmark"]["accuracy"] >= 0.9
    assert "structural" in run["injection"]["claim"]


def test_latency_is_measured_not_quoted(run: dict) -> None:
    assert run["latency"]["samples"] >= 1000
    assert 0 < run["latency"]["p50_ms"] < 5
    assert run["latency"]["p99_ms"] >= run["latency"]["p50_ms"]
