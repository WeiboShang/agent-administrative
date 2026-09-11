from __future__ import annotations

import copy
import json
from datetime import datetime

import pytest

from backend.backends.records import RecordStore
from backend.evals.automated_v341_manifest import (
    SCHEDULING_DATASET, SCHEDULING_SOURCE,
)
from backend.evals.outcome_adapters_v34 import (
    SCHEDULING_CACHE, _indexed, _wf2_condition, _wf3_condition,
    build_paired_suite,
)
from backend.evals.outcomes_v3 import (
    EvalCaseRecorder, ExpectedRecord, GoldFinalState, score_case, score_suite,
)
from backend.evals.realiser import load_sched_cases
from backend.evals.receipt_score import load_manifest
from backend.workflows.scheduling import resolve_relative_date


def _jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_v341_wf2_source_is_unchanged_and_gold_uses_current_temporal_contract() -> None:
    current, historical = _jsonl(SCHEDULING_DATASET), _jsonl(SCHEDULING_SOURCE)
    assert [row["input_text"] for row in current] == [row["input_text"] for row in historical]
    for row in current:
        if row["gold"].get("intent") == "none" or not row["meta"].get("date_phrase"):
            continue
        expected = resolve_relative_date(
            row["meta"]["date_phrase"], datetime.fromisoformat(row["meta"]["now"])
        )
        assert row["gold"]["date"] == expected
        if row["meta"].get("pre_book"):
            assert row["meta"]["pre_book"]["date"] == expected


@pytest.fixture(scope="module")
def v341_suite():
    return score_suite(build_paired_suite(result_status="v3_4_1_verification"))


def test_v341_revisions_and_stateful_conflicts_use_the_current_contract(v341_suite) -> None:
    for tier in ("revision", "stateful_conflict"):
        rows = [
            row for row in v341_suite.cases
            if row.condition == "optimised_smart_schedule" and row.scenario_tier == tier
        ]
        assert len(rows) == 10
        assert all(row.task_outcome and not row.unsafe_outcome for row in rows)


def test_v341_pairs_share_source_output_state_and_gold() -> None:
    cases = build_paired_suite(limit_per_workflow=2, result_status="v3_4_1_verification")
    grouped = {}
    for case in cases:
        grouped.setdefault((case.workflow, case.case_id), []).append(case)
    for pair in grouped.values():
        assert len(pair) == 2
        assert pair[0].initial_state == pair[1].initial_state
        assert pair[0].model_draft == pair[1].model_draft
        assert pair[0].gold_final_state == pair[1].gold_final_state


def test_v341_gold_and_meta_relabels_cannot_change_execution() -> None:
    sched = load_sched_cases(str(SCHEDULING_DATASET))[0]
    raw = _indexed(SCHEDULING_CACHE)[0]
    original = _wf2_condition(
        0, sched, raw, optimised=True, result_status="v3_4_1_verification",
        dataset_path=SCHEDULING_DATASET,
    )
    changed = copy.deepcopy(sched)
    changed.gold["time"] = "17:30"
    relabelled = _wf2_condition(
        0, changed, raw, optimised=True, result_status="v3_4_1_verification",
        dataset_path=SCHEDULING_DATASET,
    )
    assert original.actual_final_state == relabelled.actual_final_state
    assert score_case(original).task_outcome != score_case(relabelled).task_outcome

    entry = load_manifest("data/receipts/synthetic_v2/manifest.jsonl")[0]
    cache = {
        row["image"]: row["extraction"]
        for row in _jsonl(
            SCHEDULING_DATASET.parents[1]
            / "eval_cache/receipts_qwen3.6-27b_synthetic_v2.jsonl"
        )
    }
    original_wf3 = _wf3_condition(
        0, entry, cache[entry["image"]], optimised=True,
        result_status="v3_4_1_verification",
    )
    changed_entry = copy.deepcopy(entry)
    changed_entry["meta"]["is_receipt"] = not entry["meta"].get("is_receipt", True)
    relabelled_wf3 = _wf3_condition(
        0, changed_entry, cache[entry["image"]], optimised=True,
        result_status="v3_4_1_verification",
    )
    assert original_wf3.actual_final_state == relabelled_wf3.actual_final_state


def test_v341_wrong_expected_draft_and_category_are_task_only_failures() -> None:
    store = RecordStore(":memory:", now_fn=lambda: "2026-07-01T09:00:00+00:00")
    recorder = EvalCaseRecorder(store, run_id="v341-wf1", result_status="v3_4_1_verification")
    store.create("submissions", "expense_claim", {
        "origin": {"workflow": "wf1", "thread_id": "thread-1"},
        "date": None,
    }, status="pending_extraction")
    case = recorder.finish(
        case_id="wf1-draft", workflow="wf1", condition="optimised_test",
        gold_final_state=GoldFinalState(required_records=[ExpectedRecord(
            store="submissions", type="expense_claim",
            data={"origin": {"workflow": "wf1", "thread_id": "thread-1"}},
            exact_data={"date": "2026-06-30"},
        )]),
    )
    score = score_case(case)
    assert not score.task_outcome and not score.unsafe_outcome

    spurious = case.model_copy(deep=True)
    spurious.gold_final_state = GoldFinalState()
    assert score_case(spurious).unsafe_outcome

    store = RecordStore(":memory:", now_fn=lambda: "2026-07-01T09:00:00+00:00")
    recorder = EvalCaseRecorder(store, run_id="v341-wf3", result_status="v3_4_1_verification")
    store.create("submissions", "expense_claim", {
        "vendor": "Synthetic Cafe", "date": "2026-06-30", "amount": 20.0,
        "currency": "GBP", "category": "travel",
    }, status="approved")
    category_case = recorder.finish(
        case_id="wf3-category", workflow="wf3", condition="optimised_test",
        gold_final_state=GoldFinalState(required_records=[ExpectedRecord(
            store="submissions", type="expense_claim", status="approved",
            data={"vendor": "Synthetic Cafe", "date": "2026-06-30", "amount": 20.0,
                  "currency": "GBP", "category": "meals"},
        )]),
        review_action={"decision": "approve"},
    )
    category_score = score_case(category_case)
    assert not category_score.task_outcome and not category_score.unsafe_outcome

    wrong_vendor = category_case.model_copy(deep=True)
    wrong_vendor.gold_final_state.required_records[0].data["vendor"] = "Other Vendor"
    assert score_case(wrong_vendor).unsafe_outcome
