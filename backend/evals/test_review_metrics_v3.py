"""Focused tests for Review Value and Review Effort."""

import pytest
from backend.evals.outcomes_v3 import (
    EvalCase,
    GoldFinalState,
    RecordState,
    WorkspaceState,
    score_suite,
)
from backend.evals.review_metrics_v3 import evaluate_review_metrics


def _review_case(index: int, *, draft: bool, final: bool) -> EvalCase:
    actual = WorkspaceState()
    if not final:
        actual = WorkspaceState(events=[RecordState(
            id=f"evt-{index}", store="events", type="schedule_meeting",
            status="pending_review", data={"unexpected": True},
        )])
    return EvalCase(
        run_id="review-grid", case_id=f"case-{index}", workflow="wf1",
        condition="author_walkthrough", initial_state=WorkspaceState(),
        gold_final_state=GoldFinalState(), actual_final_state=actual,
        draft_outcome=draft, reviewer_type="author", review_action="approve",
        changed_fields=[f"field-{value}" for value in range(index)],
        interaction_count=index,
        started_at=f"2026-08-03T10:00:{index:02d}+00:00",
        decided_at=f"2026-08-03T10:00:{index * 10:02d}+00:00",
    )


def test_review_value_reports_all_four_cells_and_clear_denominators():
    cases = [
        _review_case(1, draft=True, final=True),
        _review_case(2, draft=False, final=True),
        _review_case(3, draft=False, final=False),
        _review_case(4, draft=True, final=False),
    ]
    suite = score_suite(cases)
    metrics = evaluate_review_metrics(cases, suite.cases)
    value = metrics["review_value"]

    assert value["correct_acceptance"] == 1
    assert value["rescued"] == 1
    assert value["over_reliance"] == 1
    assert value["over_correction"] == 1
    assert value["rescue_rate"] == 0.5
    assert value["over_reliance_rate"] == 0.5
    assert value["over_correction_rate"] == 0.5
    assert value["reviewer_types"] == {"author": 4}


def test_review_effort_reports_median_and_iqr_without_composite_score():
    cases = [
        _review_case(1, draft=True, final=True),
        _review_case(2, draft=True, final=True),
        _review_case(3, draft=True, final=True),
        _review_case(4, draft=True, final=True),
    ]
    suite = score_suite(cases)
    effort = evaluate_review_metrics(cases, suite.cases)["review_effort"]

    assert effort["interactions"] == {"n": 4, "median": 2.5, "q1": 1.75, "q3": 3.25}
    assert effort["fields_changed"]["median"] == 2.5
    assert effort["decision_time_seconds"]["n"] == 4
    assert effort["information_request_rounds"]["median"] == 0.0
    assert "score" not in effort


def test_review_metrics_reject_misaligned_cases_and_scores():
    with pytest.raises(ValueError, match="must align"):
        evaluate_review_metrics([_review_case(1, draft=True, final=True)], [])
