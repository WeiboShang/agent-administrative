from backend.evals.run_wf2_v35_formal import run


def test_v35_runner_is_matched_and_does_not_persist_by_default() -> None:
    result = run(limit=1)
    assert result["persisted"] is False
    assert result["result_status"] == "v3_5_verification"
    assert set(result["code_drift_from_sealed_formal"]) == {
        "source_version",
        "scorer_sha256",
    }
    assert result["matched_e2e_case_count"] == 1
    assert result["mechanism_case_count"] == 20
    assert result["report"]["e2e"]["suite"] == "WF2-E2E-70"
    assert result["report"]["mechanism"]["headline_eligible"] is False
