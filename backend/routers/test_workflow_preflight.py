"""Route-level preflight for the three workflows used in the live demonstration.

These tests deliberately cross router boundaries with one isolated RecordStore.  Unit
tests cover the individual policy helpers; this file proves that the HTTP contracts and
state transitions the React app uses still compose into complete workflows.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from backend.backends.records import RecordStore
from backend.fixtures import org
from backend.main import app
from backend.testing import ASGITestClient as TestClient


@pytest.fixture
def workspace(monkeypatch, tmp_path: Path) -> tuple[TestClient, RecordStore, Path]:
    from backend import config
    from backend.routers import expense, inbox, schedule
    from backend.workflows import expense_evidence

    store = RecordStore(":memory:")
    org.seed_from_org(store, today=date.today())
    monkeypatch.setattr(inbox, "store", store)
    monkeypatch.setattr(schedule, "store", store)
    monkeypatch.setattr(expense, "_store", store)
    monkeypatch.setattr(config, "CALENDAR_BACKEND", "mock")

    evidence_dir = tmp_path / "receipt_evidence"
    monkeypatch.setattr(expense_evidence, "EVIDENCE_DIR", evidence_dir)
    monkeypatch.setattr(expense, "EVIDENCE_DIR", evidence_dir)
    return TestClient(app), store, evidence_dir


def _future(days: int = 21) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _past(days: int = 2) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def test_wf1_meeting_handoff_can_be_reviewed_booked_and_archived(workspace):
    client, store, _ = workspace
    thread = store.create(
        "threads",
        "thread",
        {
            "source": "chat",
            "subject": "Tomorrow's stakeholder demo",
            "raw_text": "Alice: Book a demo with Chen at 15:30.",
            "detected_actions": [{
                "action_type": "schedule_meeting",
                "status": "proposed",
                "seed_fields": {
                    "title": "Stakeholder demo",
                    "participants": ["Chen Wei"],
                    "date": _future(),
                    "time": "15:30",
                    "duration_minutes": 30,
                },
            }],
        },
        status="in_review",
    )
    listed = next(
        row for row in client.get("/api/inbox/threads").json()["threads"]
        if row["id"] == thread.id
    )
    action = listed["detected_actions"][0]

    routed = client.post("/api/inbox/route", json={
        "thread_id": thread.id,
        "action_id": action["action_id"],
        "expected_version": action["version"],
        "acting_user": "alice",
    })
    assert routed.status_code == 200
    routed_body = routed.json()
    assert routed_body["status"] == "pending_review"
    draft_id = routed_body["record_id"]
    assert store.get(draft_id).status == "pending_review"

    review = client.get(f"/api/schedule/drafts/{draft_id}")
    assert review.status_code == 200
    assert review.json()["missing"] == []
    decided = client.post(f"/api/schedule/drafts/{draft_id}/decide", json={
        "event": review.json()["event"],
        "decision": "approve",
        "reviewed_by": "alice",
    })
    assert decided.status_code == 200
    assert decided.json()["status"] == "booked"
    assert store.get(draft_id).status == "booked"

    archived = client.post("/api/inbox/archive", json={
        "thread_id": thread.id,
        "acting_user": "alice",
    })
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"


def test_wf2_conflict_requires_confirmation_then_alternative_books(workspace, monkeypatch):
    client, store, _ = workspace
    from backend.routers import schedule

    busy = next(
        record for record in store.list("events", status="booked")
        if "bob" in record.data.get("participants", [])
    )
    extraction = {
        "title": "Conflict regression",
        "participants": ["Bob Rivera"],
        "date": busy.data["date"],
        "time": busy.data["start"],
        "duration_minutes": 30,
        "location": "Orion",
    }
    monkeypatch.setattr(schedule, "llm_extract", lambda *_args, **_kwargs: dict(extraction))

    checked = client.post("/api/schedule/run", json={
        "input_text": "meet Bob",
        "organizer": "alice",
    })
    assert checked.status_code == 200
    body = checked.json()
    assert any(flag["rule"] == "conflict" for flag in body["flags"])
    assert body["alternatives"]

    before = len(store.list("events", status="booked"))
    blocked = client.post("/api/schedule/decide", json={
        "event": body["event"],
        "decision": "approve",
    })
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "requires_override_confirmation"
    assert len(store.list("events", status="booked")) == before

    alternative = body["alternatives"][0]
    moved = {
        **body["event"],
        "date": alternative["date"],
        "time": alternative["start"],
        "start": alternative["start"],
        "end": alternative["end"],
    }
    booked = client.post("/api/schedule/decide", json={
        "event": moved,
        "decision": "approve",
        "changed_fields": ["date", "time"],
    })
    assert booked.status_code == 200
    assert booked.json()["status"] == "booked"
    assert len(store.list("events", status="booked")) == before + 1

    invalid = client.post("/api/schedule/decide", json={
        "event": moved,
        "decision": "accidentally-book",
    })
    assert invalid.status_code == 422


def test_wf2_smart_create_is_canonical_idempotent_and_cancellable(workspace):
    client, store, _ = workspace
    spec = {
        "operation": "CREATE",
        "title": "Multi-person demo",
        "participants": ["alice", "chen"],
        "duration_minutes": 30,
        "date_window": {"start": _future(28), "end": _future(28)},
        "location": "Lyra",
    }
    candidates = client.post("/api/schedule/smart/candidates", json={
        "spec": spec,
        "actor": "alice",
    })
    assert candidates.status_code == 200
    candidate_body = candidates.json()
    assert len(candidate_body["candidates"]) == 3

    payload = {
        "spec": candidate_body["spec"],
        "candidate": candidate_body["candidates"][0],
        "actor": "alice",
        "idempotency_key": "preflight-smart-create",
        "validation_token": candidate_body["validation_token"],
        "calendar_version": candidate_body["calendar_version"],
    }
    created = client.post("/api/schedule/smart/execute", json=payload)
    assert created.status_code == 200
    result = created.json()
    assert result["status"] == "booked"
    record = store.get(result["record_id"])
    assert record.data["participants"] == ["alice", "chen"]
    assert [item["name"] for item in record.data["participant_details"]] == [
        "Alice Tan", "Chen Wei",
    ]
    assert record.data["calendar_sync"]["status"] == "skipped"
    calendar_row = next(
        row for row in client.get("/api/schedule/calendar").json()["events"]
        if row["id"] == record.id
    )
    assert calendar_row["duration_minutes"] == 30

    replay = client.post("/api/schedule/smart/execute", json=payload)
    assert replay.json() == {"status": "idempotent_replay", "record_id": record.id}

    reschedule_spec = {
        "operation": "RESCHEDULE",
        "target_event_id": record.id,
        "title": record.data["title"],
        "participants": ["alice", "chen"],
        "duration_minutes": 30,
        "date_window": {"start": _future(29), "end": _future(29)},
        "location": "Lyra",
    }
    new_candidates = client.post("/api/schedule/smart/candidates", json={
        "spec": reschedule_spec,
        "actor": "alice",
    }).json()
    rescheduled = client.post("/api/schedule/smart/execute", json={
        "spec": new_candidates["spec"],
        "candidate": new_candidates["candidates"][0],
        "actor": "alice",
        "idempotency_key": "preflight-smart-reschedule",
        "validation_token": new_candidates["validation_token"],
        "calendar_version": new_candidates["calendar_version"],
    })
    assert rescheduled.status_code == 200
    assert rescheduled.json()["status"] == "reschedule"
    record = store.get(record.id)
    assert record.data["date"] == _future(29)
    assert [item["name"] for item in record.data["participant_details"]] == [
        "Alice Tan", "Chen Wei",
    ]

    cancelled = client.post("/api/schedule/smart/execute", json={
        "spec": {"operation": "CANCEL", "target_event_id": record.id},
        "actor": "alice",
        "idempotency_key": "preflight-smart-cancel",
        "reason": "preflight lifecycle check",
    })
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert store.get(record.id).status == "cancelled"


def test_wf3_evidence_revision_approval_and_ledger_complete(workspace):
    client, store, _ = workspace
    from backend.workflows.expense_evidence import persist_receipt

    sample = Path("docs/baselines/gate0-c9404d6/_expenses.png").read_bytes()
    evidence = persist_receipt(sample, mime_type="image/png", filename="receipt.png")
    fields = {
        "employee_name": "Alice Tan",
        "department": "Product",
        "vendor": "Preflight Café",
        "date": _past(2),
        "amount": 20.0,
        "currency": "GBP",
        "payment_method": "corporate_card",
        "category": "meals",
        "business_purpose": "Stakeholder demonstration",
        "image_phash": evidence["image_phash"],
    }
    extraction = {
        "vendor": fields["vendor"],
        "date": fields["date"],
        "amount": fields["amount"],
        "currency": fields["currency"],
    }
    submitted = client.post("/api/expense/evidence/submit", json={
        "fields": fields,
        "extraction_snapshot": extraction,
        "critical_second_read": extraction,
        "evidence": evidence,
        "submitted_by": "alice",
        "changed_fields": [],
        "idempotency_key": "preflight-expense-submit",
    })
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"
    record_id = submitted.json()["record_id"]

    self_approval = client.post(f"/api/expense/claims/{record_id}/decision", json={
        "decision": "approve",
        "reviewed_by": "alice",
        "expected_version": 1,
        "acknowledged_flags": [],
        "idempotency_key": "preflight-self-approval",
    })
    assert self_approval.json()["status"] == "self_approval_blocked"

    requested = client.post(
        f"/api/expense/claims/{record_id}/request-information",
        json={
            "reviewed_by": "chen",
            "expected_version": 1,
            "issues": ["Clarify the business purpose"],
            "request_text": "Please add the stakeholder meeting context.",
            "idempotency_key": "preflight-expense-request",
        },
    )
    assert requested.json()["status"] == "needs_information"
    assert requested.json()["version"] == 2

    revised_fields = {**fields, "business_purpose": "Lunch during stakeholder demo preparation"}
    resubmitted = client.post(f"/api/expense/claims/{record_id}/resubmit", json={
        "fields": revised_fields,
        "submitted_by": "alice",
        "expected_version": 2,
        "changed_fields": ["business_purpose"],
        "idempotency_key": "preflight-expense-resubmit",
    })
    assert resubmitted.json()["status"] == "resubmitted"
    assert resubmitted.json()["version"] == 3

    approved = client.post(f"/api/expense/claims/{record_id}/decision", json={
        "decision": "approve",
        "reviewed_by": "chen",
        "expected_version": 3,
        "acknowledged_flags": [],
        "idempotency_key": "preflight-expense-approve",
    })
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["version"] == 4
    assert store.get(record_id).status == "approved"

    queue_ids = {item["id"] for item in client.get("/api/expense/evidence/queue").json()["items"]}
    assert record_id not in queue_ids
    ledger = client.get("/api/expense/ledger").json()
    assert next(row for row in ledger["records"] if row["id"] == record_id)["status"] == "approved"
    # The no-thread ASGI test adapter intentionally cannot stream Starlette FileResponse
    # objects.  Verify the same route guard/path directly; browser smoke covers the actual
    # HTTP server's static/streaming response path.
    import asyncio
    from backend.routers import expense

    receipt_response = asyncio.run(expense.claim_receipt(record_id))
    assert Path(receipt_response.path).is_file()

    invalid = client.post(f"/api/expense/claims/{record_id}/decision", json={
        "decision": "maybe",
        "reviewed_by": "chen",
        "expected_version": 4,
        "acknowledged_flags": [],
        "idempotency_key": "preflight-invalid-decision",
    })
    assert invalid.status_code == 422
