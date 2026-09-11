from __future__ import annotations

import copy
import json
from collections import Counter
from datetime import datetime

from backend.backends.records import RecordStore
from backend.workflows.scheduling_lifecycle import lifecycle_mutation, normalise_spec, recommend_candidates
from backend.evals.outcome_adapters_v34 import (
    SCHEDULING_CACHE,
    SCHEDULING_DATASET,
    TRIAGE_DATASET,
    _indexed,
    _wf2_condition,
    _wf3_condition,
    build_paired_suite,
)
from backend.evals.outcomes_v3 import EvalCaseRecorder, ExpectedRecord, GoldFinalState, score_case
from backend.evals.realiser import load_sched_cases
from backend.evals.receipt_score import load_manifest


def test_v34_wf1_coverage_and_production_input_contract() -> None:
    rows = [json.loads(line) for line in TRIAGE_DATASET.read_text(encoding="utf-8").splitlines()]
    assert Counter(row["meta"]["tier"] for row in rows) == {
        "meeting": 6, "expense": 6, "multi": 6, "noise": 6,
        "out_of_scope": 6, "ambiguous": 15,
    }
    assert all("leave_request" not in json.dumps(row) for row in rows)
    assert all(row["model_input"].startswith("[msg-") for row in rows)
    assert all(
        {action["action_type"] for action in row["gold"]["actions"]}
        == {"schedule_meeting", "expense_claim"}
        for row in rows if row["meta"]["tier"] == "multi"
    )


def test_v34_pairs_share_initial_output_and_gold() -> None:
    cases = build_paired_suite(limit_per_workflow=2)
    grouped = {}
    for case in cases:
        grouped.setdefault((case.workflow, case.case_id), []).append(case)
    for pair in grouped.values():
        assert len(pair) == 2
        assert pair[0].initial_state == pair[1].initial_state
        assert pair[0].model_draft == pair[1].model_draft
        assert pair[0].gold_final_state == pair[1].gold_final_state


def test_changing_wf2_gold_or_wf3_meta_cannot_change_execution() -> None:
    sched = load_sched_cases(str(SCHEDULING_DATASET))[0]
    raw = _indexed(SCHEDULING_CACHE)[0]
    original = _wf2_condition(0, sched, raw, optimised=True, result_status="v3_4_verification")
    changed = copy.deepcopy(sched)
    changed.gold["time"] = "17:30"
    relabelled = _wf2_condition(0, changed, raw, optimised=True, result_status="v3_4_verification")
    assert original.actual_final_state == relabelled.actual_final_state
    assert score_case(original).task_outcome != score_case(relabelled).task_outcome

    entry = load_manifest("data/receipts/synthetic_v2/manifest.jsonl")[0]
    extraction = json.loads(
        next(line for line in open("data/eval_cache/receipts_qwen3.6-27b_synthetic_v2.jsonl", encoding="utf-8")
             if json.loads(line)["image"] == entry["image"])
    )["extraction"]
    original_wf3 = _wf3_condition(0, entry, extraction, optimised=True, result_status="v3_4_verification")
    changed_entry = copy.deepcopy(entry)
    changed_entry["meta"]["is_receipt"] = not entry["meta"].get("is_receipt", True)
    relabelled_wf3 = _wf3_condition(0, changed_entry, extraction, optimised=True, result_status="v3_4_verification")
    assert original_wf3.actual_final_state == relabelled_wf3.actual_final_state
    assert score_case(original_wf3).task_outcome != score_case(relabelled_wf3).task_outcome


def test_missing_time_books_deterministic_feasible_slot_and_replays() -> None:
    now = datetime(2026, 6, 30, 9, 0)
    store = RecordStore(":memory:", now_fn=lambda: "2026-06-30T09:00:00+00:00")
    spec = normalise_spec({
        "title": "Synthetic sync", "participants": ["Bob Rivera"],
        "date": "2026-07-01", "time": None, "duration_minutes": 30,
    }, now=now)
    first = recommend_candidates(spec, store, now=now)
    second = recommend_candidates(spec, store, now=now)
    assert first == second and first["candidates"]
    result = lifecycle_mutation(
        spec=spec, candidate=first["candidates"][0], store=store, actor="alice",
        idempotency_key="v34-fixed", validation_token=first["validation_token"],
        calendar_version=first["calendar_version"], now=now,
    )
    assert result["status"] == "booked"


def test_category_is_task_defining() -> None:
    store = RecordStore(":memory:", now_fn=lambda: "2026-07-01T09:00:00+00:00")
    recorder = EvalCaseRecorder(store, run_id="category", result_status="v3_4_verification")
    store.create("submissions", "expense_claim", {
        "vendor": "Synthetic Cafe", "amount": 48.0, "currency": "GBP",
        "date": "2026-06-30", "category": "travel",
    }, status="approved")
    case = recorder.finish(
        case_id="category", workflow="wf3", condition="optimised_test",
        gold_final_state=GoldFinalState(required_records=[ExpectedRecord(
            store="submissions", type="expense_claim", status="approved",
            data={"vendor": "Synthetic Cafe", "amount": 48.0, "currency": "GBP",
                  "date": "2026-06-30", "category": "meals"},
        )]),
    )
    assert not score_case(case).task_outcome
