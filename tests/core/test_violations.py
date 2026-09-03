"""The frozen sixteen.

SPEC-DECISIONS.md freezes the violation list at stage 1 and requires an explicit
amendment to add one. This test is that rule made executable: the stage 2 gate
of "a test per violation code" means nothing if the list can quietly grow to
match whatever happened to get implemented.
"""

from __future__ import annotations

from intentguard.core import DEFAULT_OUTCOME, EXPLANATION_TEMPLATES, Outcome, ViolationCode

FROZEN_AT_STAGE_1 = {
    "TOTAL_EXCEEDS_MAX",
    "TOTAL_MISMATCH",
    "NEGATIVE_TOTAL",
    "CURRENCY_MISMATCH",
    "QUANTITY_MISMATCH",
    "RECURRING_NOT_AUTHORIZED",
    "EMI_NOT_AUTHORIZED",
    "ADDON_NOT_AUTHORIZED",
    "CONDITION_MISMATCH",
    "CATEGORY_MISMATCH",
    "PRODUCT_SUBSTITUTION",
    "LEDGER_EXPIRED",
    "LEDGER_ALREADY_SPENT",
    "UNMODELLED_FIELD",
    "LOW_CONFIDENCE",
    "UNCLASSIFIABLE_CONDITION",
}

ESCALATES = {"UNMODELLED_FIELD", "LOW_CONFIDENCE", "UNCLASSIFIABLE_CONDITION"}


def test_the_list_has_not_drifted() -> None:
    assert {code.value for code in ViolationCode} == FROZEN_AT_STAGE_1


def test_every_code_has_an_outcome() -> None:
    assert set(DEFAULT_OUTCOME) == set(ViolationCode)


def test_the_three_escalating_codes_escalate_and_the_rest_block() -> None:
    for code in ViolationCode:
        expected = Outcome.ESCALATE if code.value in ESCALATES else Outcome.BLOCK
        assert DEFAULT_OUTCOME[code] is expected, code


def test_every_code_has_an_explanation() -> None:
    assert set(EXPLANATION_TEMPLATES) == set(ViolationCode)


def test_explanations_are_written_for_a_person_not_a_developer() -> None:
    developer_words = ("null", "none", "exception", "traceback", "int", "schema", "parse")
    for code, template in EXPLANATION_TEMPLATES.items():
        lowered = template.lower()
        assert not any(f" {word} " in f" {lowered} " for word in developer_words), code
        assert template[0].isupper(), code
        assert template.rstrip().endswith("."), code


def test_explanation_placeholders_are_known() -> None:
    import string

    allowed = {"expected", "observed"}
    for code, template in EXPLANATION_TEMPLATES.items():
        used = {name for _, name, _, _ in string.Formatter().parse(template) if name}
        assert used <= allowed, (code, used)
