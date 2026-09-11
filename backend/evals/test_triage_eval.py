"""Tests for the WF1 triage generator + scorer (offline — perfect-extractor stub)."""
from backend.evals.triage_data import (
    LENGTHS,
    POSITIONS,
    TIERS,
    make_dataset,
    make_position_case,
    make_position_dataset,
    make_thread_case,
)
from backend.evals.triage_score import (
    evaluate,
    evaluate_position,
    gold_as_triage,
    score_case,
    summary_coverage,
)


def test_generator_deterministic_and_tiers():
    c1 = make_thread_case("meeting", 5)
    c2 = make_thread_case("meeting", 5)
    assert c1.raw_text == c2.raw_text and c1.gold == c2.gold
    assert make_thread_case("multi", 0).gold["action_types"] == ["schedule_meeting", "expense_claim"]
    assert make_thread_case("out_of_scope", 0).gold["action_types"] == ["none"]


def test_ambiguous_tier_is_varied_and_abstains():
    # every ambiguous case must abstain (gold none), and the widened pool must give real
    # variety at raised n rather than repeating a handful of lines
    cases = [make_thread_case("ambiguous", s) for s in range(15)]
    assert all(c.gold["action_types"] == ["none"] for c in cases)
    assert len({c.raw_text for c in cases}) >= 10


def test_ambiguous_lines_are_recognised_by_the_realiser():
    # each ambiguous template must trip the realiser's cue matcher — otherwise it silently
    # falls back to template and the realised tier loses the variety it is meant to add
    from backend.evals.realiser import realise_thread_case

    stub = lambda _p: "Let's find a moment to properly connect soon."  # noqa: E731
    realised = [realise_thread_case(make_thread_case("ambiguous", s), stub).meta["realised"]
                for s in range(15)]
    assert all(realised)


def test_perfect_extractor_scores_meeting():
    case = make_thread_case("meeting", 1)
    row = score_case(case, gold_as_triage(case))
    assert row["recall"] == 1.0 and row["exact"] is True


def test_missed_action_lowers_recall():
    case = make_thread_case("multi", 1)                 # gold has 2 actions
    row = score_case(case, {"detected_actions": [{"action_type": "schedule_meeting"}]})
    assert row["recall"] == 0.5 and row["exact"] is False


def test_out_of_scope_refusal():
    case = make_thread_case("out_of_scope", 1)
    assert score_case(case, {"detected_actions": []})["correct_refusal"] is True
    # a spurious detection fails the refusal
    assert score_case(case, {"detected_actions": [{"action_type": "schedule_meeting"}]})[
        "correct_refusal"] is False


def test_evaluate_perfect_extractor():
    rep = evaluate(make_dataset(n_per_tier=2), gold_as_triage)["triage"]
    assert set(rep) == set(TIERS)
    assert rep["meeting"]["recall"] == 1.0
    assert rep["out_of_scope"]["correct_refusal"] == 1.0


def test_position_case_length_and_placement():
    for length in LENGTHS:
        early = make_position_case(length, "early", 3)
        late = make_position_case(length, "late", 3)
        assert len(early.raw_text.splitlines()) == length
        assert len(late.raw_text.splitlines()) == length
        assert early.meta["action_index"] < late.meta["action_index"]
        # deterministic in seed
        again = make_position_case(length, "early", 3)
        assert again.raw_text == early.raw_text
    # the buried line is really at action_index
    c = make_position_case(25, "middle", 9)
    assert "Can we sync on" in c.raw_text.splitlines()[c.meta["action_index"]]


def test_evaluate_position_grid_perfect():
    rep = evaluate_position(make_position_dataset(n_per_cell=1), gold_as_triage)["position"]
    assert set(rep) == {str(x) for x in LENGTHS}
    for length in rep:
        assert set(rep[length]) == set(POSITIONS)
        for pos in POSITIONS:
            assert rep[length][pos]["recall"] == 1.0


def test_summary_coverage_counts_gold_facts():
    c = make_position_case(10, "middle", 4)
    f = c.meta["facts"]
    full = {"summary": f"Meeting about {f['topic']} next {f['weekday']} at {f['time']}",
            "key_points": f["names"], "detected_actions": []}
    assert summary_coverage(c, full) == 1.0
    none_found = {"summary": "People chatted about office things.",
                  "key_points": [], "detected_actions": []}
    assert summary_coverage(c, none_found) == 0.0
    # extraction without a summary field → metric not applicable
    assert summary_coverage(c, {"detected_actions": []}) is None
