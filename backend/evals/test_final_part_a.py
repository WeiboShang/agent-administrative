from backend.evals.final_part_a import (
    EVIDENCE_BOUNDARY,
    latest_formal_scores,
    load_formal_cases,
)


def test_final_part_a_uses_declared_authoritative_workflow_versions() -> None:
    cases, provenance = load_formal_cases()

    assert len(cases) == 446
    assert {case.evaluation_version for case in cases if case.workflow == "wf1"} == {
        "v3.4.3"
    }
    assert {case.evaluation_version for case in cases if case.workflow == "wf2"} == {"v3.5"}
    assert {case.evaluation_version for case in cases if case.workflow == "wf3"} == {
        "v3.4.3"
    }
    assert provenance["wf1_wf3"]["result_status"] == "v3_4_3_formal"
    assert provenance["wf2"]["result_status"] == "v3_5_formal"


def test_final_part_a_scores_match_the_sealed_headlines() -> None:
    result = latest_formal_scores()

    assert result["package_label"] == "Part A Final"
    assert result["evidence_boundary"] == EVIDENCE_BOUNDARY
    by_workflow = result["by_workflow_condition"]
    assert by_workflow["wf1"]["optimised_draft_only"]["task_outcome_rate"] == 0.867
    assert by_workflow["wf2"]["optimised_smart_schedule"]["task_outcome_rate"] == 1.0
    assert by_workflow["wf2"]["optimised_smart_schedule"]["unsafe_outcome_rate"] == 0.0
    assert by_workflow["wf3"]["optimised_policy_gate"]["task_outcome_rate"] == 0.889
