"""WF2: explicit V5 date semantics + deterministic free-slot search (offline)."""
from datetime import datetime

from backend.backends.records import RecordStore
from backend.fixtures import org
from backend.workflows.scheduling import (
    date_ambiguity,
    suggest_free_slots,
    validate_scheduling,
)

WED = datetime(2026, 7, 1, 9, 0)      # 2026-07-01 is a Wednesday


def _seeded() -> RecordStore:
    s = RecordStore(":memory:")
    org.seed_from_org(s)
    return s


# ── explicit V5 date convention ──
def test_next_weekday_has_one_frozen_calendar_week_meaning():
    assert date_ambiguity("next Friday", WED) is None
    assert date_ambiguity("next Friday", datetime(2026, 7, 2, 9, 0)) is None


def test_next_weekday_is_never_marked_ambiguous():
    assert date_ambiguity("next Friday", datetime(2026, 7, 4, 9, 0)) is None
    # on the day itself, both readings roll a full week
    assert date_ambiguity("next Friday", datetime(2026, 7, 3, 9, 0)) is None
    # Mon already passed by Wednesday
    assert date_ambiguity("next Monday", WED) is None


def test_bare_weekday_and_non_weekday_are_never_flagged():
    for expr in ["Friday", "tomorrow", "2026-07-03", "sometime", "", None, 7]:
        assert date_ambiguity(expr, WED) is None


def test_next_weekday_reaches_the_gate_as_an_inferred_following_week_date():
    ev, _, flags = validate_scheduling(
        {"title": "Sync", "participants": ["Bob"], "date": "next Friday", "time": "14:00"},
        _seeded(), now=WED)
    assert ev["slot_provenance"]["date"] == "inferred"
    assert not any(f.rule == "ambiguous_date" for f in flags)
    assert ev["date"] == "2026-07-10"


def test_unambiguous_date_keeps_its_normal_provenance():
    ev, _, flags = validate_scheduling(
        {"title": "Sync", "participants": ["Bob"], "date": "2026-07-03", "time": "14:00"},
        _seeded(), now=WED)
    assert ev["slot_provenance"]["date"] == "explicit"
    assert not any(f.rule == "ambiguous_date" for f in flags)


# ── free-slot search ──
def _event(**over):
    return {"date": "2026-07-07", "start": "14:00", "end": "15:00",
            "duration_minutes": 60, "participants": ["bob"], **over}


def test_suggests_slots_that_are_actually_free():
    s = _seeded()                       # bob is seeded busy 2026-07-07 14:00–15:00
    slots = suggest_free_slots(_event(), s, now=WED)
    assert slots, "expected alternatives"
    booked = [r.data for r in s.list("events", status="booked")]
    for slot in slots:
        for d in booked:
            if d.get("date") == slot["date"] and "bob" in d.get("participants", []):
                assert not (slot["start"] < d["end"] and d["start"] < slot["end"]), slot


def test_never_re_proposes_the_clashing_slot():
    slots = suggest_free_slots(_event(), _seeded(), now=WED)
    assert {"date": "2026-07-07", "start": "14:00"} not in [
        {"date": s["date"], "start": s["start"]} for s in slots]


def test_slots_stay_inside_working_hours():
    from backend.workflows.policy import WORKING_HOURS
    for slot in suggest_free_slots(_event(), _seeded(), now=WED):
        assert slot["start"] >= WORKING_HOURS[0]
        assert slot["end"] <= WORKING_HOURS[1]


def test_room_double_booking_is_respected():
    s = _seeded()
    s.create("events", "event", {"date": "2026-07-09", "start": "09:00", "end": "18:00",
                                 "participants": [], "room": "Orion"}, status="booked")
    slots = suggest_free_slots(_event(date="2026-07-09", location="Orion"), s, now=WED,
                               horizon_days=1)
    assert slots == []                  # the room is blocked all day


def test_room_double_booking_reads_current_location_field():
    s = _seeded()
    s.create("events", "event", {
        "date": "2026-07-09",
        "start": "09:00",
        "end": "18:00",
        "participants": [],
        "location": "Orion",
    }, status="booked")
    slots = suggest_free_slots(
        _event(date="2026-07-09", location="Orion"),
        s,
        now=WED,
        horizon_days=1,
    )
    assert slots == []


def test_no_date_or_bad_date_yields_no_suggestions():
    s = _seeded()
    assert suggest_free_slots(_event(date=None), s, now=WED) == []
    assert suggest_free_slots(_event(date="not a date"), s, now=WED) == []


def test_limit_is_respected():
    assert len(suggest_free_slots(_event(), _seeded(), now=WED, limit=2)) <= 2


def test_suggestions_are_spaced_apart_not_adjacent_half_hours():
    """Three consecutive half-hours is one choice wearing three hats."""
    slots = suggest_free_slots(_event(), _seeded(), now=WED, spacing_minutes=120)
    same_day = [s for s in slots if s["date"] == slots[0]["date"]]
    mins = [int(s["start"][:2]) * 60 + int(s["start"][3:]) for s in same_day]
    for a, b in zip(mins, mins[1:]):
        assert b - a >= 120, same_day


def test_spacing_is_configurable():
    tight = suggest_free_slots(_event(), _seeded(), now=WED, spacing_minutes=30)
    assert len(tight) >= 2
