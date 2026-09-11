"""Execute and score the frozen WF2-MECH-20 deterministic mechanism suite."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..backends.records import RecordStore
from ..workflows.scheduling_lifecycle import normalise_spec, recommend_candidates
from .stats import wilson_ci
from .wf2_v35_oracle import (
    candidates_are_diverse,
    conflict_types,
    diverse_capacity,
    enumerate_feasible_slots,
    slot_is_feasible,
)

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "data/eval_datasets/wf2_mechanism_v35.jsonl"


def load_cases(path: Path = DATASET) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _store(case: dict[str, Any]) -> RecordStore:
    stamp = datetime.fromisoformat(case["now"]).replace(
        tzinfo=timezone.utc
    ).isoformat()
    store = RecordStore(":memory:", now_fn=lambda: stamp)
    for event in case.get("seed_events") or []:
        store.create("events", "event", event, status="booked")
    return store


def _proportion(k: int, n: int) -> dict[str, Any]:
    return {
        "numerator": k,
        "denominator": n,
        "rate": round(k / n, 3) if n else None,
        "wilson_95": wilson_ci(k, n) if n else None,
    }


def _warning_reasons(recommendation: dict[str, Any]) -> list[str]:
    reasons = {
        str(reason)
        for warning in recommendation.get("warnings") or []
        for reason in warning.get("reason_codes") or []
        if reason in {"participant_conflict", "room_conflict"}
    }
    return sorted(reasons)


def run_mechanism_suite(path: Path = DATASET) -> dict[str, Any]:
    cases = load_cases(path)
    if len(cases) != 20:
        raise RuntimeError(f"expected 20 frozen mechanism cases, got {len(cases)}")
    results: list[dict[str, Any]] = []
    for case in cases:
        store = _store(case)
        now = datetime.fromisoformat(case["now"])
        spec = normalise_spec(case["spec"], now=now)
        recommendation = recommend_candidates(spec, store, now=now, actor=case["actor"])
        events = case.get("seed_events") or []
        exact = spec.get("exact_time")
        requested_conflicts = (
            conflict_types(
                participants=spec["participant_names"],
                organizer=case["actor"],
                day=spec["date_window"]["start"],
                start=exact,
                end=(
                    datetime.strptime(exact, "%H:%M")
                    + timedelta(minutes=int(spec["duration_minutes"]))
                ).strftime("%H:%M"),
                location=spec.get("location"),
                existing_events=events,
            )
            if exact
            else []
        )
        expected_conflicts = sorted(
            case["gold"].get("expected_requested_conflicts", requested_conflicts)
        )
        predicted_conflicts = _warning_reasons(recommendation)

        reference_slots = enumerate_feasible_slots(
            participants=spec["participant_names"],
            organizer=case["actor"],
            date_start=spec["date_window"]["start"],
            date_end=spec["date_window"].get("end"),
            duration_minutes=int(spec["duration_minutes"]),
            location=spec.get("location"),
            existing_events=events,
            exact_time=exact,
            relax_infeasible_exact=True,
        )
        candidates = recommendation.get("candidates") or []
        candidate_feasible = [
            slot_is_feasible(
                participants=spec["participant_names"],
                organizer=case["actor"],
                day=str(candidate.get("date")),
                start=str(candidate.get("start")),
                duration_minutes=int(spec["duration_minutes"]),
                location=spec.get("location"),
                existing_events=events,
            )
            for candidate in candidates
        ]
        reference_diverse_capacity = diverse_capacity(reference_slots)
        coverage_expected = min(3, reference_diverse_capacity)
        first = candidates[0] if candidates else None
        exact_preserved = (
            bool(first)
            and first.get("date") == spec["date_window"]["start"]
            and first.get("start") == exact
        )
        warning_present = bool(recommendation.get("warnings"))
        expect_warning = bool(case["gold"].get("expect_warning"))
        expect_no_feasible = bool(case["gold"].get("expect_no_feasible"))
        results.append(
            {
                "case_id": case["case_id"],
                "group": case["group"],
                "note": case["gold"].get("note"),
                "expected_requested_conflicts": expected_conflicts,
                "oracle_requested_conflicts": requested_conflicts,
                "predicted_requested_conflicts": predicted_conflicts,
                "conflict_type_exact": predicted_conflicts == expected_conflicts,
                "warning_reason_exact": (
                    predicted_conflicts == expected_conflicts
                    if expected_conflicts
                    else not predicted_conflicts
                ),
                "candidate_count": len(candidates),
                "candidate_feasible": candidate_feasible,
                "all_candidates_feasible": all(candidate_feasible),
                "reference_feasible_count": len(reference_slots),
                "reference_diverse_capacity": reference_diverse_capacity,
                "coverage_expected": coverage_expected,
                "coverage_satisfied": len(candidates) == coverage_expected,
                "diverse": candidates_are_diverse(candidates),
                "exact_slot_should_rank_first": bool(
                    case["gold"].get("exact_slot_should_rank_first")
                ),
                "exact_slot_preserved": exact_preserved,
                "expect_warning": expect_warning,
                "warning_fidelity": warning_present == expect_warning,
                "expect_no_feasible": expect_no_feasible,
                "no_feasible_satisfied": (
                    not candidates and "no_feasible_slot" in recommendation.get("blockers", [])
                ),
                "recommendation": recommendation,
            }
        )

    conflict_rows = [row for row in results if row["group"] == "conflict"]
    top3_rows = [row for row in results if row["group"] == "top3"]
    participant_gold = [
        row for row in conflict_rows
        if "participant_conflict" in row["expected_requested_conflicts"]
    ]
    room_gold = [
        row for row in conflict_rows
        if "room_conflict" in row["expected_requested_conflicts"]
    ]
    no_conflict = [row for row in conflict_rows if not row["expected_requested_conflicts"]]
    all_candidate_checks = [
        passed for row in top3_rows for passed in row["candidate_feasible"]
    ]
    coverage_rows = [
        row for row in top3_rows if row["reference_diverse_capacity"] > 0
    ]
    exact_rows = [row for row in top3_rows if row["exact_slot_should_rank_first"]]
    warning_rows = [row for row in top3_rows if row["expect_warning"]]
    diversity_rows = [
        row for row in top3_rows if row["reference_diverse_capacity"] >= 2
    ]
    no_feasible_rows = [row for row in top3_rows if row["expect_no_feasible"]]

    metrics = {
        "conflict_type_accuracy": _proportion(
            sum(row["conflict_type_exact"] for row in conflict_rows),
            len(conflict_rows),
        ),
        "participant_conflict_recall": _proportion(
            sum(
                "participant_conflict" in row["predicted_requested_conflicts"]
                for row in participant_gold
            ),
            len(participant_gold),
        ),
        "room_conflict_recall": _proportion(
            sum(
                "room_conflict" in row["predicted_requested_conflicts"]
                for row in room_gold
            ),
            len(room_gold),
        ),
        "no_conflict_false_positive_rate": _proportion(
            sum(bool(row["predicted_requested_conflicts"]) for row in no_conflict),
            len(no_conflict),
        ),
        "warning_reason_accuracy": _proportion(
            sum(row["warning_reason_exact"] for row in conflict_rows),
            len(conflict_rows),
        ),
        "feasible_at_3": _proportion(
            sum(all_candidate_checks), len(all_candidate_checks)
        ),
        "coverage_at_3": _proportion(
            sum(row["coverage_satisfied"] for row in coverage_rows),
            len(coverage_rows),
        ),
        "exact_slot_preservation": _proportion(
            sum(row["exact_slot_preserved"] for row in exact_rows),
            len(exact_rows),
        ),
        "warning_fidelity": _proportion(
            sum(row["warning_fidelity"] for row in warning_rows),
            len(warning_rows),
        ),
        "diversity_at_3": _proportion(
            sum(row["diverse"] for row in diversity_rows), len(diversity_rows)
        ),
        "no_feasible_behavior": _proportion(
            sum(row["no_feasible_satisfied"] for row in no_feasible_rows),
            len(no_feasible_rows),
        ),
    }
    return {
        "schema_version": "3.5",
        "suite": "WF2-MECH-20",
        "headline_eligible": False,
        "case_count": len(results),
        "metrics": metrics,
        "cases": results,
    }
