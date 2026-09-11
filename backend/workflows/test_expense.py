"""Tests for the WF3 expense validation core (offline — no LLM / no images).

(The submit/approve gate is covered in test_expense_two_role.py.)
"""
from backend.backends.records import RecordStore
from backend.fixtures import org
from backend.workflows import policy
from backend.workflows.expense import (
    decide_expense_evidence,
    submit_expense_evidence,
    validate_and_complete_expense,
)


def _seeded() -> RecordStore:
    s = RecordStore(":memory:")
    org.seed_from_org(s)
    return s


def _clean_fields(**over):
    f = {"employee_name": "Alice Tan", "vendor": "Café Aurora", "date": "2026-06-28",
         "amount": 30.0, "currency": "GBP", "category": "meals",
         "business_purpose": "Client lunch"}
    f.update(over)
    return f


# ── validate ──
def test_validate_clean():
    d = validate_and_complete_expense(_clean_fields(), _seeded())
    assert d.missing_required == []
    assert d.completeness == 1.0
    assert d.flags == []


def test_business_purpose_missing_is_flagged():
    fields = _clean_fields()
    del fields["business_purpose"]        # never on a receipt → must be filled by human
    d = validate_and_complete_expense(fields, _seeded())
    assert "business_purpose" in d.missing_required


def test_validate_surfaces_over_limit_hard():
    d = validate_and_complete_expense(_clean_fields(amount=85.0), _seeded())
    assert any(f.rule == "over_limit" and f.severity == "hard" for f in d.flags)

# ── budget consumption is derived from approved records ──
def test_approved_claim_consumes_budget():
    s = _seeded()
    before = policy.budget_remaining("Product", s)
    fields = _clean_fields(amount=30.0)
    sub = submit_expense_evidence(
        fields, s, submitted_by="alice", extraction_snapshot=fields,
        second_read=fields, idempotency_key="budget-submit",
    )
    decide_expense_evidence(
        sub["record_id"], s, decision="approve", reviewed_by="chen",
        expected_version=1, reason=None, acknowledged_flags=[],
        idempotency_key="budget-approve",
    )
    after = policy.budget_remaining("Product", s)
    assert after == before - 30.0
