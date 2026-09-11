"""Tests for WF1's deterministic retraction check (offline, no LLM).

False positives matter as much as recall here: a check that flags healthy threads makes the
"code recovers what the model missed" claim meaningless, so the chit-chat corpus the
generator uses is asserted clean.
"""
from backend.evals.triage_data import _CHITCHAT, _NOISE_LINES, make_retraction_case
from backend.workflows.triage import check_retraction, has_retraction_cue

ACTION = [{
    "action_type": "schedule_meeting",
    "source_evidence": [{"message_id": "msg-1", "span": "Booking us in"}],
}]


def test_flags_a_retraction_after_the_action():
    text = "Alice: Booking us in for the Q3 budget next Tuesday at 14:00.\n" \
           "Bob: Sounds good.\n" \
           "Alice: Actually the meeting is cancelled, I'll email a summary."
    flags = check_retraction(text, ACTION)
    assert len(flags) == 1
    assert flags[0]["rule"] == "possible_retraction" and flags[0]["severity"] == "soft"
    assert flags[0]["action_index"] == 0


def test_ignores_a_cancellation_that_precedes_the_request():
    """A cancellation before the ask is not a retraction of it."""
    text = "Alice: Yesterday's sync was cancelled.\n" \
           "Alice: Booking us in for the Q3 budget next Tuesday at 14:00."
    assert check_retraction(text, ACTION) == []


def test_non_routable_actions_are_not_checked():
    text = "Alice: nothing here.\nAlice: the meeting is cancelled."
    assert check_retraction(text, [{"action_type": "none", "source_evidence": []}]) == []


def test_unlocatable_span_scans_the_whole_thread():
    """A paraphrased span must not silently disable the check."""
    text = "Alice: Let's sync Tuesday.\nAlice: Actually, cancel that."
    flags = check_retraction(text, [{
        "action_type": "schedule_meeting",
        "source_evidence": [{
            "message_id": "msg-1", "span": "a paraphrase that is not in the text"
        }],
    }])
    assert len(flags) == 1


def test_generated_retraction_cases_are_all_caught():
    for distance in ("near", "far"):
        for seed in range(6):
            case = make_retraction_case(distance, seed)
            flags = check_retraction(case.raw_text, ACTION)
            assert flags, f"{distance}/{seed} not flagged: {case.raw_text!r}"


# ── false-positive guards ──
def test_no_false_positive_on_the_chitchat_corpora():
    """Every distractor line the generators can emit must be cue-free."""
    for line in list(_CHITCHAT) + list(_NOISE_LINES):
        assert not has_retraction_cue(line), f"false positive: {line!r}"


def test_reschedule_is_not_a_retraction():
    """Moving a meeting is not calling it off — the flag must not fire."""
    for line in [
        "Alice: Change of plan, let's meet at 15:00 instead.",
        "Alice: Standup moved 15 minutes earlier just for today.",
        "Alice: Pushing the review to Thursday, same room.",
    ]:
        assert not has_retraction_cue(line), f"false positive: {line!r}"


def test_weak_cue_needs_a_meeting_noun():
    assert not has_retraction_cue("Bob: No need to bring laptops tomorrow.")
    assert has_retraction_cue("Bob: No need for the meeting, I'll email you.")
