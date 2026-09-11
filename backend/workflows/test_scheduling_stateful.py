"""Tests for WF2 v2 — stateful-calendar scheduling (offline, no LLM)."""
import pytest
from datetime import datetime

from backend.backends.records import RecordStore
from backend.fixtures import org
from backend.workflows.scheduling import (
    execute_scheduling,
    to_ics,
    validate_scheduling,
)

NOW = datetime(2026, 6, 30, 9, 0)   # a Tuesday → "next Tuesday" resolves to 2026-07-07


def _seeded() -> RecordStore:
    s = RecordStore(":memory:")
    org.seed_from_org(s)
    return s


def _ext(**over):
    e = {"title": "Q3 sync", "participants": ["bob", "chen"], "date": "2026-07-07",
         "time": "15:00", "duration_minutes": 30}
    e.update(over)
    return e


# ── validate ──
def test_validate_clean_no_missing_no_flags():
    ev, missing, flags = validate_scheduling(_ext(), _seeded(), now=NOW)
    assert missing == []
    assert ev["date"] == "2026-07-07" and ev["participants"] == ["bob", "chen"]
    assert flags == []                       # 15:00–15:30 clears bob's 14:00–15:00 seed


def test_validate_resolves_next_weekday():
    ev, _, _ = validate_scheduling(_ext(date="next Tuesday"), _seeded(), now=NOW)
    assert ev["date"] == "2026-07-07"
    assert ev["slot_provenance"]["date"] == "inferred"


def test_validate_conflict_against_seed():
    ev, _, flags = validate_scheduling(_ext(time="14:30"), _seeded(), now=NOW)  # clashes bob
    assert any(f.rule == "conflict" for f in flags)


def test_validate_missing_time():
    _, missing, _ = validate_scheduling(_ext(time=None), _seeded(), now=NOW)
    assert "time" in missing


def test_validate_unknown_participant():
    _, _, flags = validate_scheduling(_ext(participants=["ghost"]), _seeded(), now=NOW)
    assert any(f.rule == "unknown_participant" for f in flags)


# ── execute ──
def test_approve_books_event_and_ics():
    s = _seeded()
    ev, _, _ = validate_scheduling(_ext(), s, now=NOW)
    res = execute_scheduling(ev, s, decision="approve")
    assert res["status"] == "booked"
    assert s.get(res["record_id"]).status == "booked"
    assert "SUMMARY:Q3 sync" in res["ics"] and "BEGIN:VEVENT" in res["ics"]
    assert len(res["notifications"]) == 2       # bob + chen


def test_approve_blocked_by_missing_time():
    s = _seeded()
    ev, _, _ = validate_scheduling(_ext(time=None), s, now=NOW)
    res = execute_scheduling(ev, s, decision="approve")
    assert res["status"] == "blocked_missing_required"
    assert "time" in res["missing"]


def test_plain_approve_with_conflict_requires_confirmation_and_does_not_write():
    s = _seeded()
    ev, _, _ = validate_scheduling(_ext(time="14:30"), s, now=NOW)   # bob conflict (soft)
    before = len(s.list("events"))
    provider_calls = []

    class ProviderSpy:
        def book(self, event, participant_ids):
            provider_calls.append((event, participant_ids))
            return {"status": "booked"}

    res = execute_scheduling(
        ev,
        s,
        decision="approve",
        calendar_backend=ProviderSpy(),
    )

    assert res["status"] == "requires_override_confirmation"
    assert any(f["rule"] == "conflict" for f in res["flags"])
    assert res["alternatives"]
    assert len(s.list("events")) == before
    assert provider_calls == []


def test_explicit_reasoned_conflict_override_books_and_records_audit():
    s = _seeded()
    ev, _, _ = validate_scheduling(_ext(time="14:30"), s, now=NOW)
    res = execute_scheduling(
        ev,
        s,
        decision="approve",
        override_soft_flags=True,
        override_reason="Both participants approved the overlap for this test.",
    )

    assert res["status"] == "booked"
    assert any(f["rule"] == "conflict" for f in res["overridden_flags"])
    assert s.get(res["record_id"]).data["override_reason"].startswith("Both participants")


def test_override_without_reason_is_still_blocked():
    s = _seeded()
    ev, _, _ = validate_scheduling(_ext(time="14:30"), s, now=NOW)
    before = len(s.list("events"))
    res = execute_scheduling(ev, s, decision="approve", override_soft_flags=True)

    assert res["status"] == "override_reason_required"
    assert len(s.list("events")) == before


def test_reject_logs_reason():
    s = _seeded()
    ev, _, _ = validate_scheduling(_ext(), s, now=NOW)
    res = execute_scheduling(ev, s, decision="reject", reason="clashes with board prep")
    assert res["status"] == "rejected"
    assert s.get(res["record_id"]).data["decision_reason"] == "clashes with board prep"


# ── the stateful property: today's approval affects tomorrow's validation ──
def test_booked_meeting_creates_a_future_conflict():
    s = _seeded()
    # book meeting A (alice, 2026-07-09 Thu 10:00–10:30 — no seed clash)
    a, _, fa = validate_scheduling(
        {"title": "A", "participants": ["alice"], "date": "2026-07-09", "time": "10:00"},
        s, now=NOW)
    assert not any(f.rule == "conflict" for f in fa)
    assert execute_scheduling(a, s, decision="approve")["status"] == "booked"
    # meeting B overlaps A → now conflicts against the just-booked event
    _, _, fb = validate_scheduling(
        {"title": "B", "participants": ["alice"], "date": "2026-07-09", "time": "10:00"},
        s, now=NOW)
    assert any(f.rule == "conflict" for f in fb)


def test_to_ics_shape():
    ev, _, _ = validate_scheduling(_ext(), _seeded(), now=NOW)
    ics = to_ics(ev)
    assert ics.startswith("BEGIN:VCALENDAR") and "DTSTART:20260707T150000" in ics


# ── stringy nulls from the LLM (found live on real AMI transcripts) ──
def test_string_null_time_is_treated_as_missing_not_parsed():
    """A model asked for "HH:MM or null" may emit the *string* "null". Observed on real
    AMI transcripts, where it crashed the time parser with a ValueError."""
    store = _seeded()
    seed = {"title": "Design sync", "participants": ["Bob Rivera"],
            "date": "2026-07-09", "time": "null", "duration_minutes": 40,
            "location": "null"}
    event, missing, _ = validate_scheduling(seed, store, now=NOW)
    assert event["start"] is None
    assert event["location"] is None
    assert "time" in missing                    # → the human is asked, nothing is booked


@pytest.mark.parametrize("bad", ["null", "None", "N/A", "nil", "", "  ", "25:99", "half four"])
def test_only_a_real_clock_time_is_accepted(bad):
    store = _seeded()
    event, missing, _ = validate_scheduling(
        {"title": "t", "participants": ["Bob Rivera"], "date": "2026-07-09", "time": bad},
        store, now=NOW)
    assert event["start"] is None and "time" in missing


def test_stringy_null_duration_falls_back_to_default():
    store = _seeded()
    event, _, _ = validate_scheduling(
        {"title": "t", "participants": ["Bob Rivera"], "date": "2026-07-09",
         "time": "14:00", "duration_minutes": "null"}, store, now=NOW)
    assert event["duration_minutes"] == 30


def test_stringy_null_participants_are_dropped():
    store = _seeded()
    event, missing, _ = validate_scheduling(
        {"title": "t", "participants": ["null", "", "Bob Rivera"], "date": "2026-07-09",
         "time": "14:00"}, store, now=NOW)
    assert event["participant_names"] == ["Bob Rivera"]
