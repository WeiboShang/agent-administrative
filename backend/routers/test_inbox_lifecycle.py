"""WF1 API lifecycle tests for messages, editable actions, memos and archive guards."""

import pytest
from backend.testing import ASGITestClient as TestClient

from backend.main import app
from backend.routers._store import store


@pytest.fixture
def client():
    return TestClient(app)


def _thread(*, with_action: bool = False) -> str:
    actions = []
    if with_action:
        actions.append({
            "action_type": "schedule_meeting",
            "status": "proposed",
            "seed_fields": {
                "title": "Budget review",
                "participants": ["Bob Rivera"],
                "date": "2026-07-07",
                "time": "10:00",
            },
        })
    return store.create(
        "threads",
        "thread",
        {
            "source": "chat",
            "subject": "WF1 lifecycle test",
            "raw_text": "Alice: Initial request",
            "detected_actions": actions,
        },
        status="in_review",
    ).id


def _listed_thread(client: TestClient, thread_id: str) -> dict:
    return next(
        item for item in client.get("/api/inbox/threads").json()["threads"]
        if item["id"] == thread_id
    )


def test_append_message_marks_thread_untriaged_and_keeps_attachment_reference(client):
    thread_id = _thread()
    response = client.post(
        f"/api/inbox/threads/{thread_id}/messages",
        json={
            "sender": "Alice",
            "body": "The receipt is attached",
            "attachment_ids": ["att-receipt-1"],
            "attachments": [{
                "attachment_id": "att-receipt-1",
                "filename": "receipt.png",
                "mime_type": "image/png",
            }],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "added"
    assert body["has_untriaged_messages"] is True
    assert body["message"]["attachment_ids"] == ["att-receipt-1"]

    thread = _listed_thread(client, thread_id)
    assert thread["has_untriaged_messages"] is True
    assert thread["messages"][-1]["message_id"].endswith("-002")
    assert thread["attachments"][0]["evidence_type"] == "receipt"


def test_edit_action_versions_snapshot_and_rejects_stale_write(client):
    thread_id = _thread(with_action=True)
    action = _listed_thread(client, thread_id)["detected_actions"][0]
    url = f"/api/inbox/threads/{thread_id}/actions/{action['action_id']}"

    edited = client.patch(url, json={
        "expected_version": action["version"],
        "fields": {"time": "11:00"},
        "reason": "participant requested a later slot",
    })
    assert edited.status_code == 200
    edited_action = edited.json()["action"]
    assert edited_action["status"] == "edited"
    assert edited_action["version"] == action["version"] + 1
    assert edited_action["current_seed_fields"]["time"] == "11:00"
    assert edited_action["previous_versions"][-1]["current_seed_fields"]["time"] == "10:00"

    stale = client.patch(url, json={
        "expected_version": action["version"],
        "fields": {"time": "12:00"},
    })
    assert stale.status_code == 409
    assert "stale_version" in stale.json()["detail"]


def test_memo_create_complete_reopen_and_dismiss_are_versioned(client):
    thread_id = _thread()
    created = client.post(
        f"/api/inbox/threads/{thread_id}/memos",
        json={"text": "Send the agenda", "resolved_date": "2026-07-06"},
    )
    assert created.status_code == 200
    memo = created.json()["memo"]
    url = f"/api/inbox/threads/{thread_id}/memos/{memo['memo_id']}"

    completed = client.patch(url, json={
        "expected_version": memo["version"],
        "is_completed": True,
    }).json()["memo"]
    assert completed["status"] == "completed"
    assert completed["is_completed"] is True

    reopened = client.patch(url, json={
        "expected_version": completed["version"],
        "is_completed": False,
    }).json()["memo"]
    assert reopened["status"] == "active"

    dismissed = client.patch(url, json={
        "expected_version": reopened["version"],
        "dismissed": True,
    }).json()["memo"]
    assert dismissed["status"] == "dismissed"
    assert dismissed["is_completed"] is False
    assert dismissed["version"] == memo["version"] + 3


def test_archive_blocks_pending_supported_action(client):
    thread_id = _thread(with_action=True)
    blocked = client.post("/api/inbox/archive", json={"thread_id": thread_id})
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "pending_actions_must_be_resolved"
    assert store.get(thread_id).status == "in_review"
