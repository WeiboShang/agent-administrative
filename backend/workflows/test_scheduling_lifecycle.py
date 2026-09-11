"""Focused tests for WF2 candidate ranking and exact-time fallback."""

from datetime import datetime

from backend.backends.records import RecordStore
from backend.workflows.scheduling_lifecycle import (
    lifecycle_mutation,
    normalise_spec,
    recommend_candidates,
)


NOW = datetime(2026, 8, 11, 9, 0)


def _spec() -> dict:
    return normalise_spec(
        {
            "title": "Design review",
            "participants": ["Chen Wei", "Dana Okoro"],
            "date": "2026-08-18",
            "time": "10:00",
            "duration_minutes": 60,
            "location": "Orion",
        },
        now=NOW,
    )


def test_conflicted_exact_time_returns_ranked_alternatives():
    store = RecordStore(":memory:")
    store.create(
        "events",
        "event",
        {
            "date": "2026-08-18",
            "start": "10:00",
            "end": "11:00",
            "participants": ["chen"],
            "location": "Orion",
        },
        status="booked",
    )

    result = recommend_candidates(_spec(), store, now=NOW)

    assert len(result["candidates"]) == 3
    assert all(candidate["start"] != "10:00" for candidate in result["candidates"])
    assert result["blockers"] == ["requested_time_unavailable"]
    assert all(
        "requested_time_unavailable" in candidate["warning_codes"]
        for candidate in result["candidates"]
    )
    assert result["warnings"] == [
        {
            "code": "requested_slot_occupied",
            "message": (
                "The requested slot on 2026-08-18 at 10:00–11:00 is unavailable: "
                "one or more participants and the selected room are busy. "
                "The options below are available alternatives."
            ),
            "date": "2026-08-18",
            "start": "10:00",
            "end": "11:00",
            "reason_codes": ["participant_conflict", "room_conflict"],
        }
    ]


def test_available_exact_time_is_not_relaxed():
    result = recommend_candidates(_spec(), RecordStore(":memory:"), now=NOW)

    assert result["candidates"]
    assert all(candidate["start"] == "10:00" for candidate in result["candidates"])
    assert result["blockers"] == []
    assert result["warnings"] == []


def test_acting_organiser_is_included_in_availability_checks():
    store = RecordStore(":memory:")
    store.create(
        "events",
        "event",
        {
            "date": "2026-08-18",
            "start": "10:00",
            "end": "11:00",
            "participants": ["alice"],
            "location": None,
        },
        status="booked",
    )

    result = recommend_candidates(_spec(), store, now=NOW, actor="alice")

    assert result["warnings"][0]["reason_codes"] == ["participant_conflict"]
    assert all(candidate["start"] != "10:00" for candidate in result["candidates"])


def test_room_display_aliases_share_one_conflict_identity():
    store = RecordStore(":memory:")
    store.create(
        "events",
        "event",
        {
            "date": "2026-08-18",
            "start": "10:00",
            "end": "11:00",
            "participants": [],
            "location": "Orion room",
        },
        status="booked",
    )

    result = recommend_candidates(_spec(), store, now=NOW)

    assert result["warnings"][0]["reason_codes"] == ["room_conflict"]
    assert all(candidate["start"] != "10:00" for candidate in result["candidates"])


def test_flexible_window_warns_when_the_entered_slot_is_occupied():
    store = RecordStore(":memory:")
    store.create(
        "events",
        "event",
        {
            "date": "2026-08-18",
            "start": "10:00",
            "end": "11:00",
            "participants": ["chen"],
            "location": None,
        },
        status="booked",
    )
    spec = normalise_spec(
        {
            "title": "Design review",
            "participants": ["Chen Wei", "Dana Okoro"],
            "date_window": {"start": "2026-08-18", "end": "2026-08-20"},
            "exact_time": "10:00",
            "duration_minutes": 60,
        },
        now=NOW,
    )

    result = recommend_candidates(spec, store, now=NOW)

    # The exact time remains available on later days, so this used to return options with
    # no warning even though the slot explicitly entered for 18 August was occupied.
    assert result["candidates"]
    assert all(candidate["start"] == "10:00" for candidate in result["candidates"])
    assert all(candidate["date"] != "2026-08-18" for candidate in result["candidates"])
    assert result["blockers"] == ["requested_time_unavailable"]
    assert result["warnings"][0]["code"] == "requested_slot_occupied"
    assert result["warnings"][0]["reason_codes"] == ["participant_conflict"]


def test_smart_spec_keeps_exact_time_and_multiple_participants():
    spec = normalise_spec(
        {
            "title": "Project weekly meeting",
            "participants": ["alice", "bob", "chen"],
            "date_window": {"start": "2026-08-13", "end": "2026-08-13"},
            "exact_time": "15:30",
            "duration_minutes": 30,
        },
        now=NOW,
    )

    assert spec["participant_names"] == ["alice", "bob", "chen"]
    assert spec["exact_time"] == "15:30"
    result = recommend_candidates(spec, RecordStore(":memory:"), now=NOW)
    assert result["candidates"]
    assert all(candidate["start"] == "15:30" for candidate in result["candidates"])

    # Candidate responses return the canonical form and the execute endpoint normalises it
    # once more. That round trip must not discard participants or the requested time.
    round_tripped = normalise_spec(spec, now=NOW)
    assert round_tripped["participant_names"] == ["alice", "bob", "chen"]
    assert round_tripped["exact_time"] == "15:30"

    store = RecordStore(":memory:")
    options = recommend_candidates(round_tripped, store, now=NOW)
    booked = lifecycle_mutation(
        spec=round_tripped,
        candidate=options["candidates"][0],
        store=store,
        actor="alice",
        idempotency_key="multi-person-exact-time",
        validation_token=options["validation_token"],
        calendar_version=options["calendar_version"],
    )
    assert booked["status"] == "booked"
    assert booked["event"]["participants"] == ["alice", "bob", "chen"]
