from backend.evals.v3_report import formal_headline_report, paired_case_ids


def test_formal_report_has_counts_ci_and_ignores_nonformal_records():
    entries = [
        {"result_status": "legacy_frozen", "result": {"scores": {"cases": [{"workflow": "wf1", "condition": "baseline", "scenario_tier": "ordinary", "case_id": "x", "task_outcome": False, "unsafe_outcome": True}]}}},
        {"result_status": "v3_formal", "result": {"scores": {"cases": [{"workflow": "wf1", "condition": "optimised", "scenario_tier": "ordinary", "case_id": "x", "task_outcome": True, "unsafe_outcome": False}]}}},
    ]
    report = formal_headline_report(entries)
    assert report["overall"]["task_outcome"] == {"numerator": 1, "denominator": 1, "rate": 1.0, "wilson_95": (0.207, 1.0)}


def test_pairing_uses_shared_case_ids_only():
    rows = [
        {"workflow": "wf1", "condition": "baseline", "case_id": "a"},
        {"workflow": "wf1", "condition": "baseline", "case_id": "b"},
        {"workflow": "wf1", "condition": "optimised", "case_id": "a"},
    ]
    assert paired_case_ids(rows) == {"wf1": ["a"]}
