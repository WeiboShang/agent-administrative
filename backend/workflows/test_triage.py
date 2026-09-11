"""Tests for the WF1 triage core (offline - no LLM; gold extractions fed in)."""

from datetime import datetime

from backend.backends.records import RecordStore
from backend.fixtures import org
from backend.workflows.triage import route_action, validate_triage

NOW = datetime(2026, 6, 30, 9, 0)


def _seeded() -> RecordStore:
    s = RecordStore(":memory:")
    org.seed_from_org(s)
    return s


def test_validate_keeps_supported_actions_and_drops_none_noise():
    out = validate_triage(
        {
            "summary": "s",
            "detected_actions": [
                {
                    "action_type": "schedule_meeting",
                    "confidence": 0.9,
                    "seed_fields": {"title": "x"},
                },
                {"action_type": "expense_claim", "confidence": 0.8},
                {
                    "action_type": "none",
                    "confidence": 0.5,
                },  # noise next to a real action -> dropped
            ],
        }
    )
    kinds = [a["action_type"] for a in out["detected_actions"]]
    assert kinds == ["schedule_meeting", "expense_claim"]
    assert all(a["status"] == "proposed" for a in out["detected_actions"])


def test_validate_keeps_lone_none_for_fyi_threads():
    out = validate_triage(
        {
            "summary": "s",
            "detected_actions": [
                {"action_type": "none", "confidence": 0.6},
            ],
        }
    )
    assert [a["action_type"] for a in out["detected_actions"]] == ["none"]


def test_route_schedule_meeting_creates_pending_review_draft_without_booking(
    monkeypatch,
):
    s = _seeded()
    booked_before = len(s.list("events", status="booked"))

    def fail_if_executed(*args, **kwargs):
        raise AssertionError("WF1 routing must not execute or book a meeting")

    monkeypatch.setattr(
        "backend.workflows.scheduling.execute_scheduling", fail_if_executed
    )
    action = {
        "action_type": "schedule_meeting",
        "current_seed_fields": {
            "title": "Budget sync",
            "participants": ["bob"],
            "date": "2026-07-09",
            "time": "10:00",
        },
    }
    res = route_action(action, s, now=NOW, acting_user="alice", thread_id="thr-1")
    assert res["routed"] == "calendar" and res["status"] == "pending_review"
    ev = s.get(res["record_id"])
    assert ev.type == "schedule_meeting" and ev.status == "pending_review"
    assert ev.data["organizer"] == "alice" and ev.data["origin"]["thread_id"] == "thr-1"
    assert ev.data["missing_required"] == []
    assert len(s.list("events", status="booked")) == booked_before


def test_route_schedule_missing_slot_creates_needs_input_draft():
    s = _seeded()
    booked_before = len(s.list("events", status="booked"))
    action = {
        "action_type": "schedule_meeting",
        "current_seed_fields": {"title": "Sync", "participants": ["bob"], "date": "2026-07-09"},
    }  # no time
    res = route_action(action, s, now=NOW, acting_user="alice", thread_id="thr-1")
    assert res["status"] == "needs_input" and "time" in res["missing"]
    ev = s.get(res["record_id"])
    assert ev.type == "schedule_meeting" and ev.status == "needs_input"
    assert ev.data["missing_required"] == ["time"]
    assert len(s.list("events", status="booked")) == booked_before


def test_route_expense_with_receipt_creates_pending_extraction_draft():
    s = _seeded()
    action = {
        "action_id": "act-expense-1",
        "version": 1,
        "action_type": "expense_claim",
        "current_seed_fields": {
            "employee_name": "Alice Tan",
            "vendor": "CityRail",
            "date": "2026-06-29",
            "amount": 48,
            "currency": "GBP",
            "category": "travel",
            "business_purpose": "Client workshop",
        },
        "attachment_ids": ["att-1"],
        "source_evidence": [
            {"message_id": "msg-1", "span": "Please reimburse", "grounded": True}
        ],
    }
    attachments = [
        {"attachment_id": "att-1", "filename": "receipt.png", "mime_type": "image/png"}
    ]
    res = route_action(
        action,
        s,
        now=NOW,
        acting_user="alice",
        thread_id="thr-2",
        attachments=attachments,
    )
    assert res["routed"] == "expenses" and res["status"] == "pending_extraction"
    rec = s.get(res["record_id"])
    assert rec.type == "expense_claim" and rec.status == "pending_extraction"
    assert rec.data["submitted_by"] == "alice"
    assert rec.data["origin"] == {
        "workflow": "wf1",
        "thread_id": "thr-2",
        "action_id": "act-expense-1",
        "action_version": 1,
        "source_message_ids": ["msg-1"],
        "source_path": "/inbox?thread=thr-2&action=act-expense-1",
    }
    assert rec.data["evidence_refs"][0]["attachment_id"] == "att-1"
    assert rec.data["extraction_snapshot"] is None
    assert rec.data["submitted_snapshot"] is None


def test_route_expense_without_evidence_creates_needs_evidence_draft():
    s = _seeded()
    action = {
        "action_id": "act-expense-2",
        "version": 1,
        "action_type": "expense_claim",
        "current_seed_fields": {
            "employee_name": "Alice Tan", "amount": 48, "currency": "GBP"
        },
    }
    res = route_action(action, s, now=NOW, acting_user="alice", thread_id="thr-3")
    assert res["routed"] == "expenses" and res["status"] == "needs_evidence"
    assert res["missing"] == ["receipt_or_alternative_evidence"]
    rec = s.get(res["record_id"])
    assert rec.status == "needs_evidence"
    assert rec.data["evidence_refs"] == []


def test_leave_is_not_routable_from_wf1():
    s = _seeded()
    submissions_before = len(s.list("submissions"))
    action = {
        "action_type": "leave_request",
        "seed_fields": {
            "employee_name": "Alice Tan",
            "start_date": "2026-08-03",
            "end_date": "2026-08-05",
            "leave_type": "annual",
        },
    }
    res = route_action(action, s, now=NOW, acting_user="alice", thread_id="thr-4")
    assert res == {"routed": "none", "status": "not_routable"}
    assert len(s.list("submissions")) == submissions_before
