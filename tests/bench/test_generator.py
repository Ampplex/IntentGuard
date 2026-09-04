"""The generator, and the properties that make its numbers worth anything.

The credibility problem CLAUDE.md names is that the same repository writes the
generator and the detector. Every test here is about one of the mitigations
rather than about generation working.
"""

from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from intentguard.bench import generator
from intentguard.core import IntentLedger, Offer, Outcome

GENERATOR_PATH = Path(generator.__file__)
CASES = generator.generate()


def test_the_generator_cannot_import_the_implementation() -> None:
    """CLAUDE.md requires it cannot import policy/. This is the stronger rule.

    A generator that can reach any part of the implementation can encode its
    assumptions without anyone intending to, and then precision and recall
    measure agreement rather than correctness.
    """
    tree = ast.parse(GENERATOR_PATH.read_text(encoding="utf-8"))
    reached = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            reached.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            reached.add(node.module.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level:
            pytest.fail("the generator uses a relative import, so it is inside the package")
    assert "intentguard" not in reached
    assert "policy" not in reached


def test_generation_is_reproducible() -> None:
    """A reported number that cannot be regenerated is an anecdote."""
    first = json.dumps(generator.generate(seed=7), sort_keys=True)
    second = json.dumps(generator.generate(seed=7), sort_keys=True)
    assert first == second


def test_a_different_seed_gives_a_different_set() -> None:
    assert generator.generate(seed=1) != generator.generate(seed=2)


def test_the_split_is_reproducible_from_the_seed() -> None:
    """Nobody can rerun until the holdout flatters.

    Assignment is stratified rather than hashed per case, so it is not stable
    against changing the mix. It is stable against rerunning, which is the
    property that matters: the seed is fixed in main().
    """
    first = {c["case_id"]: c["split"] for c in generator.generate(seed=11)}
    second = {c["case_id"]: c["split"] for c in generator.generate(seed=11)}
    assert first == second


def test_the_holdout_looks_like_the_slice_it_stands_in_for() -> None:
    """Hashing each id independently left the holdout nine points off on labels.

    A holdout whose composition differs from the training slice produces a
    number that describes neither, so it is stratified by kind and label.
    """
    train = Counter(c["label"] for c in CASES if c["split"] == "train")
    holdout = Counter(c["label"] for c in CASES if c["split"] == "holdout")
    train_n, holdout_n = sum(train.values()), sum(holdout.values())

    for label in set(train) | set(holdout):
        drift = abs(train[label] / train_n - holdout[label] / holdout_n)
        assert drift < 0.03, f"{label} differs by {drift:.1%} between the splits"


def test_every_kind_appears_in_the_holdout() -> None:
    """A kind absent from the holdout is a kind the final number says nothing about."""
    train_kinds = {c["kind"] for c in CASES if c["split"] == "train"}
    holdout_kinds = {c["kind"] for c in CASES if c["split"] == "holdout"}
    assert train_kinds == holdout_kinds


def test_the_holdout_is_about_a_fifth_and_disjoint() -> None:
    splits = Counter(case["split"] for case in CASES)
    assert set(splits) == {"train", "holdout"}
    share = splits["holdout"] / len(CASES)
    assert 0.15 <= share <= 0.25, f"holdout is {share:.0%} of the set"


def test_the_set_is_large_enough_to_mean_something() -> None:
    assert len(CASES) >= 1_000


def test_every_label_is_a_real_outcome() -> None:
    for case in CASES:
        assert case["label"] in {outcome.value for outcome in Outcome}


def test_all_three_outcomes_are_well_represented() -> None:
    counts = Counter(case["label"] for case in CASES)
    for outcome in Outcome:
        assert counts[outcome.value] >= 50, f"only {counts[outcome.value]} {outcome.value}"


def test_no_violation_kind_carries_only_one_label() -> None:
    """A set where every case of a kind is a violation cannot measure detection.

    "Block anything with a shipping line" would have scored perfectly on
    hidden_cost. Each violation kind is paired with a compliant offer of the
    same shape, so the benchmark measures discrimination rather than pattern
    matching.

    Four kinds are legitimately single-label and are named: valid and the two
    should-pass categories from the specification are all ALLOW by definition,
    and an unmodelled field is always an escalation.
    """
    single_by_definition = {"valid", "discount", "shipping_upgrade", "unmodelled"}
    by_kind: dict[str, set[str]] = {}
    for case in CASES:
        by_kind.setdefault(case["kind"], set()).add(case["label"])

    offenders = {
        kind: labels
        for kind, labels in by_kind.items()
        if len(labels) == 1 and kind not in single_by_definition
    }
    assert not offenders, f"kinds that cannot measure discrimination: {offenders}"


def test_the_set_is_not_mostly_violations() -> None:
    """A set that is nine tenths blocks makes a blocking detector look good."""
    labels = Counter(case["label"] for case in CASES)
    assert 0.35 <= labels["ALLOW"] / len(CASES) <= 0.6


def test_every_case_says_which_rule_it_exercises() -> None:
    """A disputed label should be a disputed reading of the spec, not a mystery."""
    for case in CASES:
        assert len(case["rationale"]) > 25, case["case_id"]


def test_case_ids_are_unique() -> None:
    ids = [case["case_id"] for case in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case", CASES[::37], ids=lambda c: c["case_id"])
def test_a_sample_of_cases_is_structurally_valid(case: dict) -> None:
    from datetime import UTC, datetime

    IntentLedger.model_validate({**case["ledger"], "created_at": datetime(2026, 9, 4, tzinfo=UTC)})
    if case["offer_carries_unknown_field"]:
        with pytest.raises(ValidationError):
            Offer.model_validate(case["offer"])
    else:
        Offer.model_validate(case["offer"])


def test_money_is_always_whole_paise() -> None:
    for case in CASES:
        amounts = [case["ledger"]["hard"]["max_total_paise"], case["offer"]["total_paise"]]
        amounts += [item["amount_paise"] for item in case["offer"]["line_items"]]
        for amount in amounts:
            assert isinstance(amount, int) and not isinstance(amount, bool), case["case_id"]


# --- injection twins ------------------------------------------------------


def test_an_injected_twin_differs_only_in_the_description() -> None:
    """The experiment means nothing if the injection also changed a price.

    A changed decision has to be attributable to the text and to nothing else.
    """
    by_id = {case["case_id"]: case for case in CASES}
    twins = [c for c in CASES if c.get("injection_of")]
    assert twins

    for twin in twins:
        original = by_id[twin["injection_of"]]
        assert twin["label"] == original["label"]
        assert twin["ledger"] == original["ledger"]

        left = dict(twin["offer"])
        right = dict(original["offer"])
        for field in ("raw_description", "offer_id"):
            left.pop(field, None)
            right.pop(field, None)
        assert left == right, f"{twin['case_id']} changed more than the description"


def test_every_twin_actually_carries_hostile_text() -> None:
    by_id = {case["case_id"]: case for case in CASES}
    for twin in (c for c in CASES if c.get("injection_of")):
        original = by_id[twin["injection_of"]]
        added = twin["offer"]["raw_description"]
        assert len(added) > len(original["offer"].get("raw_description", ""))


def test_injection_covers_allowed_cases_and_blocked_ones() -> None:
    """Twins only of blocked cases could not show that injection fails to flip an allow."""
    by_id = {case["case_id"]: case for case in CASES}
    labels = {by_id[c["injection_of"]]["label"] for c in CASES if c.get("injection_of")}
    assert {"ALLOW", "BLOCK"} <= labels


# --- boundaries -----------------------------------------------------------


def test_the_set_contains_the_spec_boundaries() -> None:
    """The only part of a self-generated set that can disagree for a good reason."""
    boundaries = [case for case in CASES if case["kind"] == "boundary"]
    assert len(boundaries) >= 150
    labels = Counter(case["label"] for case in boundaries)
    assert labels["ALLOW"] > 0 and labels["BLOCK"] > 0


def test_the_boundary_cases_sit_on_the_edge_rather_than_near_it() -> None:
    """A boundary case that is comfortably inside proves nothing about the edge."""
    at_ceiling = [c for c in CASES if "at_ceiling" in c["case_id"]]
    assert at_ceiling
    for case in at_ceiling:
        assert case["offer"]["total_paise"] == case["ledger"]["hard"]["max_total_paise"]

    one_over = [c for c in CASES if "one_over" in c["case_id"]]
    assert one_over
    for case in one_over:
        assert case["offer"]["total_paise"] == case["ledger"]["hard"]["max_total_paise"] + 1
