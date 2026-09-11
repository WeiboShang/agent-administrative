"""Tests for the WF2 date/time helpers. No LLM / network — runs offline.

(The validator/executor are covered in test_scheduling_stateful.py.)
"""
from datetime import datetime

from backend.workflows.scheduling import add_minutes, resolve_relative_date

# 2026-06-30 is a Tuesday; the org fixture seeds Bob busy 2026-07-07 14:00–15:00.
NOW = datetime(2026, 6, 30, 9, 0)


# --- date resolution -------------------------------------------------------
def test_resolve_iso_passthrough():
    assert resolve_relative_date("2026-07-07", NOW) == "2026-07-07"


def test_resolve_today_and_tomorrow():
    assert resolve_relative_date("today", NOW) == "2026-06-30"
    assert resolve_relative_date("tomorrow", NOW) == "2026-07-01"


def test_next_tuesday_rolls_to_following_week():
    # NOW is itself a Tuesday, so the next Tuesday is +7.
    assert resolve_relative_date("next Tuesday", NOW) == "2026-07-07"
    assert resolve_relative_date("tuesday", NOW) == "2026-07-07"


def test_bare_weekday_later_this_week():
    assert resolve_relative_date("wednesday", NOW) == "2026-07-01"


def test_unparseable_returns_none():
    assert resolve_relative_date("whenever works", NOW) is None
    assert resolve_relative_date(None, NOW) is None


def test_dateparser_fallback_resolves_richer_phrases():
    assert resolve_relative_date("3 August 2026", NOW) == "2026-08-03"
    assert resolve_relative_date("July 14", NOW) == "2026-07-14"
    assert resolve_relative_date("the day after tomorrow", NOW) == "2026-07-02"
    assert resolve_relative_date("in two weeks", NOW) == "2026-07-14"


def test_vague_phrases_stay_none_never_invent():
    for phrase in ("sometime early next week", "in the next couple of weeks",
                   "once things calm down a bit", "later this month, whenever suits"):
        assert resolve_relative_date(phrase, NOW) is None


def test_add_minutes():
    assert add_minutes("14:30", 30) == "15:00"
    assert add_minutes("09:45", 30) == "10:15"
