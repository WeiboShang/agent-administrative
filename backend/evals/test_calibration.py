"""Tests for the confidence-calibration analysis (offline, no LLM)."""
from backend.evals.calibration import auroc, collect_confidences, threshold_sweep
from backend.evals.triage_data import make_thread_case


def test_auroc_perfect_separation():
    assert auroc([0.9, 0.8], [0.2, 0.1]) == 1.0


def test_auroc_inverted_separation():
    assert auroc([0.1, 0.2], [0.8, 0.9]) == 0.0


def test_auroc_all_ties_is_chance():
    """Models emit 0.9 over and over; ties must average to 0.5, not be broken arbitrarily."""
    assert auroc([0.9, 0.9, 0.9], [0.9, 0.9]) == 0.5


def test_auroc_partial_ties():
    # pos {1.0, 0.5}, neg {0.5, 0.0}: the shared 0.5 contributes half a point
    assert auroc([1.0, 0.5], [0.5, 0.0]) == 0.875


def test_auroc_needs_both_classes():
    assert auroc([0.9], []) is None
    assert auroc([], [0.1]) is None


def test_collect_labels_actions_against_gold():
    meeting = make_thread_case("meeting", 0)        # gold: schedule_meeting
    ambiguous = make_thread_case("ambiguous", 0)    # gold: none
    out = collect_confidences(
        [meeting, ambiguous],
        [
            {"detected_actions": [{"action_type": "schedule_meeting", "confidence": 0.9}]},
            {"detected_actions": [{"action_type": "schedule_meeting", "confidence": 0.8}]},
        ],
    )
    assert out["n_correct"] == 1 and out["n_spurious"] == 1
    assert out["mean_confidence_correct"] == 0.9
    assert out["mean_confidence_spurious"] == 0.8
    assert out["auroc"] == 1.0


def test_collect_ignores_non_routable_and_malformed_confidence():
    case = make_thread_case("meeting", 1)
    out = collect_confidences([case], [{"detected_actions": [
        {"action_type": "none", "confidence": 0.5},              # not routable
        {"action_type": "schedule_meeting", "confidence": None},  # unusable
        {"action_type": "schedule_meeting", "confidence": True},  # bool is not a score
        {"action_type": "schedule_meeting", "confidence": 0.7},   # the only countable one
    ]}])
    assert out["n_actions"] == 1 and out["n_correct"] == 1


def test_collect_handles_a_thread_with_both_a_hit_and_a_spurious_action():
    """Unit of analysis is the action: one thread can produce both labels."""
    case = make_thread_case("meeting", 2)           # gold: schedule_meeting only
    out = collect_confidences([case], [{"detected_actions": [
        {"action_type": "schedule_meeting", "confidence": 0.95},
        {"action_type": "expense_claim", "confidence": 0.30},
    ]}])
    assert out["n_correct"] == 1 and out["n_spurious"] == 1
    assert out["auroc"] == 1.0


# ── threshold sweep ──
def _rows(pos, neg):
    return ([{"confidence": v, "correct": True} for v in pos]
            + [{"confidence": v, "correct": False} for v in neg])


def test_sweep_reports_one_row_per_observed_value():
    """A two-valued confidence signal must produce a two-row sweep — that IS the finding."""
    sweep = threshold_sweep(_rows([0.9, 0.9], [0.8, 0.8]))
    assert [s["threshold"] for s in sweep] == [0.8, 0.9]


def test_sweep_lowest_threshold_filters_nothing():
    sweep = threshold_sweep(_rows([0.9], [0.8]))
    assert sweep[0] == {"threshold": 0.8, "true_retained": 1.0, "spurious_removed": 0.0}


def test_sweep_finds_the_clean_operating_point():
    sweep = threshold_sweep(_rows([0.9, 0.9, 0.9], [0.8, 0.8]))
    at_09 = next(s for s in sweep if s["threshold"] == 0.9)
    assert at_09["true_retained"] == 1.0 and at_09["spurious_removed"] == 1.0


def test_sweep_costs_true_detections_when_they_share_the_low_value():
    sweep = threshold_sweep(_rows([0.9, 0.8], [0.8]))
    at_09 = next(s for s in sweep if s["threshold"] == 0.9)
    assert at_09["true_retained"] == 0.5 and at_09["spurious_removed"] == 1.0


def test_sweep_needs_both_classes():
    assert threshold_sweep(_rows([0.9], [])) == []
