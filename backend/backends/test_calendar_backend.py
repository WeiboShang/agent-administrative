"""Calendar backend: the mock path, factory selection, and the safety contracts (offline).

No test contacts the real Google API — same posture as the LLM tests, which only ever
exercise pure helpers. What matters here is the two invariants the demo feature must not
violate: booking never raises, and the evaluated core never touches this code.
"""
from backend.backends.calendar_backend import (
    CalendarBackend,
    MockCalendarBackend,
    get_calendar_backend,
)

EVENT = {"title": "Sync", "date": "2026-07-07", "start": "14:00", "end": "15:00",
         "participants": ["bob"]}


def test_mock_backend_is_a_noop():
    assert MockCalendarBackend().book(EVENT, ["bob"]) == {"status": "skipped"}


def test_factory_defaults_to_mock(monkeypatch):
    from backend import config
    monkeypatch.setattr(config, "CALENDAR_BACKEND", "mock")
    assert isinstance(get_calendar_backend(), MockCalendarBackend)


def test_factory_selects_google_when_configured(monkeypatch):
    from backend import config
    from backend.backends.calendar_backend import GoogleCalendarBackend
    monkeypatch.setattr(config, "CALENDAR_BACKEND", "google")
    # constructed lazily — no credentials touched until book() is called
    assert isinstance(get_calendar_backend(), GoogleCalendarBackend)


def test_google_backend_returns_error_not_raises_when_credentials_missing(monkeypatch):
    from backend import config
    from backend.backends.calendar_backend import GoogleCalendarBackend
    monkeypatch.setattr(config, "GOOGLE_CALENDARS_PATH", "secrets/does_not_exist.json")
    b = GoogleCalendarBackend(token_path="secrets/nope_token.json",
                              client_secret_path="secrets/nope_secret.json",
                              calendars_path="secrets/does_not_exist.json")
    out = b.book(EVENT, ["bob"])
    assert out["status"] == "error" and "google_auth_setup" in out["error"]


def test_google_backend_updates_and_cancels_saved_remote_event():
    """Lifecycle operations target the CREATE event ID; they never insert a duplicate."""
    from backend.backends.calendar_backend import GoogleCalendarBackend

    calls = []

    class FakeRequest:
        def __init__(self, payload=None):
            self.payload = payload or {}

        def execute(self):
            return self.payload

    class FakeEvents:
        def update(self, **kwargs):
            calls.append(("update", kwargs))
            return FakeRequest({"id": kwargs["eventId"], "htmlLink": "https://updated"})

        def insert(self, **kwargs):
            calls.append(("insert", kwargs))
            return FakeRequest({"id": "new-event", "htmlLink": "https://inserted"})

        def delete(self, **kwargs):
            calls.append(("delete", kwargs))
            return FakeRequest()

    class FakeService:
        def events(self):
            return FakeEvents()

    backend = GoogleCalendarBackend(token_path="unused", client_secret_path="unused",
                                    calendars_path="unused")
    backend._service = FakeService()
    backend._calendar_ids = {"chen": "chen-calendar"}
    event = {
        **EVENT,
        "participants": ["chen"],
        "calendar_sync": {
            "status": "booked",
            "provider_events": {
                "chen": {
                    "calendar_id": "chen-calendar",
                    "event_id": "remote-123",
                    "html_link": "https://original",
                }
            },
        },
    }

    updated = backend.update(event, ["chen"])
    assert updated["status"] == "updated"
    assert calls[0][0] == "update"
    assert calls[0][1]["eventId"] == "remote-123"
    assert not any(call[0] == "insert" for call in calls)

    cancelled = backend.cancel(event, ["chen"])
    assert cancelled["status"] == "cancelled"
    assert calls[-1][0] == "delete"
    assert calls[-1][1]["eventId"] == "remote-123"


def test_execute_scheduling_still_books_locally_when_the_backend_raises(monkeypatch):
    """The never-blocks contract, enforced at the call site: a backend that raises must not
    fail the approval — the local record is the booking; the calendar write is a bonus."""
    from datetime import datetime

    import backend.backends.calendar_backend as cb
    from backend.backends.records import RecordStore
    from backend.fixtures import org
    from backend.workflows import scheduling

    class ExplodingBackend(CalendarBackend):
        def book(self, event, participant_ids):
            raise RuntimeError("simulated Google outage")

    # patched on the source module — execute_scheduling imports the factory from there
    monkeypatch.setattr(cb, "get_calendar_backend", lambda: ExplodingBackend())

    s = RecordStore(":memory:")
    org.seed_from_org(s)
    ev = {"title": "Sync", "organizer": "alice", "participants": ["chen"],
          "participant_names": ["Chen Wei"], "participant_details": [],
          "date": "2026-07-15", "time": "10:00", "duration_minutes": 60}
    res = scheduling.execute_scheduling(ev, s, decision="approve",
                                        now=datetime(2026, 7, 1, 9, 0))
    assert res["status"] == "booked"                       # approval survived
    assert res["calendar_backend"]["status"] == "error"    # and the fault was captured
    assert s.list("events", status="booked")               # the local record really exists


def test_execute_scheduling_syncs_reresolved_participant_ids():
    """Editable people arrive as names with stale IDs cleared; Google gets canonical IDs."""
    from datetime import datetime

    from backend.backends.records import RecordStore
    from backend.fixtures import org
    from backend.workflows import scheduling

    calls = []

    class SpyBackend(CalendarBackend):
        def book(self, event, participant_ids):
            calls.append((event, participant_ids))
            return {"status": "booked", "html_link": "https://calendar.test/event"}

    s = RecordStore(":memory:")
    org.seed_from_org(s)
    ev = {
        "title": "Vendor review",
        "organizer": "alice",
        "participants": [],
        "participant_names": ["Chen Wei", "Dana Okoro"],
        "date": "2026-08-19",
        "time": "11:00",
        "duration_minutes": 30,
    }
    res = scheduling.execute_scheduling(
        ev,
        s,
        decision="approve",
        now=datetime(2026, 8, 12, 9, 0),
        calendar_backend=SpyBackend(),
    )

    assert res["calendar_backend"]["status"] == "booked"
    assert len(calls) == 1
    synced_event, synced_ids = calls[0]
    assert synced_ids == ["chen", "dana"]
    assert synced_event["participants"] == ["chen", "dana"]


def test_smart_create_syncs_resolved_participants_at_interactive_api(monkeypatch):
    """Smart CREATE syncs at the router boundary while its evaluation core stays pure."""
    import asyncio

    import backend.backends.calendar_backend as cb
    from backend.routers import schedule as schedule_router

    calls = []

    class SpyBackend(CalendarBackend):
        def book(self, event, participant_ids):
            calls.append((event, participant_ids))
            return {"status": "booked", "html_link": "https://calendar.test/smart"}

    canonical_event = {
        "title": "Project meeting",
        "participants": ["alice", "chen"],
        "date": "2026-08-20",
        "start": "10:00",
        "end": "10:30",
    }
    monkeypatch.setattr(
        schedule_router,
        "lifecycle_mutation",
        lambda **_kwargs: {
            "status": "booked",
            "record_id": "evt-test-smart",
            "event": canonical_event,
        },
    )
    monkeypatch.setattr(cb, "get_calendar_backend", lambda: SpyBackend())

    req = schedule_router.SmartExecuteRequest(
        spec={
            "operation": "CREATE",
            "title": "Project meeting",
            "participants": ["alice", "chen"],
            "date": "2026-08-20",
            "time": "10:00",
            "duration_minutes": 30,
        },
        candidate={"date": "2026-08-20", "start": "10:00", "end": "10:30"},
        actor="alice",
        idempotency_key="smart-google-sync-test",
    )
    result = asyncio.run(schedule_router.smart_execute(req))

    assert result["calendar_backend"]["status"] == "booked"
    assert calls == [(canonical_event, ["alice", "chen"])]


def test_smart_lifecycle_core_has_no_external_calendar_call():
    """Evaluation calls the lifecycle function directly, so it must remain mock-only."""
    import inspect

    from backend.workflows import scheduling_lifecycle

    source = inspect.getsource(scheduling_lifecycle.lifecycle_mutation)
    assert "get_calendar_backend" not in source
    assert ".book(" not in source


def test_smart_provider_failure_preserves_remote_ids_for_retry(monkeypatch):
    import asyncio

    import backend.backends.calendar_backend as cb
    from backend.backends.records import RecordStore
    from backend.routers import schedule as schedule_router

    store = RecordStore(":memory:")
    existing = store.create("events", "event", {
        "title": "Project meeting",
        "participants": ["chen"],
        "date": "2026-08-20",
        "start": "10:00",
        "end": "10:30",
        "calendar_sync": {
            "status": "booked",
            "provider_events": {"chen": {"calendar_id": "cal", "event_id": "remote-1"}},
        },
    }, status="booked")

    class FailingBackend(MockCalendarBackend):
        def update(self, event, participant_ids):
            return {"status": "error", "error": "temporary outage"}

    monkeypatch.setattr(schedule_router, "store", store)
    monkeypatch.setattr(cb, "get_calendar_backend", lambda: FailingBackend())
    monkeypatch.setattr(schedule_router, "lifecycle_mutation", lambda **_kwargs: {
        "status": "reschedule",
        "record_id": existing.id,
        "event": store.get(existing.id).data,
    })
    req = schedule_router.SmartExecuteRequest(
        spec={"operation": "RESCHEDULE", "target_event_id": existing.id},
        actor="alice",
        idempotency_key="provider-retry-state",
    )
    result = asyncio.run(schedule_router.smart_execute(req))
    assert result["calendar_backend"]["status"] == "error"
    saved = store.get(existing.id).data["calendar_sync"]
    assert saved["provider_events"]["chen"]["event_id"] == "remote-1"
    assert saved["error"] == "temporary outage"


def test_evaluation_harness_never_reaches_the_calendar_backend():
    """Reproducibility invariant (CLAUDE.md §3.4): the WF2 scorer scores validate_scheduling
    directly and must never call execute_scheduling, which is the only booking path."""
    import inspect

    from backend.evals import scheduling_score
    src = inspect.getsource(scheduling_score)
    assert "execute_scheduling" not in src
    assert "calendar_backend" not in src
