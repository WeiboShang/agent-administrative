"""Tests for the WF3 deterministic core. Offline (no LLM)."""
import pytest
from backend.workflows.form_prefill import validate_and_complete_form


def test_complete_expense_claim():
    draft, missing, notes = validate_and_complete_form({
        "form_type": "expense_claim",
        "fields": {
            "employee_name": "Alice Tan", "vendor": "Cafe", "date": "2026-07-10",
            "amount": 12.5, "currency": "GBP", "category": "meals",
            "business_purpose": "Client lunch",
        },
    })
    assert draft.form_type == "expense_claim"
    assert missing == []
    assert draft.completeness == 1.0


def test_missing_required_field_flagged_not_invented():
    draft, missing, notes = validate_and_complete_form({
        "form_type": "expense_claim",
        "fields": {"employee_name": "Alice Tan", "vendor": "Cafe", "date": "2026-07-10",
                   "amount": 12.5, "currency": "GBP", "category": "meals"},
    })
    assert missing == ["business_purpose"]
    assert draft.fields.get("business_purpose") is None
    assert draft.completeness == 0.857


def test_optional_field_not_counted_as_missing():
    draft, missing, _ = validate_and_complete_form({
        "form_type": "expense_claim",
        "fields": {"employee_name": "Bob", "vendor": "Cafe", "date": "2026-07-10",
                   "amount": 12.5, "currency": "GBP", "category": "meals",
                   "business_purpose": "Team lunch"},  # optional fields omitted
    })
    assert missing == []
    assert draft.completeness == 1.0


def test_invalid_date_is_nulled_and_missing():
    draft, missing, notes = validate_and_complete_form({
        "form_type": "expense_claim",
        "fields": {"employee_name": "Alice", "vendor": "Cafe", "date": "next week",
                   "amount": 12.5, "currency": "GBP", "category": "meals",
                   "business_purpose": "Team lunch"},
    })
    assert "date" in missing
    assert draft.fields["date"] is None
    assert any("date" in n for n in notes)


def test_invalid_numeric_is_nulled_and_missing():
    draft, missing, notes = validate_and_complete_form({
        "form_type": "expense_claim",
        "fields": {"employee_name": "Chen", "amount": "a lot", "currency": "GBP",
                   "category": "travel", "date": "2026-07-01"},
    })
    assert "amount" in missing
    assert any("not a positive number" in n for n in notes)


def test_unclassified_form_type():
    draft, missing, notes = validate_and_complete_form({"form_type": "vacation", "fields": {}})
    assert draft.form_type is None
    assert missing == ["form_type"]
    assert draft.completeness == 0.0


# ── amounts must be positive: an approved negative claim inflated the budget ──
@pytest.mark.parametrize("bad", [-50.0, 0, -0.01, "null", "unknown", float("nan")])
def test_non_positive_or_unusable_amount_is_nulled_and_missing(bad):
    draft, missing, _ = validate_and_complete_form(
        {"form_type": "expense_claim",
         "fields": {"employee_name": "Alice Tan", "vendor": "X", "date": "2026-06-25",
                    "amount": bad, "currency": "GBP", "category": "meals",
                    "business_purpose": "x"}})
    assert draft.fields["amount"] is None
    assert "amount" in missing


def test_positive_amount_survives():
    draft, missing, _ = validate_and_complete_form(
        {"form_type": "expense_claim",
         "fields": {"employee_name": "Alice Tan", "vendor": "X", "date": "2026-06-25",
                    "amount": 12.5, "currency": "GBP", "category": "meals",
                    "business_purpose": "x"}})
    assert draft.fields["amount"] == 12.5 and missing == []


def test_stringy_null_in_a_required_text_field_counts_as_missing():
    """The vision model answers "null"/"N/A" on an unreadable receipt — that must not be
    stored as a vendor literally named "null"."""
    draft, missing, _ = validate_and_complete_form(
        {"form_type": "expense_claim",
         "fields": {"employee_name": "Alice Tan", "vendor": "null", "date": "2026-06-25",
                    "amount": 12.0, "currency": "GBP", "category": "meals",
                    "business_purpose": "N/A"}})
    assert "vendor" in missing and "business_purpose" in missing
