"""Tests for the minimal-pair + retraction generators and their metrics (offline)."""
from backend.evals.triage_data import (
    PAIR_DELTAS,
    RETRACTION_DISTANCES,
    make_pair_case,
    make_pair_dataset,
    make_retraction_case,
    make_retraction_dataset,
)
from backend.evals.triage_score import evaluate_pairs, gold_as_triage, score_case


# ── minimal pairs ──
def test_twins_differ_by_exactly_one_line():
    """The whole design rests on this: same noise, same position, one line changed."""
    for delta in PAIR_DELTAS:
        minus, plus = make_pair_case(delta, seed=3)
        a, b = minus.raw_text.split("\n"), plus.raw_text.split("\n")
        assert len(a) == len(b), delta
        diff = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        assert len(diff) == 1, f"{delta}: {len(diff)} lines differ, expected 1"


def test_twin_gold_is_opposite():
    for delta in PAIR_DELTAS:
        minus, plus = make_pair_case(delta, seed=1)
        assert minus.gold["action_types"] == ["none"]
        assert plus.gold["action_types"] == ["schedule_meeting"]
        assert minus.meta["delta"] == plus.meta["delta"] == delta
        assert minus.meta["side"] == "minus" and plus.meta["side"] == "plus"


def test_pairs_deterministic_in_seed():
    assert make_pair_case("time_specificity", 7)[0].raw_text == \
           make_pair_case("time_specificity", 7)[0].raw_text


def test_pair_dataset_covers_every_delta():
    pairs = make_pair_dataset(n_per_delta=2)
    assert len(pairs) == len(PAIR_DELTAS) * 2
    assert {m.meta["delta"] for m, _ in pairs} == set(PAIR_DELTAS)


def test_perfect_extractor_scores_one_everywhere():
    rep = evaluate_pairs(make_pair_dataset(n_per_delta=2), gold_as_triage)["pairs"]
    for delta in PAIR_DELTAS:
        assert rep[delta]["paired_accuracy"] == 1.0
        assert rep[delta]["car"] == 1.0


def test_constant_policies_score_zero_paired():
    """The point of twins: neither 'always act' nor 'always abstain' can win."""
    pairs = make_pair_dataset(n_per_delta=2)
    always_act = evaluate_pairs(
        pairs, lambda c: {"detected_actions": [{"action_type": "schedule_meeting"}]})["pairs"]
    always_abstain = evaluate_pairs(pairs, lambda c: {"detected_actions": []})["pairs"]
    for delta in PAIR_DELTAS:
        assert always_act[delta]["paired_accuracy"] == 0.0
        assert always_abstain[delta]["paired_accuracy"] == 0.0
        # and CAR is undefined for the inert policy — it never solves the act side
        assert always_abstain[delta]["car"] is None


def test_car_conditions_on_the_act_side():
    """A model that abstains everywhere must not look good at abstaining."""
    pairs = make_pair_case("time_specificity", seed=0)
    # right on T+, wrong on T− (over-acts): abstain 0, act 1, CAR 0
    rep = evaluate_pairs(
        [pairs], lambda c: {"detected_actions": [{"action_type": "schedule_meeting"}]})["pairs"]
    r = rep["time_specificity"]
    assert r["act_rate"] == 1.0 and r["abstain_rate"] == 0.0 and r["car"] == 0.0


# ── retraction ──
def test_retraction_gold_is_no_action():
    for d in RETRACTION_DISTANCES:
        c = make_retraction_case(d, seed=2)
        assert c.gold["action_types"] == ["none"]
        assert c.meta["tier"] == f"retracted_{d}"


def test_retraction_plan_is_fully_specified_and_then_called_off():
    c = make_retraction_case("far", seed=5)
    lines = c.raw_text.split("\n")
    assert c.meta["plan_turns"] == 3
    assert len(lines) == 3 + c.meta["gap_turns"] + 1        # plan + filler + retraction
    assert "Room" in lines[1]                               # location present in the plan
    # the last line is the retraction, and it is far from the plan
    assert c.meta["gap_turns"] == RETRACTION_DISTANCES["far"]


def test_retraction_scores_through_existing_correct_refusal_path():
    """No new metric needed: empty gold already routes to correct_refusal."""
    c = make_retraction_case("near", seed=1)
    row = score_case(c, {"detected_actions": []})
    assert row["correct_refusal"] is True
    row_bad = score_case(c, {"detected_actions": [{"action_type": "schedule_meeting"}]})
    assert row_bad["correct_refusal"] is False


def test_retraction_dataset_shape():
    ds = make_retraction_dataset(n_per_distance=3)
    assert len(ds) == len(RETRACTION_DISTANCES) * 3


# ── underspecified (AgentAbstain S1) ──
def test_underspecified_gold_is_detect_not_abstain():
    from backend.evals.triage_data import make_underspecified_case
    c = make_underspecified_case(1)
    assert c.gold["action_types"] == ["schedule_meeting"]   # the ask IS real
    assert set(c.meta["expect_absent"]) == {"date", "time", "participants"}


def test_underspecified_text_names_no_slot_or_people():
    from backend.evals.triage_data import _NAMES, _TIMES, make_underspecified_case
    for seed in range(8):
        line = [ln for ln in make_underspecified_case(seed).raw_text.split("\n")
                if ln.startswith("Alice:")][0]
        assert not any(t in line for t in _TIMES), line
        assert not any(f" {n}" in line for n in _NAMES), line


def test_fabrication_is_scored_not_abstention():
    from backend.evals.triage_data import make_underspecified_dataset
    from backend.evals.triage_score import evaluate_underspecified
    cases = make_underspecified_dataset(n=4)
    honest = {"detected_actions": [{"action_type": "schedule_meeting",
                                    "seed_fields": {"date": None, "time": None,
                                                    "participants": []}}]}
    r = evaluate_underspecified(cases, lambda c: honest)["underspecified"]
    assert r["detection_rate"] == 1.0 and r["fabrication_rate"] == 0.0

    invented = {"detected_actions": [{"action_type": "schedule_meeting",
                                      "seed_fields": {"date": "next Tuesday", "time": "14:00",
                                                      "participants": ["Bob"]}}]}
    r2 = evaluate_underspecified(cases, lambda c: invented)["underspecified"]
    assert r2["fabrication_rate"] == 1.0
    assert r2["fabricated_by_field"] == {"date": 1.0, "participants": 1.0, "time": 1.0}


def test_stringy_null_is_not_counted_as_fabrication():
    """The model writes "null"/"N/A" instead of JSON null — that is absence, not invention."""
    from backend.evals.triage_data import make_underspecified_dataset
    from backend.evals.triage_score import evaluate_underspecified
    cases = make_underspecified_dataset(n=3)
    stringy = {"detected_actions": [{"action_type": "schedule_meeting",
                                     "seed_fields": {"date": "null", "time": "N/A",
                                                     "participants": [""]}}]}
    r = evaluate_underspecified(cases, lambda c: stringy)["underspecified"]
    assert r["fabrication_rate"] == 0.0


# ── feedback conditioning ──
def test_feedback_modes_pick_disjoint_families():
    from backend.evals.feedback import negatives_for
    from backend.evals.triage_data import PAIR_DELTAS
    d = PAIR_DELTAS[0]
    assert negatives_for(d, "none") == []
    ins = negatives_for(d, "in_family", k=4)
    cross = negatives_for(d, "cross_family", k=4)
    assert len(ins) == 4 and len(cross) == 4
    # cross-family must not reuse the test δ's own frame
    assert set(ins).isdisjoint(set(cross))


def test_negatives_are_disjoint_from_test_cases():
    """A negative that IS a test item would leak the answer."""
    from backend.evals.feedback import negatives_for
    from backend.evals.triage_data import PAIR_DELTAS, make_pair_dataset
    test_text = "\n".join(m.raw_text for m, _ in make_pair_dataset(n_per_delta=6))
    for d in PAIR_DELTAS:
        for neg in negatives_for(d, "in_family", k=4) + negatives_for(d, "cross_family", k=4):
            assert neg not in test_text, neg


def test_baseline_prompt_is_byte_identical_without_negatives():
    """The A/B must isolate the feedback block and nothing else."""
    from backend.agent.prompts import PROMPT_MAP, feedback_block
    base = PROMPT_MAP["triage"].format(input="x", source="chat")
    assert feedback_block(["a"]) not in base
    assert (base + feedback_block(["a"])).startswith(base)


def test_dismissed_spans_reads_the_store():
    from backend.backends.records import RecordStore
    from backend.evals.feedback import dismissed_spans
    s = RecordStore(":memory:")
    s.create("threads", "thread", {"detected_actions": [
        {"action_type": "schedule_meeting", "status": "dismissed", "source_span": "grab a coffee"},
        {"action_type": "schedule_meeting", "status": "routed", "source_span": "sync Tuesday"},
    ]}, status="resolved")
    assert dismissed_spans(s) == ["grab a coffee"]


def test_negatives_are_distinct():
    """k negatives must be k DIFFERENT examples, not one repeated."""
    from backend.evals.feedback import negatives_for
    from backend.evals.triage_data import PAIR_DELTAS
    for d in PAIR_DELTAS:
        for mode in ("in_family", "cross_family"):
            negs = negatives_for(d, mode, k=4)
            assert len(negs) == len(set(negs)) == 4, (d, mode, negs)
