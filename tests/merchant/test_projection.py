"""The stage 5 gate: no ceiling in the serialised merchant view.

A field-name check alone would be weak. The strong test is indistinguishability:
project two mandates that differ only in their ceiling and assert the serialised
views are byte-identical. If the ceiling cannot be recovered from the bytes, it
did not leak through any field, any derived value, or any encoding.
"""

from __future__ import annotations

import json

import pytest

from intentguard.core import Category, Condition, HardConstraints, SoftPreferences, from_rupees
from intentguard.merchant import NEVER_PROJECTED, MerchantView, project
from tests.fixtures import a_ledger


def ledger_with_ceiling(rupees: int):
    ledger = a_ledger()
    hard = HardConstraints.model_validate(
        {**ledger.hard.model_dump(), "max_total_paise": from_rupees(rupees)}
    )
    return ledger.model_copy(update={"hard": hard})


def test_the_view_has_no_field_that_could_hold_a_ceiling() -> None:
    for name in MerchantView.model_fields:
        assert "max_total" not in name
        assert not name.endswith("_paise"), name


def test_two_mandates_differing_only_in_ceiling_serialise_identically() -> None:
    """The real gate. If the bytes match, the number is not in them.

    Cheap, and it catches leaks a field-name check never would: a derived
    field, a rounded band, a length, an ordering that depends on the value.
    """
    cheap = project(ledger_with_ceiling(500)).model_dump_json()
    dear = project(ledger_with_ceiling(9_999_999)).model_dump_json()
    assert cheap == dear


# Values distinctive enough for a substring search to mean something. A one
# rupee ceiling renders as "1", which appears inside any identifier, and would
# fail this test for a reason that has nothing to do with leaking.
@pytest.mark.parametrize("rupees", [999, 5000, 47231, 123456, 9_999_999])
def test_no_rendering_of_the_ceiling_appears_anywhere_in_the_payload(rupees: int) -> None:
    """Search the bytes for the number in every form it could take."""
    serialised = project(ledger_with_ceiling(rupees)).model_dump_json()
    paise = from_rupees(rupees)
    for rendering in (str(paise), str(rupees), f"{rupees:,}", f"{paise:,}"):
        assert rendering not in serialised, f"{rendering} leaked into the merchant view"


def test_the_withheld_fields_are_absent_by_name() -> None:
    view = project(a_ledger())
    serialised = json.loads(view.model_dump_json())
    for field in NEVER_PROJECTED:
        assert field not in serialised


def test_confidence_is_not_projected() -> None:
    """Confidence is a hint about how firm the constraints are. That is leverage."""
    ledger = a_ledger(confidence={"max_total_paise": 0.31})
    assert "0.31" not in project(ledger).model_dump_json()


def test_the_raw_instruction_is_not_projected() -> None:
    """A user who writes "I could stretch to 6000" has stated a ceiling in prose."""
    ledger = a_ledger(raw_instruction="Buy shoes under 5000, I could stretch to 6000 at a push.")
    assert "6000" not in project(ledger).model_dump_json()
    assert "stretch" not in project(ledger).model_dump_json()


def test_the_merchant_still_learns_everything_it_needs_to_quote() -> None:
    """Bounded is not blind. A merchant that cannot quote is not a product."""
    ledger = a_ledger()
    view = project(ledger)
    assert view.category is Category.FOOTWEAR
    assert view.condition is Condition.NEW
    assert view.quantity == ledger.hard.quantity
    assert view.currency == "INR"
    assert view.recurring_permitted is False


def test_exclusions_reach_the_merchant() -> None:
    """Withholding an exclusion would produce blocks the merchant could have avoided."""
    ledger = a_ledger()
    hard = HardConstraints.model_validate({**ledger.hard.model_dump(), "exclusions": ("leather",)})
    view = project(ledger.model_copy(update={"hard": hard}))
    assert view.exclusions == ("leather",)


def test_soft_preferences_reach_the_merchant() -> None:
    ledger = a_ledger()
    ledger = ledger.model_copy(update={"soft": SoftPreferences(brand="Asics", colour="blue")})
    view = project(ledger)
    assert view.brand_preference == "Asics"
    assert view.colour_preference == "blue"


def test_the_projection_allows_fields_rather_than_removing_them() -> None:
    """A new constraint must be invisible until someone shares it on purpose.

    Any field added to HardConstraints that is not explicitly mapped here should
    stay out of the merchant's view. This asserts the mapping is a whitelist by
    checking that the view's field set is fixed and known.
    """
    assert set(MerchantView.model_fields) == {
        "intent_id",
        "category",
        "quantity",
        "quantity_mode",
        "currency",
        "condition",
        "recurring_permitted",
        "emi_permitted",
        "addons_permitted",
        "product_ref",
        "exclusions",
        "brand_preference",
        "colour_preference",
        "delivery_preference",
    }
