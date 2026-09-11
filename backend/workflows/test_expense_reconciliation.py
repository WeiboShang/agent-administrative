from __future__ import annotations

import inspect
from datetime import date

from backend.backends.records import RecordStore
from backend.workflows import expense_reconciliation
from backend.workflows.expense_reconciliation import reconcile_expense_evidence
from backend.workflows.expense_reconciliation import critical_read_triggers


def _store() -> RecordStore:
    return RecordStore(":memory:", now_fn=lambda: "2026-07-01T09:00:00+00:00")


def test_reconciliation_is_independent_from_evaluation_gold() -> None:
    source = inspect.getsource(expense_reconciliation)
    assert "backend.evals" not in source
    assert "receipt_category_gold" not in source


def test_line_items_override_an_incompatible_model_category() -> None:
    extraction = {
        "amount": 21.91,
        "line_items": [
            {"desc": "Parking", "amount": 11.47},
            {"desc": "Taxi fare", "amount": 10.44},
        ],
    }
    fields = {
        "vendor": "DeskSupplies Co", "date": "2026-06-25", "amount": 21.91,
        "currency": "GBP", "category": "supplies", "business_purpose": "Business expense",
    }
    reconciled, report = reconcile_expense_evidence(fields, extraction, _store())
    assert reconciled["category"] == "travel"
    assert report["changed_fields"] == ["category"]
    assert not report["requires_review"]


def test_reconciliation_keeps_the_auto_generated_purpose_consistent() -> None:
    extraction = {
        "amount": 21.91,
        "line_items": [{"desc": "Taxi fare", "amount": 21.91}],
    }
    fields = {
        "vendor": "DeskSupplies Co", "date": "2026-06-25", "amount": 21.91,
        "currency": "GBP", "category": "supplies", "business_purpose": "Office supplies",
    }
    reconciled, report = reconcile_expense_evidence(fields, extraction, _store())
    assert reconciled["category"] == "travel"
    assert reconciled["business_purpose"] == "Business travel"
    assert report["changed_fields"] == ["category", "business_purpose"]


def test_policy_sensitive_category_ambiguity_is_not_auto_resolved() -> None:
    extraction = {
        "amount": 85.0,
        "line_items": [{"desc": "Hotel breakfast", "amount": 85.0}],
    }
    fields = {
        "vendor": "Café Aurora", "date": "2026-06-25", "amount": 85.0,
        "currency": "GBP", "category": "accommodation",
        "business_purpose": "Business expense",
    }
    reconciled, report = reconcile_expense_evidence(fields, extraction, _store())
    assert reconciled["category"] == "accommodation"
    assert report["status"] == "policy_sensitive_ambiguity"
    assert report["requires_review"]


def test_generic_items_do_not_preserve_an_unsupported_meals_guess() -> None:
    extraction = {
        "amount": 25.44,
        "line_items": [{"desc": "Misc item", "amount": 25.44}],
    }
    fields = {
        "vendor": "BrightMart", "date": "2026-06-25", "amount": 25.44,
        "currency": "GBP", "category": "meals", "business_purpose": "Business expense",
    }
    reconciled, report = reconcile_expense_evidence(fields, extraction, _store())
    assert reconciled["category"] == "other"
    assert report["status"] == "reconciled"


def test_independent_read_fills_missing_fields_without_guessing() -> None:
    fields = {
        "vendor": None, "date": None, "amount": 24.0, "currency": "GBP",
        "category": "travel", "business_purpose": "Business travel",
    }
    extraction = {"amount": 24.0, "line_items": [{"desc": "Taxi fare", "amount": 24.0}]}
    second = {"vendor": "CityCab", "date": "2026-06-22", "amount": 24.0,
              "currency": "GBP"}
    reconciled, report = reconcile_expense_evidence(
        fields, extraction, _store(), second_read=second
    )
    assert reconciled["vendor"] == "CityCab"
    assert reconciled["date"] == "2026-06-22"
    assert not report["requires_review"]
    assert set(report["changed_fields"]) == {"vendor", "date"}


def test_independent_date_disagreement_requires_review() -> None:
    fields = {
        "vendor": "CityCab", "date": "2020-06-22", "amount": 24.0,
        "currency": "GBP", "category": "travel", "business_purpose": "Business travel",
    }
    extraction = {"amount": 24.0, "line_items": [{"desc": "Taxi fare", "amount": 24.0}]}
    second = {"vendor": "CityCab", "date": "2026-06-22", "amount": 24.0,
              "currency": "GBP"}
    reconciled, report = reconcile_expense_evidence(
        fields, extraction, _store(), second_read=second
    )
    assert reconciled["date"] == "2020-06-22"
    assert report["requires_review"]
    assert report["critical_conflicts"] == [
        {"field": "date", "primary": "2020-06-22", "critical": "2026-06-22"}
    ]


def test_clean_second_vendor_can_replace_an_obviously_corrupted_read() -> None:
    fields = {
        "vendor": "Caf☒ Aurora", "date": "2026-06-22", "amount": 24.0,
        "currency": "GBP", "category": "meals", "business_purpose": "Business meal",
    }
    extraction = {"amount": 24.0, "line_items": [{"desc": "Coffee", "amount": 24.0}]}
    second = {"vendor": "Café Aurora", "date": "2026-06-22", "amount": 24.0,
              "currency": "GBP"}
    reconciled, report = reconcile_expense_evidence(
        fields, extraction, _store(), second_read=second
    )
    assert reconciled["vendor"] == "Café Aurora"
    assert not report["requires_review"]
    assert "vendor" in report["changed_fields"]


def test_damaged_second_vendor_does_not_overrule_a_clean_primary_read() -> None:
    fields = {
        "vendor": "Café Aurora", "date": "2026-06-22", "amount": 24.0,
        "currency": "GBP", "category": "meals", "business_purpose": "Business meal",
    }
    extraction = {"amount": 24.0, "line_items": [{"desc": "Coffee", "amount": 24.0}]}
    second = {"vendor": "Caf☒ Aurora", "date": "2026-06-22", "amount": 24.0,
              "currency": "GBP"}
    reconciled, report = reconcile_expense_evidence(
        fields, extraction, _store(), second_read=second
    )
    assert reconciled["vendor"] == "Café Aurora"
    assert not report["requires_review"]
    assert "vendor" not in report["changed_fields"]


def test_critical_read_selection_uses_only_primary_extraction_risk() -> None:
    clean = {
        "vendor": "Café Aurora", "date": "2026-06-22", "amount": 24.0,
        "currency": "GBP",
        "field_confidence": {"vendor": 1.0, "date": 1.0, "amount": 1.0},
    }
    assert critical_read_triggers(clean, now=date(2026, 7, 1)) == ()
    stale = {**clean, "date": "2020-06-22"}
    assert "date_outlier:stale" in critical_read_triggers(
        stale, now=date(2026, 7, 1)
    )
    non_receipt = {"not_a_receipt": True, "vendor": None, "amount": None}
    assert critical_read_triggers(non_receipt, now=date(2026, 7, 1)) == ()
