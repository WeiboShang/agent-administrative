from __future__ import annotations

import copy
import json

from backend.evals.outcome_adapters_v34 import (
    SCHEDULING_V341_DATASET,
    SCHEDULING_V343_CACHE,
    SCHEDULING_V343_DATASET,
    _indexed,
    _wf2_condition,
    _wf2_gold,
    build_paired_suite,
)
from backend.evals.outcomes_v3 import score_case
from backend.evals.realiser import load_sched_cases


def _jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_v343_wf2_changes_one_source_no_gold_and_one_model_output() -> None:
    prior = _jsonl(SCHEDULING_V341_DATASET)
    current = _jsonl(SCHEDULING_V343_DATASET)
    cache = _jsonl(SCHEDULING_V343_CACHE)
    assert len(prior) == len(current) == len(cache) == 70
    assert [row["gold"] for row in current] == [row["gold"] for row in prior]
    assert [
        index
        for index, (old, new) in enumerate(zip(prior, current))
        if old["input_text"] != new["input_text"]
    ] == [30]
    assert current[30]["input_text"].endswith("the sprint review?")
    assert [
        row["i"]
        for row in cache
        if row["provenance"]["generation"] == "fresh_source_repair"
    ] == [30]


def test_v343_wf2_mode_is_categorical_task_gold_only_in_new_contract() -> None:
    row = load_sched_cases(str(SCHEDULING_V343_DATASET))[30]
    old = _wf2_gold(row, "v3_4_2_verification").required_records[0]
    current = _wf2_gold(row, "v3_4_3_verification").required_records[0]
    assert "mode" not in old.data
    assert current.data["mode"] == "virtual"


def test_v343_wf2_gold_relabel_cannot_change_execution_only_score() -> None:
    row = load_sched_cases(str(SCHEDULING_V343_DATASET))[30]
    raw = _indexed(SCHEDULING_V343_CACHE)[30]
    original = _wf2_condition(
        30,
        row,
        raw,
        optimised=True,
        result_status="v3_4_3_verification",
        dataset_path=SCHEDULING_V343_DATASET,
    )
    relabelled_row = copy.deepcopy(row)
    relabelled_row.gold["mode"] = "in_person"
    relabelled = _wf2_condition(
        30,
        relabelled_row,
        raw,
        optimised=True,
        result_status="v3_4_3_verification",
        dataset_path=SCHEDULING_V343_DATASET,
    )
    assert original.actual_final_state == relabelled.actual_final_state
    assert original.model_draft == relabelled.model_draft
    assert score_case(original).task_outcome
    assert not score_case(relabelled).task_outcome


def test_v343_pairs_share_source_output_state_and_gold() -> None:
    cases = build_paired_suite(
        limit_per_workflow=2, result_status="v3_4_3_verification"
    )
    grouped = {}
    for case in cases:
        grouped.setdefault((case.workflow, case.case_id), []).append(case)
    for pair in grouped.values():
        assert len(pair) == 2
        assert pair[0].initial_state == pair[1].initial_state
        assert pair[0].model_draft == pair[1].model_draft
        assert pair[0].gold_final_state == pair[1].gold_final_state
        assert pair[0].dataset_version == pair[1].dataset_version
        assert pair[0].prompt_version == pair[1].prompt_version


def test_v343_status_uses_v343_contract() -> None:
    cases = build_paired_suite(limit_per_workflow=1, result_status="v3_4_3_formal")
    assert {case.evaluation_version for case in cases} == {"v3.4.3"}
    assert {case.result_status for case in cases} == {"v3_4_3_formal"}
