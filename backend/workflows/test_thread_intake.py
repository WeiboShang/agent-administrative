"""Deterministic contract tests for WF1 thread intake and incremental reconciliation."""

from backend.workflows.thread_intake import (
    THREAD_SCHEMA_VERSION,
    ensure_thread_data,
    ground_action,
    migrate_thread_records,
    reconcile_actions,
    reconcile_memos,
    triage_text,
)


def test_legacy_thread_projection_has_stable_message_and_attachment_ids():
    raw = {
        "received_at": "2026-06-30T08:15:00",
        "raw_text": "Alice: Please review this\nBob: I will do it",
        "attachments": [{"filename": "receipt.png", "mime_type": "image/png"}],
    }
    first = ensure_thread_data(raw, thread_id="thr-9")
    second = ensure_thread_data(raw, thread_id="thr-9")

    assert [item["message_id"] for item in first["messages"]] == [
        "msg-thr-9-001",
        "msg-thr-9-002",
    ]
    assert first["messages"] == second["messages"]
    assert first["attachments"][0]["attachment_id"] == "att-thr-9-001"
    assert first["attachments"][0]["evidence_type"] == "receipt"
    assert first["thread_schema_version"] == THREAD_SCHEMA_VERSION


def test_thread_migration_persists_only_canonical_action_fields():
    from backend.backends.records import RecordStore

    store = RecordStore(":memory:")
    record = store.create("threads", "thread", {
        "raw_text": "Alice: Please schedule the review",
        "detected_actions": [{
            "action_type": "schedule_meeting",
            "confidence": 0.8,
            "seed_fields": {"title": "Review", "participants": ["Alice"]},
            "source_span": "schedule the review",
        }],
    }, status="pending")

    assert migrate_thread_records(store) == {"migrated": 1}
    assert migrate_thread_records(store) == {"migrated": 0}
    migrated = store.get(record.id).data
    action = migrated["detected_actions"][0]
    assert migrated["thread_schema_version"] == THREAD_SCHEMA_VERSION
    assert action["model_confidence"] == 0.8
    assert action["model_seed_fields"]["title"] == "Review"
    assert action["source_evidence"][0]["span"] == "schedule the review"
    assert {"confidence", "seed_fields", "source_span"}.isdisjoint(action)


def test_ground_action_flags_bad_evidence_and_removes_unknown_attachment():
    messages = [{
        "message_id": "msg-1",
        "sender": "Alice",
        "sent_at": None,
        "body": "Please arrange the budget meeting next Tuesday",
        "attachment_ids": ["att-1"],
    }]
    attachments = [{
        "attachment_id": "att-1",
        "filename": "agenda.pdf",
        "mime_type": "application/pdf",
    }]
    grounded = ground_action({
        "source_evidence": [
            {"message_id": "msg-1", "span": "budget meeting next Tuesday"},
            {"message_id": "msg-1", "span": "Friday at noon"},
        ],
        "field_sources": {
            "title": {"message_id": "msg-1", "span": "budget meeting"},
            "time": {"message_id": "msg-1", "span": "14:00"},
        },
        "attachment_ids": ["att-1", "att-missing"],
    }, messages=messages, attachments=attachments)

    assert [item["grounded"] for item in grounded["source_evidence"]] == [True, False]
    assert grounded["field_sources"]["title"]["grounded"] is True
    assert grounded["field_sources"]["time"]["grounded"] is False
    assert grounded["attachment_ids"] == ["att-1"]
    assert {flag["rule"] for flag in grounded["flags"]} == {
        "evidence_unresolved",
        "field_evidence_unresolved",
        "attachment_unresolved",
    }


def test_reconcile_create_dedupes_and_amend_increments_existing_version():
    existing = [{
        "action_id": "act-thr-1-001",
        "action_type": "schedule_meeting",
        "operation": "create",
        "version": 2,
        "status": "routed",
        "routed_to": "evt-1",
        "current_seed_fields": {
            "title": "Budget review",
            "participants": ["bob"],
            "date": "2026-07-07",
            "time": "10:00",
        },
        "source_evidence": [],
        "previous_versions": [],
    }]
    duplicate = {
        "action_type": "schedule_meeting",
        "operation": "create",
        "current_seed_fields": dict(existing[0]["current_seed_fields"]),
    }
    assert reconcile_actions(existing, [duplicate], thread_id="thr-1", at="now") == existing

    amendment = {
        "action_id": "proposal-id",
        "action_type": "schedule_meeting",
        "operation": "amend",
        "target_action_id": "act-thr-1-001",
        "version": 1,
        "model_seed_fields": {"time": "11:00"},
        "current_seed_fields": {"time": "11:00"},
        "source_evidence": [],
    }
    amended = reconcile_actions(existing, [amendment], thread_id="thr-1", at="later")[0]

    assert amended["action_id"] == "act-thr-1-001"
    assert amended["version"] == 3
    assert amended["current_seed_fields"]["time"] == "11:00"
    assert amended["target_record_id"] == "evt-1"
    assert amended["routed_to"] is None
    assert amended["previous_versions"][0]["version"] == 2


def test_reconcile_memos_dedupes_normalised_text_and_date():
    existing = [{
        "memo_id": "memo-1",
        "current_text": "Submit expense report",
        "resolved_date": "2026-07-03",
    }]
    proposals = [
        {"current_text": "  submit   EXPENSE report ", "resolved_date": "2026-07-03"},
        {"current_text": "Book project room", "resolved_date": "2026-07-04"},
    ]
    result = reconcile_memos(existing, proposals, thread_id="thr-1", at="now")

    assert len(result) == 2
    assert result[1]["memo_id"] == "memo-thr-1-002"
    assert result[1]["status"] == "active"


def test_triage_text_contains_only_new_messages_and_active_action_context():
    data = {
        "messages": [
            {
                "message_id": "msg-1",
                "sender": "Alice",
                "body": "Original request",
                "attachment_ids": [],
            },
            {
                "message_id": "msg-2",
                "sender": "Alice",
                "body": "Move it to 11:00",
                "attachment_ids": ["att-1"],
            },
        ],
        "last_triaged_message_id": "msg-1",
        "detected_actions": [{
            "action_id": "act-1",
            "action_type": "schedule_meeting",
            "status": "routed",
            "current_seed_fields": {"time": "10:00"},
        }],
    }
    text = triage_text(data)

    assert "Existing action state" in text
    assert "act-1" in text
    assert "Original request" not in text
    assert "[msg-2] Alice: Move it to 11:00 [attachments: att-1]" in text
