"""Strict, WF2-only adapters for the sealed V3.5 evaluation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ..backends.calendar_backend import MockCalendarBackend
from ..workflows.scheduling import execute_scheduling, validate_scheduling
from ..workflows.scheduling_lifecycle import (
    lifecycle_mutation,
    normalise_spec,
    recommend_candidates,
)
from .outcome_adapters_v34 import (
    SCHEDULING_V343_CACHE,
    TEXT_MODEL,
    _indexed,
    _recorder,
    _seed_wf2,
    _take,
)
from .outcomes_v3 import EvalCase, ExpectedRecord, GoldFinalState, WorkspaceState
from .realiser import load_sched_cases
from .wf2_v35_oracle import add_minutes, enumerate_feasible_slots

ROOT = Path(__file__).resolve().parents[2]
SCHEDULING_V35_DATASET = ROOT / "data/eval_datasets/scheduling_v35.jsonl"


def _event_data(state: WorkspaceState) -> list[dict[str, Any]]:
    return [record.data for record in state.events if record.status == "booked"]


def _strict_gold(
    row: Any, initial_state: WorkspaceState
) -> tuple[GoldFinalState, list[dict[str, str]] | None]:
    gold = row.gold
    if gold.get("intent") == "none" or not gold.get("date"):
        return GoldFinalState(), None
    if row.meta.get("pre_book") and gold.get("time"):
        return GoldFinalState(), None

    exact_time = gold.get("time")
    allowed_slots = enumerate_feasible_slots(
        participants=gold["participants"],
        organizer=gold["organizer"],
        date_start=gold["date"],
        date_end=gold["date"],
        duration_minutes=int(gold["duration_minutes"]),
        location=gold.get("location"),
        existing_events=_event_data(initial_state),
        exact_time=exact_time,
        relax_infeasible_exact=False,
    )
    if not allowed_slots:
        return GoldFinalState(), []

    data: dict[str, Any] = {
        "organizer": gold["organizer"],
        "date": gold["date"],
        "duration_minutes": gold["duration_minutes"],
        "mode": gold["mode"],
    }
    accepted: dict[str, list[Any]] = {}
    if exact_time:
        data.update(
            {
                "start": exact_time,
                "end": add_minutes(exact_time, int(gold["duration_minutes"])),
            }
        )
    else:
        accepted["start"] = [slot["start"] for slot in allowed_slots]
    accepted_locations = gold.get("accepted_location_values") or []
    if accepted_locations:
        accepted["location"] = accepted_locations
    return (
        GoldFinalState(
            required_records=[
                ExpectedRecord(
                    store="events",
                    type="event",
                    status="booked",
                    data=data,
                    exact_data={"participants": gold["participants"]},
                    accepted_data=accepted,
                )
            ]
        ),
        allowed_slots,
    )


def _condition(
    index: int,
    row: Any,
    raw: dict[str, Any],
    *,
    optimised: bool,
    result_status: str,
) -> EvalCase:
    now = datetime.fromisoformat(row.meta["now"])
    store = _seed_wf2(row, now)
    recorder = _recorder(
        store,
        run_id="wf2-v35-paired",
        dataset_label="scheduling_v35",
        dataset_paths=[SCHEDULING_V35_DATASET],
        cache_path=SCHEDULING_V343_CACHE,
        model=TEXT_MODEL,
        seed=index,
        result_status=result_status,
    )

    if optimised:
        spec = normalise_spec(raw, now=now)
        recommendation = recommend_candidates(spec, store, now=now, actor="alice")
        candidate = recommendation["candidates"][0] if recommendation["candidates"] else None
        selected = candidate
        if candidate and spec.get("exact_time") and candidate["start"] != spec["exact_time"]:
            selected = None
        execution = (
            lifecycle_mutation(
                spec=spec,
                candidate=selected,
                store=store,
                actor="alice",
                idempotency_key=f"wf2-v35:{index}",
                validation_token=recommendation.get("validation_token"),
                calendar_version=recommendation.get("calendar_version"),
                now=now,
            )
            if selected
            else {"status": "no_approved_candidate"}
        )
        checks = [{"recommendation": recommendation, "execution": execution}]
    else:
        # Both arms receive the same acting-user context.  V3.4.3 omitted this adapter
        # field for Quick Create and would otherwise confound organiser scoring.
        baseline_input = dict(raw)
        baseline_input["organizer"] = "alice"
        event, missing, flags = validate_scheduling(baseline_input, store, now=now)
        execution = {"status": "needs_input", "missing": missing}
        if not missing:
            execution = execute_scheduling(
                event,
                store,
                decision="approve",
                now=now,
                calendar_backend=MockCalendarBackend(),
                override_soft_flags=bool(flags),
                override_reason=(
                    "Scripted evaluator approved surfaced warnings" if flags else None
                ),
            )
        checks = [{"missing": missing, "execution": execution}]

    gold, allowed_slots = _strict_gold(row, recorder.initial_state)
    diagnostics: dict[str, Any] = {
        "wf2_v35_gold_contract": "strict_final_state_v1",
    }
    if allowed_slots is not None:
        diagnostics["wf2_v35_allowed_slots"] = allowed_slots
    return recorder.finish(
        case_id=f"wf2-{index:04d}",
        workflow="wf2",
        condition=(
            "optimised_smart_schedule" if optimised else "baseline_quick_create"
        ),
        scenario_tier=row.meta["tier"],
        gold_final_state=gold,
        model_draft=raw,
        deterministic_checks=checks,
        diagnostics=diagnostics,
        review_action={"decision": "approve"},
        reviewer_type="scripted",
        interaction_count=1,
    )


def build_wf2_v35_paired_cases(
    *, limit: int | None = None, result_status: str = "v3_5_verification"
) -> list[EvalCase]:
    rows = _take(load_sched_cases(str(SCHEDULING_V35_DATASET)), limit)
    cache = _indexed(SCHEDULING_V343_CACHE)
    output: list[EvalCase] = []
    for index, row in enumerate(rows):
        if index not in cache:
            raise RuntimeError(f"missing frozen WF2 V3.5 output {index}")
        output.extend(
            [
                _condition(
                    index,
                    row,
                    cache[index],
                    optimised=False,
                    result_status=result_status,
                ),
                _condition(
                    index,
                    row,
                    cache[index],
                    optimised=True,
                    result_status=result_status,
                ),
            ]
        )
    return output
