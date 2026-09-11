"""WF1 route/dismiss idempotency guards (offline — actions injected, no LLM).

Routing writes a downstream draft, so these endpoints must be idempotent: a double-click
must not duplicate the draft, a routed action must not be relabelled dismissed, and
re-triage must not reset handled actions back to pending.
"""
import pytest
from backend.testing import ASGITestClient as TestClient

from backend.main import app
from backend.routers._store import store

MEETING = {"action_type": "schedule_meeting", "confidence": 0.9, "status": "pending",
           "source_span": "", "rationale": "",
           "seed_fields": {"title": "Sync", "participants": ["Bob Rivera", "Chen Wei"],
                           "date": "2026-07-09", "time": "10:00", "duration_minutes": 30}}


@pytest.fixture
def client():
    return TestClient(app)


def _thread_with(action: dict) -> str:
    """Seed a fresh thread carrying one detected action (skips the LLM triage step)."""
    rec = store.create("threads", "thread",
                       {"source": "chat", "subject": "t", "raw_text": "Alice: hi",
                        "detected_actions": [dict(action)]}, status="in_review")
    return rec.id


def _action_body(client, tid: str, *, expected_version: int | None = None) -> dict:
    thread = next(
        item for item in client.get("/api/inbox/threads").json()["threads"]
        if item["id"] == tid
    )
    action = thread["detected_actions"][0]
    return {
        "thread_id": tid, "action_id": action["action_id"],
        "expected_version": expected_version or action["version"],
    }


def test_precontract_action_is_projected_to_canonical_schema(client):
    tid = _thread_with(MEETING)
    first = _action_body(client, tid)
    second = _action_body(client, tid)
    assert first == second and first["expected_version"] == 1
    threads = client.get("/api/inbox/threads").json()["threads"]
    thread = next(
        item for item in threads if item["id"] == tid
    )
    action = thread["detected_actions"][0]
    assert action["operation"] == "create" and action["version"] == 1
    assert action["model_seed_fields"] == MEETING["seed_fields"]
    assert action["current_seed_fields"] == MEETING["seed_fields"]
    assert {"confidence", "seed_fields", "source_span"}.isdisjoint(action)


def test_route_twice_creates_one_draft_and_does_not_book(client):
    tid = _thread_with(MEETING)
    events_before = len(store.list("events"))
    booked_before = len(store.list("events", status="booked"))
    body = _action_body(client, tid)
    first = client.post("/api/inbox/route", json=body).json()
    second = client.post("/api/inbox/route", json=body).json()
    assert first["status"] == "pending_review"
    assert second["status"] == "already_handled"
    assert len(store.list("events")) - events_before == 1
    assert len(store.list("events", status="booked")) == booked_before
    draft = store.get(first["record_id"])
    assert draft.type == "schedule_meeting"
    assert draft.status == "pending_review"
    assert first["action_id"] == body["action_id"] and first["version"] == 2
    assert draft.data["origin"]["action_id"] == body["action_id"]
    assert draft.data["origin"]["action_version"] == 1
    assert draft.data["origin"]["source_message_ids"] == []
    assert second["record_id"] == first["record_id"]


def test_needs_input_draft_is_routed_once_without_booking(client):
    incomplete = {
        **MEETING,
        "seed_fields": {k: v for k, v in MEETING["seed_fields"].items() if k != "time"},
    }
    tid = _thread_with(incomplete)
    events_before = len(store.list("events"))
    booked_before = len(store.list("events", status="booked"))

    body = _action_body(client, tid)
    first = client.post("/api/inbox/route", json=body).json()
    second = client.post("/api/inbox/route", json=body).json()

    assert first["status"] == "needs_input"
    assert first["missing"] == ["time"]
    assert second["status"] == "already_handled"
    assert second["action_status"] == "routed"
    assert second["record_id"] == first["record_id"]
    assert len(store.list("events")) - events_before == 1
    assert len(store.list("events", status="booked")) == booked_before
    assert store.get(first["record_id"]).status == "needs_input"
    thread = store.get(tid)
    assert thread.status == "resolved"
    assert thread.data["detected_actions"][0]["routed_to"] == first["record_id"]


def test_routed_action_cannot_be_dismissed(client):
    tid = _thread_with(MEETING)
    body = _action_body(client, tid)
    client.post("/api/inbox/route", json=body)
    res = client.post("/api/inbox/dismiss", json=body).json()
    assert res["status"] == "already_handled"
    assert store.get(tid).data["detected_actions"][0]["status"] == "routed"


def test_dismiss_twice_is_idempotent(client):
    tid = _thread_with(MEETING)
    body = _action_body(client, tid)
    assert client.post("/api/inbox/dismiss", json=body).json()["status"] == "dismissed"
    assert client.post("/api/inbox/dismiss", json=body).json()["status"] == "already_handled"


def test_retriage_preserves_handled_action_and_advances_cursor(client, monkeypatch):
    tid = _thread_with({**MEETING, "status": "routed"})
    monkeypatch.setattr(
        "backend.routers.inbox.llm_extract",
        lambda *args, **kwargs: {
            "summary": "Updated summary",
            "detected_actions": [{"action_type": "none", "confidence": 1.0}],
        },
    )

    res = client.post("/api/inbox/triage", json={"thread_id": tid})
    assert res.status_code == 200
    thread = store.get(tid)
    meeting = next(
        action for action in thread.data["detected_actions"]
        if action["action_type"] == "schedule_meeting"
    )
    assert meeting["status"] == "routed"
    assert thread.data["last_triaged_message_id"] == thread.data["messages"][-1]["message_id"]
    assert thread.data["audit_events"][-1]["action"] == "triage"


def test_unknown_action_id_returns_404(client):
    tid = _thread_with(MEETING)
    for path in ("/api/inbox/route", "/api/inbox/dismiss"):
        response = client.post(path, json={
            "thread_id": tid, "action_id": "act-missing", "expected_version": 1})
        assert response.status_code == 404


def test_stale_version_rejected_before_mutation(client):
    tid = _thread_with({**MEETING, "version": 2})
    events_before = len(store.list("events"))
    response = client.post("/api/inbox/route", json=_action_body(
        client, tid, expected_version=1))
    assert response.status_code == 409
    assert "stale_version" in response.json()["detail"]
    assert len(store.list("events")) == events_before


def test_expected_version_is_required(client):
    tid = _thread_with(MEETING)
    body = _action_body(client, tid)
    body.pop("expected_version")
    for path in ("/api/inbox/route", "/api/inbox/dismiss"):
        assert client.post(path, json=body).status_code == 422


# ── relative dates resolve against the thread's arrival time, not the reader's clock ──
def _meeting_thread(received_at, date_phrase="next Tuesday") -> str:
    act = {**MEETING, "seed_fields": {**MEETING["seed_fields"], "date": date_phrase}}
    data = {"source": "chat", "subject": "t", "raw_text": "Alice: hi",
            "detected_actions": [act]}
    if received_at is not None:
        data["received_at"] = received_at
    return store.create("threads", "thread", data, status="in_review").id


def _route_date(client, tid: str):
    res = client.post("/api/inbox/route", json=_action_body(client, tid)).json()
    return store.get(res["record_id"]).data["date"]


def test_relative_date_resolves_against_thread_arrival(client):
    """Same words, different arrival → different date. A thread read a week late must not
    silently shift its meeting by a week."""
    fresh = _route_date(client, _meeting_thread("2026-06-30T08:15"))   # a Tuesday
    stale = _route_date(client, _meeting_thread("2026-06-23T10:00"))   # a week earlier
    assert fresh == "2026-07-07"
    assert stale == "2026-06-30"
    assert fresh != stale


def test_thread_without_timestamp_falls_back_to_demo_now(client):
    assert _route_date(client, _meeting_thread(None)) == "2026-07-07"


def test_unparseable_timestamp_falls_back_rather_than_crashing(client):
    assert _route_date(client, _meeting_thread("not-a-date")) == "2026-07-07"


def test_seed_q3_thread_keeps_the_flagship_conflict_basis():
    """The Q3 thread's 'next Tuesday' must still land on Bob's seeded busy slot."""
    from backend.routers.inbox import thread_now
    from backend.workflows.scheduling import resolve_relative_date
    q3 = next(r for r in store.list("threads") if r.data.get("subject") == "Q3 budget review")
    assert resolve_relative_date("next Tuesday", thread_now(q3)) == "2026-07-07"
