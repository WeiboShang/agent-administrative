from backend.evals.run_v3_formal import run


def test_formal_runner_is_matched_and_does_not_persist_by_default():
    result = run(limit_per_workflow=1)
    assert result["persisted"] is False
    assert result["matched_case_counts"] == {"wf1": 1, "wf2": 1, "wf3": 1}
    assert result["headline"]["result_status"] == "v3_3_formal"
    assert result["headline"]["n_records"] == 1
