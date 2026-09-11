"""Tests for the WF2 scorer/harness (stateful validator path). Offline (no LLM)."""
from backend.evals.scheduling_data import make_dataset
from backend.evals.scheduling_score import evaluate, gold_as_extraction


def test_offline_eval_is_self_consistent():
    """With a perfect (gold) extraction the deterministic validator should score 100% on
    every metric — proving scorer, oracle and validator agree."""
    report = evaluate(make_dataset(n_per_tier=6, seed=3))
    assert report["clean"]["date_correct"] == 1.0
    assert report["clean"]["time_correct"] == 1.0
    assert report["clean"]["participants_correct"] == 1.0
    assert report["ambiguous"]["date_correct"] == 1.0      # vague → no date invented
    assert report["ambiguous"]["missing_detected"] == 1.0  # ...and flagged missing
    assert report["missing"]["missing_detected"] == 1.0    # omitted time flagged
    assert report["out_of_scope"]["correct_abstain"] == 1.0
    for tier in ("clean", "noise", "stateful_conflict"):
        assert report[tier].get("conflict_correct", 1.0) == 1.0


def test_stateful_conflict_tier_exercises_the_store():
    """The pre-booked overlapping meeting must be flagged by the stateful validator —
    this metric is present on every case of the tier, not skipped."""
    report = evaluate(make_dataset(n_per_tier=8, seed=5))
    tier = report["stateful_conflict"]
    assert tier["n"] == 8
    assert tier["conflict_correct"] == 1.0


def test_scorer_catches_a_wrong_date():
    """A broken extractor that emits the wrong date must drop date_correct below 1.0 —
    including on the vague tier, where inventing any date is the failure."""
    def broken_extract(case):
        ex = gold_as_extraction(case)
        if ex.get("date"):
            ex["date"] = "2026-01-01"  # wrong, and not what the phrase resolves to
        return ex

    report = evaluate(make_dataset(n_per_tier=6, seed=3), extract_fn=broken_extract)
    assert report["clean"]["date_correct"] < 1.0
    assert report["ambiguous"]["date_correct"] < 1.0       # invented a date from vagueness


def test_scorer_catches_a_missed_participant():
    """Dropping a participant must drop participants_correct below 1.0."""
    def drop_participant(case):
        ex = gold_as_extraction(case)
        if len(ex.get("participants", [])) > 0:
            ex["participants"] = ex["participants"][:-1]
        return ex

    report = evaluate(make_dataset(n_per_tier=10, seed=2), extract_fn=drop_participant)
    assert report["clean"]["participants_correct"] < 1.0
