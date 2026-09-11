"""Evaluation v3 Review Value and Review Effort metrics.

Review Value uses an explicit pre-review draft label and the already-scored final Task
Outcome. Review Effort is derived only from captured interaction/audit data. Scripted and
author reviews remain labelled separately; no population-level inference is made here.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from statistics import median
from typing import Any

from pydantic import BaseModel

from .outcomes_v3 import EvalCase, OutcomeScore


class ReviewValueSummary(BaseModel):
    n: int
    unscored: int
    correct_acceptance: int
    rescued: int
    over_reliance: int
    over_correction: int
    rescue_rate: float | None
    over_reliance_rate: float | None
    over_correction_rate: float | None
    reviewer_types: dict[str, int]


class DistributionSummary(BaseModel):
    n: int
    median: float | None
    q1: float | None
    q3: float | None


class ReviewEffortSummary(BaseModel):
    n: int
    action_counts: dict[str, int]
    decision_time_seconds: DistributionSummary
    fields_changed: DistributionSummary
    interactions: DistributionSummary
    information_request_rounds: DistributionSummary
    selected_candidate_rank: DistributionSummary


def _review_value(pairs: list[tuple[EvalCase, OutcomeScore]]) -> ReviewValueSummary:
    scored = [(case, row) for case, row in pairs if case.draft_outcome is not None]
    accepted = sum(case.draft_outcome and row.task_outcome for case, row in scored)
    rescued = sum(not case.draft_outcome and row.task_outcome for case, row in scored)
    reliance = sum(not case.draft_outcome and not row.task_outcome for case, row in scored)
    correction = sum(case.draft_outcome and not row.task_outcome for case, row in scored)
    wrong_drafts = rescued + reliance
    correct_drafts = accepted + correction
    reviewer_types = Counter(case.reviewer_type for case, _ in scored)
    return ReviewValueSummary(
        n=len(scored), unscored=len(pairs) - len(scored),
        correct_acceptance=accepted, rescued=rescued,
        over_reliance=reliance, over_correction=correction,
        rescue_rate=round(rescued / wrong_drafts, 3) if wrong_drafts else None,
        over_reliance_rate=round(reliance / wrong_drafts, 3) if wrong_drafts else None,
        over_correction_rate=round(correction / correct_drafts, 3) if correct_drafts else None,
        reviewer_types=dict(sorted(reviewer_types.items())))


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return round(values[lower] * (1 - weight) + values[upper] * weight, 3)


def _distribution(values: list[float]) -> DistributionSummary:
    return DistributionSummary(
        n=len(values), median=round(float(median(values)), 3) if values else None,
        q1=_percentile(values, 0.25), q3=_percentile(values, 0.75))


def _decision_seconds(case: EvalCase) -> float | None:
    if case.active_review_time_ms is not None:
        return case.active_review_time_ms / 1000
    if not case.started_at or not case.decided_at:
        return None
    try:
        start = datetime.fromisoformat(case.started_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(case.decided_at.replace("Z", "+00:00"))
        return max(0.0, (end - start).total_seconds())
    except ValueError:
        return None


def _records(case: EvalCase):
    state = case.actual_final_state
    return [*state.threads, *state.events, *state.submissions]


def _information_rounds(case: EvalCase) -> int:
    return sum(
        event.get("action") == "request_information"
        for record in _records(case)
        for event in record.data.get("audit_events", [])
        if isinstance(event, dict))


def _selected_rank(case: EvalCase) -> int | None:
    candidate_id = next((
        record.data.get("candidate", {}).get("candidate_id")
        for record in case.actual_final_state.events
        if isinstance(record.data.get("candidate"), dict)), None)
    if not candidate_id:
        return None
    for check in case.deterministic_checks:
        candidates = (check.get("recommendation") or {}).get("candidates") or []
        for index, candidate in enumerate(candidates, 1):
            if candidate.get("candidate_id") == candidate_id:
                return index
    return None


def _review_effort(pairs: list[tuple[EvalCase, OutcomeScore]]) -> ReviewEffortSummary:
    cases = [case for case, _ in pairs]
    seconds = [value for case in cases if (value := _decision_seconds(case)) is not None]
    ranks = [value for case in cases if (value := _selected_rank(case)) is not None]
    information_rounds = [_information_rounds(case) for case in cases]
    decisions = [
        str(
            case.review_action.get("decision")
            if isinstance(case.review_action, dict)
            else case.review_action or "none"
        ).lower()
        for case in cases
    ]
    return ReviewEffortSummary(
        n=len(cases),
        action_counts={
            "unchanged": sum(
                not case.changed_fields and rounds == 0
                for case, rounds in zip(cases, information_rounds)
            ),
            "edited": sum(bool(case.changed_fields) for case in cases),
            "requested_information": sum(rounds > 0 for rounds in information_rounds),
            "rejected": sum(decision in {"reject", "dismiss", "cancel"}
                            for decision in decisions),
        },
        decision_time_seconds=_distribution(seconds),
        fields_changed=_distribution([float(len(case.changed_fields)) for case in cases]),
        interactions=_distribution([float(case.interaction_count) for case in cases]),
        information_request_rounds=_distribution(
            [float(rounds) for rounds in information_rounds]),
        selected_candidate_rank=_distribution([float(rank) for rank in ranks]))


def evaluate_review_metrics(
    cases: list[EvalCase],
    scores: list[OutcomeScore],
    *,
    evidence_boundary: str = "oracle-assisted simulated upper bound; not human evidence",
) -> dict[str, Any]:
    """Return overall and grouped review metrics for the API/front-end payload."""
    if len(cases) != len(scores):
        raise ValueError("cases and scores must align")
    pairs = list(zip(cases, scores))
    workflows: dict[str, list[tuple[EvalCase, OutcomeScore]]] = defaultdict(list)
    conditions: dict[str, list[tuple[EvalCase, OutcomeScore]]] = defaultdict(list)
    reviewer_groups: dict[str, list[tuple[EvalCase, OutcomeScore]]] = defaultdict(list)
    for pair in pairs:
        workflows[pair[1].workflow].append(pair)
        conditions[pair[1].condition].append(pair)
        reviewer_groups[pair[0].reviewer_type].append(pair)
    scripted = _review_value(reviewer_groups.get("scripted", []))
    result = {
        "review_value": _review_value(pairs).model_dump(),
        "review_effort": _review_effort(pairs).model_dump(),
        "review_value_by_workflow": {
            key: _review_value(group).model_dump()
            for key, group in sorted(workflows.items())},
        "review_effort_by_workflow": {
            key: _review_effort(group).model_dump()
            for key, group in sorted(workflows.items())},
        "review_value_by_condition": {
            key: _review_value(group).model_dump()
            for key, group in sorted(conditions.items())},
        "review_effort_by_condition": {
            key: _review_effort(group).model_dump()
            for key, group in sorted(conditions.items())},
        "review_value_by_reviewer_type": {
            key: _review_value(group).model_dump()
            for key, group in sorted(reviewer_groups.items())},
        "review_effort_by_reviewer_type": {
            key: _review_effort(group).model_dump()
            for key, group in sorted(reviewer_groups.items())},
    }
    # Explicit Part A vocabulary. Keep the legacy keys above for the immutable v3.2
    # payload and frontend compatibility; these aliases prevent scripted results from being
    # mislabeled as observed human reliance or effort in new reports.
    result["scripted_review_analysis"] = {
        "n": scripted.n,
        "simulated_rescues": scripted.rescued,
        "failed_rescues": scripted.over_reliance,
        "simulated_over_corrections": scripted.over_correction,
        "simulated_rescue_rate": scripted.rescue_rate,
        "failed_rescue_rate": scripted.over_reliance_rate,
        "simulated_over_correction_rate": scripted.over_correction_rate,
        "evidence_boundary": evidence_boundary,
    }
    return result
