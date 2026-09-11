"""Focused tests for cached/frozen Evaluation v3 adapters (no model calls)."""

import inspect

from backend.evals import outcome_adapters_v3
from backend.evals.outcome_adapters_v3 import (
    build_frozen_suite,
    build_paired_suite,
    build_wf3_paired_cases,
)
from backend.evals.outcomes_v3 import score_suite
from backend.main import app
from backend.testing import ASGITestClient as TestClient


def test_adapter_module_has_no_live_model_or_vision_call():
    source = inspect.getsource(outcome_adapters_v3)
    assert "llm_extract(" not in source
    assert "extract_receipt(" not in source


def test_each_workflow_builds_one_real_state_based_case():
    cases = build_frozen_suite(limit_per_workflow=1)
    assert [case.workflow for case in cases] == ["wf1", "wf2", "wf3"]
    assert all(case.model and case.dataset_version for case in cases)
    assert all(case.git_commit and case.config_version and case.prompt_version
               for case in cases)
    assert all("sha256:" in case.dataset_version for case in cases)
    assert len(cases[0].actual_final_state.events) > len(cases[0].initial_state.events)
    assert len(cases[1].actual_final_state.events) > len(cases[1].initial_state.events)
    assert (len(cases[2].actual_final_state.submissions)
            > len(cases[2].initial_state.submissions))

    result = score_suite(cases)
    assert result.summary.n == 3
    assert set(result.by_workflow) == {"wf1", "wf2", "wf3"}
    assert all(row.state_diff for row in result.cases)


def test_frozen_api_replays_cached_cases_without_persisting():
    response = TestClient(app).post(
        "/api/eval/v3/frozen",
        json={"limit_per_workflow": 1, "persist": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["n"] == 3
    assert set(body["by_workflow"]) == {"wf1", "wf2", "wf3"}


def test_paired_suite_uses_identical_case_ids_for_both_conditions():
    cases = build_paired_suite(limit_per_workflow=1)
    assert len(cases) == 6
    for offset in range(0, 6, 2):
        baseline, optimised = cases[offset:offset + 2]
        assert baseline.workflow == optimised.workflow
        assert baseline.case_id == optimised.case_id
        assert baseline.condition.startswith("baseline_")
        assert optimised.condition.startswith("optimised_")

    scores = score_suite(cases)
    wf1_baseline, wf1_optimised = scores.cases[:2]
    assert wf1_baseline.case_id == wf1_optimised.case_id


def test_paired_api_returns_two_conditions_per_workflow():
    response = TestClient(app).post(
        "/api/eval/v3/paired",
        json={"limit_per_workflow": 1, "persist": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["n"] == 6
    counts = {workflow: 0 for workflow in ("wf1", "wf2", "wf3")}
    for row in body["cases"]:
        counts[row["workflow"]] += 1
    assert counts == {"wf1": 2, "wf2": 2, "wf3": 2}


def test_wf3_optimised_condition_is_gold_free_and_enforces_hard_policy():
    cases = build_wf3_paired_cases()
    scores = score_suite(cases)
    baseline = scores.by_condition["baseline_legacy_review"]
    optimised = scores.by_condition["optimised_policy_gate"]

    assert baseline.n == optimised.n == 108
    assert baseline.unsafe_outcomes > 0
    assert optimised.task_outcomes > baseline.task_outcomes
    optimised_cases = [case for case in cases if case.condition == "optimised_policy_gate"]
    assert all(case.reviewer_type == "scripted" for case in optimised_cases)
    assert all(case.changed_fields == [] for case in optimised_cases)
    assert all(
        case.deterministic_checks[0]["source_review"] == {
            "policy": "gold_free_no_oracle_correction",
            "corrected_fields": [],
        }
        for case in optimised_cases
    )
    for case in optimised_cases:
        if case.scenario_tier in {"over_limit", "duplicate"}:
            assert case.review_action["decision"] == "reject"


def test_formal_paired_builder_labels_every_case_and_keeps_provenance():
    cases = build_paired_suite(limit_per_workflow=1, result_status="v3_3_formal")
    assert len(cases) == 6
    assert all(case.result_status == "v3_3_formal" for case in cases)
    assert all(
        case.git_commit
        and case.dataset_version
        and case.model
        and case.config_version
        and case.prompt_version
        and case.evaluation_version
        for case in cases
    )
