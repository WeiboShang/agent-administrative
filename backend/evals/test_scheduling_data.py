"""Tests for the WF2 synthetic data generator. Offline (no LLM)."""
from datetime import datetime

from backend.evals.scheduling_data import (
    GEN_NOW,
    TIERS,
    back_check,
    make_case,
    make_dataset,
)
from backend.fixtures import org
from backend.workflows.scheduling import resolve_relative_date


def _case(tier, seed=42):
    return make_case(tier, seed=seed)


def test_dataset_is_balanced_and_back_checks():
    data = make_dataset(n_per_tier=4, seed=7)
    assert len(data) == 4 * len(TIERS)
    assert all(back_check(c) for c in data)
    # every gold participant resolves in the directory
    for c in data:
        assert all(org.find_person(uid) is not None for uid in c.gold["participants"])


def test_generation_is_deterministic():
    a = make_dataset(n_per_tier=3, seed=1)
    b = make_dataset(n_per_tier=3, seed=1)
    assert [c.input_text for c in a] == [c.input_text for c in b]
    assert [c.gold for c in a] == [c.gold for c in b]


def test_clean_case_dates_resolve_and_time_is_stated():
    c = _case("clean")
    assert c.gold["intent"] == "schedule_meeting"
    assert c.meta["date_style"] in ("explicit", "relative")
    now = datetime.fromisoformat(c.meta["now"])
    assert resolve_relative_date(c.meta["date_phrase"], now) == c.gold["date"]
    assert f"at {c.gold['time']}" in c.input_text


def test_missing_case_flags_time_and_omits_it():
    c = _case("missing")
    assert c.gold["time"] is None
    assert c.meta["missing"] == ["time"]
    assert "at " not in c.input_text  # no "... at HH:MM"


def test_ambiguous_case_is_vague_and_gold_has_no_date():
    c = _case("ambiguous")
    assert c.meta["date_style"] == "vague"
    assert c.gold["date"] is None                      # never-invent-missing
    assert c.meta["missing"] == ["date"]
    now = datetime.fromisoformat(c.meta["now"])
    assert resolve_relative_date(c.meta["date_phrase"], now) is None


def test_noise_case_buries_the_request_in_distractors():
    c = _case("noise")
    assert c.gold["intent"] == "schedule_meeting"
    assert c.meta["n_distractors"] >= 3
    # longer than the same request rendered clean
    assert len(c.input_text) > len(_case("clean").input_text)
    assert back_check(c)


def test_revision_gold_includes_the_visible_organizer():
    c = _case("revision")
    assert "alice" in c.gold["participants"]   # she says "can we meet" in the dialogue


def test_revision_case_gold_is_the_final_slot():
    c = _case("revision")
    sup = c.meta["superseded"]
    # the superseded slot appears in the text but is NOT the gold
    assert sup["weekday"] in c.input_text or sup["time"] in c.input_text
    now = datetime.fromisoformat(c.meta["now"])
    assert resolve_relative_date(c.meta["date_phrase"], now) == c.gold["date"]
    assert c.gold["time"] in c.input_text
    assert back_check(c)


def test_stateful_conflict_prebook_overlaps_the_request():
    c = _case("stateful_conflict")
    pb = c.meta["pre_book"]
    assert c.meta["expect_conflict"] is True
    assert pb["date"] == c.gold["date"]
    assert set(pb["participants"]) & set(c.gold["participants"])
    assert pb["start"] < c.gold["time"] or pb["start"] == c.gold["time"]
    assert back_check(c)


def test_out_of_scope_has_no_meeting():
    c = _case("out_of_scope")
    assert c.gold["intent"] == "none"
    assert c.gold["date"] is None
    assert c.gold["participants"] == []


def test_back_check_rejects_a_tampered_case():
    c = _case("clean")
    c.gold["participants"] = ["zoe"]  # not in the directory
    assert back_check(c) is False
    c2 = _case("clean", seed=43)
    c2.gold["date"] = "1999-01-01"  # no longer matches the phrase
    assert back_check(c2) is False


def test_gen_now_is_a_tuesday():
    assert GEN_NOW.weekday() == 1  # the fixture's clash story depends on this
