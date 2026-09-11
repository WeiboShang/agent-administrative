from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.evals.automated_v35_data import (
    DATE_AUDIT,
    OUTPUT as SCHEDULING_V35,
    SOURCE as SCHEDULING_V343,
    TEMPORAL_CONTRACT,
)
from backend.evals.outcome_adapters_v35 import build_wf2_v35_paired_cases
from backend.evals.outcomes_v3 import RecordState, score_case
from backend.evals.wf2_mechanism_v35 import run_mechanism_suite


def _jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _optimised(index: int):
    cases = build_wf2_v35_paired_cases(limit=index + 1)
    return next(
        case
        for case in cases
        if case.case_id == f"wf2-{index:04d}"
        and case.condition == "optimised_smart_schedule"
    )


def _created_event(case):
    initial_ids = {record.id for record in case.initial_state.events}
    return next(
        record
        for record in case.actual_final_state.events
        if record.id not in initial_ids and record.status == "booked"
    )


def test_v35_preserves_sources_and_adds_only_strict_gold_fields() -> None:
    prior = _jsonl(SCHEDULING_V343)
    current = _jsonl(SCHEDULING_V35)
    assert len(prior) == len(current) == 70
    additions = {"organizer", "location", "accepted_location_values"}
    for old, new in zip(prior, current):
        assert new["input_text"] == old["input_text"]
        assert new["meta"] == old["meta"]
        assert {
            key: value
            for key, value in new["gold"].items()
            if key not in additions
        } == old["gold"]


def test_v35_temporal_contract_and_date_audit_are_literal_and_complete() -> None:
    contract = json.loads(TEMPORAL_CONTRACT.read_text(encoding="utf-8"))
    audit = json.loads(DATE_AUDIT.read_text(encoding="utf-8"))
    assert contract["manual_relative_date_table"] == {
        "next Monday": "2026-07-06",
        "next Tuesday": "2026-07-07",
        "next Wednesday": "2026-07-08",
        "next Thursday": "2026-07-09",
        "next Friday": "2026-07-10",
    }
    assert len(contract["case_expected_dates"]) == 70
    assert len(audit["rows"]) == 15
    assert sum(row["v3_3_task_outcome_failed"] for row in audit["rows"]) == 12
    assert sum(
        row["first_exposed_by_v3_4_source_only_execution"]
        for row in audit["rows"]
    ) == 3
    assert {row["attribution"] for row in audit["rows"]} == {
        "evaluation_contract_correction"
    }


def test_v35_gold_and_reference_oracle_do_not_reference_production_solver() -> None:
    root = Path(__file__).resolve().parents[2]
    for relative in (
        "backend/evals/automated_v35_data.py",
        "backend/evals/wf2_v35_oracle.py",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        assert "resolve_relative_date" not in source
        assert "recommend_candidates" not in source
    oracle = (root / "backend/evals/wf2_v35_oracle.py").read_text(encoding="utf-8")
    assert "workflows.scheduling" not in oracle


def test_v35_pairs_share_source_output_state_and_strict_gold() -> None:
    cases = build_wf2_v35_paired_cases(limit=2)
    grouped = {}
    for case in cases:
        grouped.setdefault(case.case_id, []).append(case)
    for pair in grouped.values():
        assert len(pair) == 2
        assert pair[0].initial_state == pair[1].initial_state
        assert pair[0].model_draft == pair[1].model_draft
        assert pair[0].gold_final_state == pair[1].gold_final_state
        assert pair[0].evaluation_version == pair[1].evaluation_version == "v3.5"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("organizer", "bob"),
        ("participants", ["alice"]),
        ("location", "Lyra"),
        ("mode", "virtual"),
        ("duration_minutes", 30),
        ("end", "17:30"),
    ],
)
def test_v35_strict_scorer_rejects_wrong_task_fields(field: str, value) -> None:
    case = _optimised(0).model_copy(deep=True)
    _created_event(case).data[field] = value
    assert not score_case(case).task_outcome


def test_v35_strict_scorer_rejects_extra_booking() -> None:
    case = _optimised(0).model_copy(deep=True)
    original = _created_event(case)
    case.actual_final_state.events.append(
        RecordState(**{**original.model_dump(), "id": "evt-v35-extra"})
    )
    scored = score_case(case)
    assert not scored.task_outcome
    assert scored.unsafe_outcome


def test_v35_strict_scorer_rejects_conflicting_flexible_slot() -> None:
    # Row 18 is flexible on 2026-07-07. Alice's frozen 11:00-11:30 stand-up makes
    # 11:00-11:45 illegal when organiser availability is evaluated independently.
    case = _optimised(18).model_copy(deep=True)
    event = _created_event(case)
    event.data["start"] = "11:00"
    event.data["end"] = "11:45"
    assert not score_case(case).task_outcome


def test_v35_strict_scorer_accepts_another_independently_feasible_slot() -> None:
    case = _optimised(10).model_copy(deep=True)
    allowed = case.diagnostics["wf2_v35_allowed_slots"]
    event = _created_event(case)
    replacement = next(
        slot for slot in allowed if slot["start"] != event.data["start"]
    )
    event.data.update(replacement)
    assert score_case(case).task_outcome


def test_v35_abstention_preserves_complete_seed_state() -> None:
    case = _optimised(50)
    assert case.actual_final_state == case.initial_state
    assert score_case(case).task_outcome


def test_v35_mechanism_suite_is_secondary_and_has_frozen_denominators() -> None:
    result = run_mechanism_suite()
    assert result["suite"] == "WF2-MECH-20"
    assert result["headline_eligible"] is False
    assert result["case_count"] == 20
    assert sum(case["group"] == "conflict" for case in result["cases"]) == 12
    assert sum(case["group"] == "top3" for case in result["cases"]) == 8
    assert result["metrics"]["conflict_type_accuracy"]["denominator"] == 12
    assert result["metrics"]["no_conflict_false_positive_rate"]["denominator"] == 3
