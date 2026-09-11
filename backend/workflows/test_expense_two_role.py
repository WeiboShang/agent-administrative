"""Tests for the WF3 two-role model — employee submit / approver decide (offline)."""
from backend.backends.records import RecordStore
from backend.fixtures import org
from backend.workflows.expense import decide_expense_evidence, submit_expense_evidence


def _seeded() -> RecordStore:
    s = RecordStore(":memory:")
    org.seed_from_org(s)
    return s


def _fields(**over):
    f = {"employee_name": "Alice Tan", "department": "Product", "vendor": "Café Aurora",
         "date": "2026-06-28", "amount": 30.0, "currency": "GBP", "category": "meals",
         "business_purpose": "Client lunch"}
    f.update(over)
    return f


def _submit(store, fields, *, submitted_by="alice", key="submit", changed_fields=None):
    return submit_expense_evidence(
        fields, store, submitted_by=submitted_by, changed_fields=changed_fields,
        extraction_snapshot=fields, second_read=fields, idempotency_key=key,
    )


def _decide(store, record_id, *, decision="approve", reviewed_by="chen", key="decide",
            reason=None, acknowledged_flags=None):
    record = store.get(record_id)
    return decide_expense_evidence(
        record_id, store, decision=decision, reviewed_by=reviewed_by,
        expected_version=int(record.data.get("version") or 1), reason=reason,
        acknowledged_flags=acknowledged_flags or [], idempotency_key=key,
    )


def test_approver_role_config():
    assert org.is_expense_approver("chen") and org.is_expense_approver("fiona")
    assert not org.is_expense_approver("alice")


def test_submit_creates_pending_claim():
    s = _seeded()
    res = _submit(s, _fields(), changed_fields=["category"])
    assert res["status"] == "submitted"
    rec = s.get(res["record_id"])
    assert rec.status == "submitted" and rec.data["submitted_by"] == "alice"


def test_submit_blocked_by_missing_required():
    s = _seeded()
    f = _fields()
    del f["business_purpose"]
    assert _submit(s, f)["status"] == "blocked_missing_required"


def test_approver_approves_someone_elses_claim():
    s = _seeded()
    rid = _submit(s, _fields())["record_id"]
    res = _decide(s, rid)   # Finance approves
    assert res["status"] == "approved"
    assert s.get(rid).data["reviewed_by"] == "chen"


def test_cannot_approve_your_own_submission():
    s = _seeded()
    rid = _submit(s, _fields(employee_name="Chen Wei"), submitted_by="chen")["record_id"]
    assert _decide(s, rid, reviewed_by="chen")["status"] \
        == "self_approval_blocked"


def test_approve_blocked_by_hard_policy_duplicate():
    s = _seeded()
    dup = _fields(employee_name="Bob Rivera", department="Engineering", vendor="CityCab",
                  date="2026-06-22", amount=24.0, category="travel")   # matches a seed
    rid = _submit(s, dup, submitted_by="bob")["record_id"]
    assert _decide(s, rid)["status"] \
        == "blocked_policy"


def test_reject_records_reviewer_and_reason():
    s = _seeded()
    rid = _submit(s, _fields())["record_id"]
    res = _decide(s, rid, decision="reject", reviewed_by="fiona", reason="personal")
    assert res["status"] == "rejected"
    rec = s.get(rid)
    assert rec.data["reviewed_by"] == "fiona" and rec.data["decision_reason"] == "personal"


def test_decide_on_non_pending_is_noop():
    s = _seeded()
    rid = _submit(s, _fields())["record_id"]
    _decide(s, rid)
    assert _decide(s, rid, reviewed_by="fiona", key="second-decision")["status"] == "not_pending"


def test_legacy_record_without_snapshot_cannot_approve_missing_fields():
    s = _seeded()
    record = s.create("submissions", "expense_claim", {
        "submitted_by": "alice", "vendor": "Legacy Shop",
    }, status="submitted")
    result = _decide(s, record.id)
    assert result["status"] == "blocked_missing_required"
    assert s.get(record.id).status == "submitted"
