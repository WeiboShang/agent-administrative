"""Offline adapters from frozen WF1-WF3 caches to the Evaluation v3 contract.

No model is called. Each adapter replays an existing cached extraction through the real
deterministic workflow code on a fresh in-memory RecordStore, captures before/after state,
and emits the same EvalCase shape used by the API and future frontend.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from ..agent.vision_extract import receipt_to_fields
from ..backends.calendar_backend import MockCalendarBackend
from ..backends.records import RecordStore
from ..fixtures import org
from ..workflows.expense import (
    decide_expense_evidence,
    submit_expense_evidence,
    validate_and_complete_expense,
)
from .legacy_expense import decide_expense_baseline, submit_expense_baseline
from ..workflows.scheduling import execute_scheduling, validate_scheduling
from ..workflows.scheduling_lifecycle import (
    lifecycle_mutation,
    normalise_spec,
    recommend_candidates,
)
from ..workflows.triage import route_action, validate_triage
from .outcomes_v3 import (
    EvalCase,
    EvalCaseRecorder,
    ExpectedRecord,
    GoldFinalState,
    ResultStatus,
)
from .provenance_v3 import (
    dataset_version,
    frozen_cache_version,
    git_commit,
    source_version,
)
from .realiser import load_sched_cases, load_thread_cases
from .receipt_score import load_manifest
from .task_success import _expense_matches, _sched_matches

TRIAGE_DATASET = "data/eval_datasets/triage_realised.jsonl"
TRIAGE_CACHE = "data/eval_cache/triage_openai-gpt-oss-120b_realised_v33.jsonl"
SCHEDULING_DATASET = "data/eval_datasets/scheduling_realised.jsonl"
SCHEDULING_CACHE = "data/eval_cache/scheduling_openai-gpt-oss-120b_realised_v33.jsonl"
RECEIPT_MANIFEST = "data/receipts/synthetic_v2/manifest.jsonl"
RECEIPT_CACHE = "data/eval_cache/receipts_qwen3.6-27b_synthetic_v2.jsonl"
TEXT_MODEL = "openai/gpt-oss-120b"
VISION_MODEL = "qwen/qwen3.6-27b"


def _recorder(
    store: RecordStore,
    *,
    run_id: str,
    dataset_label: str,
    dataset_paths: list[str],
    cache_path: str,
    model: str,
    seed: int,
    result_status: ResultStatus,
) -> EvalCaseRecorder:
    return EvalCaseRecorder(
        store,
        run_id=run_id,
        git_commit=git_commit(),
        dataset_version=dataset_version(dataset_label, dataset_paths),
        model=model,
        config_version=source_version(),
        prompt_version=frozen_cache_version(cache_path),
        result_status=result_status,
        seed=seed,
    )


def _load_indexed(path: str) -> dict[int, dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        return {
            row["i"]: row["x"]
            for line in handle
            if line.strip()
            for row in [json.loads(line)]
        }


def _load_images(path: str) -> dict[str, dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        return {
            row["image"]: row["extraction"]
            for line in handle
            if line.strip()
            for row in [json.loads(line)]
        }


def _take(rows: list[Any], limit: int | None) -> list[Any]:
    return rows if limit is None else rows[: max(0, limit)]


def _wf1_types_match(gold: dict[str, Any], actions: list[dict[str, Any]]) -> bool:
    expected = sorted(
        kind
        for kind in gold["action_types"]
        if kind in {"schedule_meeting", "expense_claim"}
    )
    actual = sorted(
        action.get("action_type")
        for action in actions
        if action.get("action_type") in {"schedule_meeting", "expense_claim"}
    )
    return actual == expected


def _wf2_draft_matches(
    gold: dict[str, Any], event: dict[str, Any], missing: list[str]
) -> bool:
    actionable = bool(
        gold.get("intent") != "none" and gold.get("date") and gold.get("time")
    )
    return _sched_matches(event, gold) if actionable else bool(missing)


def _wf2_expected_data(gold: dict[str, Any], tier: str) -> dict[str, Any]:
    data = {
        "date": gold["date"],
        "duration_minutes": gold["duration_minutes"],
        "participants": [person for person in gold["participants"] if person != "alice"],
    }
    if tier != "stateful_conflict":
        data["start"] = gold["time"]
    return data


def _wf3_draft_matches(
    entry: dict[str, Any], fields: dict[str, Any], extraction: dict[str, Any]
) -> bool:
    if not entry["meta"].get("is_receipt", True):
        return bool(extraction.get("not_a_receipt")) or (
            not fields.get("vendor") and fields.get("amount") is None
        )
    return _expense_matches(fields, entry["gold"])


def build_wf1_cases(
    *, limit: int | None = None, result_status: ResultStatus = "legacy_pilot"
) -> list[EvalCase]:
    frozen = load_thread_cases(TRIAGE_DATASET)
    cached = _load_indexed(TRIAGE_CACHE)
    selected = _take(
        [(index, case) for index, case in enumerate(frozen) if index in cached], limit
    )
    cases = []
    now = datetime(2026, 6, 30, 9, 0)
    for index, frozen_case in selected:
        store = RecordStore(":memory:")
        org.seed_from_org(store, today=now.date())
        recorder = _recorder(
            store,
            run_id="wf1-frozen-cached",
            dataset_label="triage_realised",
            dataset_paths=[TRIAGE_DATASET],
            cache_path=TRIAGE_CACHE,
            model=TEXT_MODEL,
            seed=index,
            result_status=result_status,
        )
        thread_id = f"eval-thread-{index:04d}"
        message = {"message_id": f"msg-{index:04d}-001", "body": frozen_case.raw_text}
        draft = validate_triage(
            cached[index], thread_id=thread_id, messages=[message], now=now
        )
        route_results = []
        for action in draft["detected_actions"]:
            if action.get("action_type") in {"schedule_meeting", "expense_claim"}:
                route_results.append(
                    route_action(
                        action, store, now=now, acting_user="alice", thread_id=thread_id
                    )
                )

        required = []
        counts = {
            kind: frozen_case.gold["action_types"].count(kind)
            for kind in ("schedule_meeting", "expense_claim")
        }
        if counts["schedule_meeting"]:
            required.append(
                ExpectedRecord(
                    store="events",
                    type="schedule_meeting",
                    count=counts["schedule_meeting"],
                    data={"origin": {"workflow": "wf1", "thread_id": thread_id}},
                )
            )
        if counts["expense_claim"]:
            required.append(
                ExpectedRecord(
                    store="submissions",
                    type="expense_claim",
                    count=counts["expense_claim"],
                    data={"origin": {"workflow": "wf1", "thread_id": thread_id}},
                )
            )
        cases.append(
            recorder.finish(
                case_id=f"wf1-{index:04d}",
                workflow="wf1",
                condition="optimised_cached",
                scenario_tier=frozen_case.meta["tier"],
                gold_final_state=GoldFinalState(required_records=required),
                model_draft=draft,
                deterministic_checks=[{"route_results": route_results}],
                review_action="route",
                draft_outcome=_wf1_types_match(
                    frozen_case.gold, draft["detected_actions"]
                ),
                interaction_count=len(route_results),
            )
        )
    return cases


def build_wf2_cases(
    *, limit: int | None = None, result_status: ResultStatus = "legacy_pilot"
) -> list[EvalCase]:
    frozen = load_sched_cases(SCHEDULING_DATASET)
    cached = _load_indexed(SCHEDULING_CACHE)
    selected = _take(
        [(index, case) for index, case in enumerate(frozen) if index in cached], limit
    )
    cases = []
    for index, frozen_case in selected:
        now = datetime.fromisoformat(frozen_case.meta["now"])
        store = RecordStore(":memory:")
        org.seed_from_org(store, today=now.date())
        if prebook := frozen_case.meta.get("pre_book"):
            store.create("events", "event", prebook, status="booked")
        recorder = _recorder(
            store,
            run_id="wf2-frozen-cached",
            dataset_label="scheduling_realised",
            dataset_paths=[SCHEDULING_DATASET],
            cache_path=SCHEDULING_CACHE,
            model=TEXT_MODEL,
            seed=index,
            result_status=result_status,
        )
        event, missing, flags = validate_scheduling(cached[index], store, now=now)
        execution = execute_scheduling(
            event,
            store,
            decision="approve",
            now=now,
            calendar_backend=MockCalendarBackend(),
            override_soft_flags=bool(flags),
            override_reason="Scripted evaluator approved surfaced warnings" if flags else None,
        )
        gold = frozen_case.gold
        actionable = bool(
            gold.get("intent") != "none" and gold.get("date") and gold.get("time")
        )
        required = []
        if actionable:
            required.append(
                ExpectedRecord(
                    store="events",
                    type="event",
                    status="booked",
                    data=_wf2_expected_data(gold, frozen_case.meta["tier"]),
                )
            )
        cases.append(
            recorder.finish(
                case_id=f"wf2-{index:04d}",
                workflow="wf2",
                condition="cached_auto_review",
                scenario_tier=frozen_case.meta["tier"],
                gold_final_state=GoldFinalState(required_records=required),
                model_draft=cached[index],
                deterministic_checks=[
                    {
                        "missing": missing,
                        "flags": [
                            {"rule": flag.rule, "severity": flag.severity}
                            for flag in flags
                        ],
                        "execution": execution,
                    }
                ],
                review_action="approve",
                draft_outcome=_wf2_draft_matches(gold, event, missing),
                interaction_count=1,
            )
        )
    return cases


def _gold_expense_state(entry: dict[str, Any], store: RecordStore) -> GoldFinalState:
    """Describe the correct final claim state under the frozen V3.3 policy.

    Hard violations must finish explicitly rejected; merely attempting approval and being
    left submitted by the safety gate is not task completion. Other valid receipts must
    finish approved. Non-receipts must create no claim.
    """
    if not entry["meta"].get("is_receipt", True):
        return GoldFinalState()
    gold = entry["gold"]
    fields = {
        "employee_name": "Alice Tan",
        "business_purpose": "Business expense",
        **{
            key: gold.get(key)
            for key in (
                "vendor",
                "date",
                "amount",
                "currency",
                "category",
                "line_items",
            )
        },
    }
    flags = validate_and_complete_expense(fields, store).flags
    has_hard = any(flag.severity == "hard" for flag in flags)
    expected = ExpectedRecord(
        store="submissions",
        type="expense_claim",
        status="rejected" if has_hard else "approved",
        data={key: gold.get(key) for key in ("vendor", "date", "amount", "currency")},
    )
    forbidden = []
    return GoldFinalState(required_records=[expected], forbidden_records=forbidden)


def build_wf3_cases(
    *, limit: int | None = None, result_status: ResultStatus = "legacy_pilot"
) -> list[EvalCase]:
    manifest = load_manifest(RECEIPT_MANIFEST)
    cached = _load_images(RECEIPT_CACHE)
    selected = _take([entry for entry in manifest if entry["image"] in cached], limit)
    cases = []
    for index, entry in enumerate(selected):
        store = RecordStore(":memory:")
        org.seed_from_org(store)
        gold_final_state = _gold_expense_state(entry, store)
        recorder = _recorder(
            store,
            run_id="wf3-frozen-cached",
            dataset_label="synthetic_v2",
            dataset_paths=[RECEIPT_MANIFEST, "data/receipts/synthetic_v2"],
            cache_path=RECEIPT_CACHE,
            model=VISION_MODEL,
            seed=index,
            result_status=result_status,
        )
        extraction = cached[entry["image"]]
        fields = receipt_to_fields(
            extraction, employee_name="Alice Tan", business_purpose="Business expense"
        )
        submitted = submit_expense_baseline(fields, store, submitted_by="alice")
        decision = None
        if submitted.get("record_id"):
            decision = decide_expense_baseline(
                submitted["record_id"], store, decision="approve", reviewed_by="bob"
            )

        cases.append(
            recorder.finish(
                case_id=f"wf3-{entry['image']}",
                workflow="wf3",
                condition="cached_auto_review",
                scenario_tier=entry["meta"]["tier"],
                gold_final_state=gold_final_state,
                model_draft=extraction,
                deterministic_checks=[{"submission": submitted, "decision": decision}],
                review_action="approve",
                draft_outcome=_wf3_draft_matches(entry, fields, extraction),
                interaction_count=2 if decision else 1,
            )
        )
    return cases


def build_frozen_suite(
    *,
    limit_per_workflow: int | None = None,
    result_status: ResultStatus = "legacy_pilot",
) -> list[EvalCase]:
    required_paths = [
        TRIAGE_DATASET,
        TRIAGE_CACHE,
        SCHEDULING_DATASET,
        SCHEDULING_CACHE,
        RECEIPT_MANIFEST,
        RECEIPT_CACHE,
    ]
    missing = [path for path in required_paths if not os.path.exists(path)]
    if missing:
        raise FileNotFoundError(f"missing frozen evaluation inputs: {missing}")
    return [
        *build_wf1_cases(limit=limit_per_workflow, result_status=result_status),
        *build_wf2_cases(limit=limit_per_workflow, result_status=result_status),
        *build_wf3_cases(limit=limit_per_workflow, result_status=result_status),
    ]


def _wf1_gold(frozen_case: Any, thread_id: str) -> GoldFinalState:
    required = []
    meeting_count = frozen_case.gold["action_types"].count("schedule_meeting")
    expense_count = frozen_case.gold["action_types"].count("expense_claim")
    if meeting_count:
        required.append(
            ExpectedRecord(
                store="events",
                type="schedule_meeting",
                count=meeting_count,
                data={"origin": {"workflow": "wf1", "thread_id": thread_id}},
            )
        )
    if expense_count:
        required.append(
            ExpectedRecord(
                store="submissions",
                type="expense_claim",
                count=expense_count,
                data={"origin": {"workflow": "wf1", "thread_id": thread_id}},
            )
        )
    return GoldFinalState(required_records=required)


def _paired_wf1_baselines(
    *, limit: int | None, result_status: ResultStatus
) -> list[EvalCase]:
    frozen = load_thread_cases(TRIAGE_DATASET)
    cached = _load_indexed(TRIAGE_CACHE)
    selected = _take([(i, case) for i, case in enumerate(frozen) if i in cached], limit)
    rows = []
    now = datetime(2026, 6, 30, 9, 0)
    for index, frozen_case in selected:
        store = RecordStore(":memory:")
        org.seed_from_org(store, today=now.date())
        recorder = _recorder(
            store,
            run_id="wf1-paired",
            dataset_label="triage_realised",
            dataset_paths=[TRIAGE_DATASET],
            cache_path=TRIAGE_CACHE,
            model=TEXT_MODEL,
            seed=index,
            result_status=result_status,
        )
        results = []
        # Gate 0 route supported meetings and executed them immediately.
        for action in cached[index].get("detected_actions") or []:
            if action.get("action_type") != "schedule_meeting":
                continue
            seed = dict(action.get("seed_fields") or {})
            seed["organizer"] = "alice"
            event, missing, flags = validate_scheduling(seed, store, now=now)
            execution = (
                {"status": "needs_input", "missing": missing}
                if missing
                else execute_scheduling(
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
            )
            results.append(
                {
                    "execution": execution,
                    "flags": [{"rule": f.rule, "severity": f.severity} for f in flags],
                }
            )
        thread_id = f"eval-thread-{index:04d}"
        rows.append(
            recorder.finish(
                case_id=f"wf1-{index:04d}",
                workflow="wf1",
                condition="baseline_gate0_route",
                scenario_tier=frozen_case.meta["tier"],
                gold_final_state=_wf1_gold(frozen_case, thread_id),
                model_draft=cached[index],
                deterministic_checks=results,
                review_action="route",
                draft_outcome=_wf1_types_match(
                    frozen_case.gold,
                    [
                        action
                        for action in cached[index].get("detected_actions") or []
                        if action.get("action_type") == "schedule_meeting"
                    ],
                ),
                interaction_count=len(results),
            )
        )
    return rows


def build_wf1_paired_cases(
    *, limit: int | None = None, result_status: ResultStatus = "legacy_pilot"
) -> list[EvalCase]:
    baseline = _paired_wf1_baselines(limit=limit, result_status=result_status)
    optimised = build_wf1_cases(limit=limit, result_status=result_status)
    for case in optimised:
        case.run_id = "wf1-paired"
        case.condition = "optimised_draft_only"
    return [case for pair in zip(baseline, optimised) for case in pair]


def _wf2_optimised_cases(
    *, limit: int | None, result_status: ResultStatus
) -> list[EvalCase]:
    frozen = load_sched_cases(SCHEDULING_DATASET)
    cached = _load_indexed(SCHEDULING_CACHE)
    selected = _take([(i, case) for i, case in enumerate(frozen) if i in cached], limit)
    rows = []
    for index, frozen_case in selected:
        now = datetime.fromisoformat(frozen_case.meta["now"])
        store = RecordStore(":memory:")
        org.seed_from_org(store, today=now.date())
        if prebook := frozen_case.meta.get("pre_book"):
            store.create("events", "event", prebook, status="booked")
        recorder = _recorder(
            store,
            run_id="wf2-paired",
            dataset_label="scheduling_realised",
            dataset_paths=[SCHEDULING_DATASET],
            cache_path=SCHEDULING_CACHE,
            model=TEXT_MODEL,
            seed=index,
            result_status=result_status,
        )
        spec = normalise_spec(cached[index], now=now)
        recommendation = recommend_candidates(spec, store, now=now, actor="alice")
        candidate = (
            recommendation["candidates"][0] if recommendation["candidates"] else None
        )
        gold = frozen_case.gold
        actionable = bool(
            gold.get("intent") != "none" and gold.get("date") and gold.get("time")
        )
        selected = candidate if actionable else None
        execution = (
            lifecycle_mutation(
                spec=spec,
                candidate=selected,
                store=store,
                actor="alice",
                idempotency_key=f"wf2-paired:{index}",
                validation_token=recommendation.get("validation_token"),
                calendar_version=recommendation.get("calendar_version"),
            )
            if selected
            else {
                "status": (
                    "candidate_selection_required" if candidate else "no_candidate"
                )
            }
        )
        participant_ids = [
            person.user_id
            for name in spec["participant_names"]
            if (person := org.find_person(name))
        ]
        draft_event = {
            "date": candidate.get("date") if candidate else None,
            "start": candidate.get("start") if candidate else None,
            "duration_minutes": spec["duration_minutes"],
            "participants": participant_ids,
        }
        draft_ok = _wf2_draft_matches(
            gold, draft_event, [] if actionable and candidate else ["candidate"]
        )
        required = []
        if actionable:
            required.append(
                ExpectedRecord(
                    store="events",
                    type="event",
                    status="booked",
                    data=_wf2_expected_data(gold, frozen_case.meta["tier"]),
                )
            )
        rows.append(
            recorder.finish(
                case_id=f"wf2-{index:04d}",
                workflow="wf2",
                condition="optimised_smart_schedule",
                scenario_tier=frozen_case.meta["tier"],
                gold_final_state=GoldFinalState(required_records=required),
                model_draft=cached[index],
                deterministic_checks=[
                    {"recommendation": recommendation, "execution": execution}
                ],
                review_action={"decision": "approve"}
                if selected
                else {"decision": "review"},
                draft_outcome=draft_ok,
                interaction_count=2 if selected else 1,
            )
        )
    return rows


def build_wf2_paired_cases(
    *, limit: int | None = None, result_status: ResultStatus = "legacy_pilot"
) -> list[EvalCase]:
    baseline = build_wf2_cases(limit=limit, result_status=result_status)
    for case in baseline:
        case.run_id = "wf2-paired"
        case.condition = "baseline_quick_create"
    optimised = _wf2_optimised_cases(limit=limit, result_status=result_status)
    return [case for pair in zip(baseline, optimised) for case in pair]


def _wf3_optimised_cases(
    *, limit: int | None, result_status: ResultStatus
) -> list[EvalCase]:
    """Replay the production evidence/policy gate without access to gold.

    V3.2 used ``_source_corrections`` as an oracle-assisted reviewer upper bound. V3.3
    keeps that historical result immutable but removes oracle corrections from the primary
    system comparison: the scripted gate may only inspect extracted fields, completeness
    and deterministic policy flags.
    """
    manifest = load_manifest(RECEIPT_MANIFEST)
    cached = _load_images(RECEIPT_CACHE)
    selected = _take([entry for entry in manifest if entry["image"] in cached], limit)
    rows = []
    for index, entry in enumerate(selected):
        store = RecordStore(":memory:")
        org.seed_from_org(store)
        gold_final_state = _gold_expense_state(entry, store)
        recorder = _recorder(
            store,
            run_id="wf3-paired",
            dataset_label="synthetic_v2",
            dataset_paths=[RECEIPT_MANIFEST, "data/receipts/synthetic_v2"],
            cache_path=RECEIPT_CACHE,
            model=VISION_MODEL,
            seed=index,
            result_status=result_status,
        )
        extraction = cached[entry["image"]]
        fields = receipt_to_fields(
            extraction, employee_name="Alice Tan", business_purpose="Business expense"
        )
        submitted = (
            submit_expense_evidence(
                fields,
                store,
                submitted_by="alice",
                extraction_snapshot=extraction,
                second_read=extraction,
                evidence={"receipt_ref": entry["image"]},
                idempotency_key=f"wf3-v33-submit:{entry['image']}",
            )
            if entry["meta"].get("is_receipt", True)
            else {"status": "refused_non_receipt"}
        )
        decision = None
        review_action: dict[str, Any] = {"decision": "request_information"}
        if submitted.get("record_id"):
            record = store.get(submitted["record_id"])
            assert record is not None
            flags = record.data.get("policy_flags", [])
            hard = [flag for flag in flags if flag.get("severity") == "hard"]
            soft = [
                flag["rule"]
                for flag in flags
                if flag.get("severity") == "soft"
            ]
            selected_decision = "reject" if hard else "approve"
            reason = (
                "; ".join(str(flag.get("message")) for flag in hard)
                if hard else "Acknowledged deterministic policy warning" if soft else None
            )
            decision = decide_expense_evidence(
                submitted["record_id"],
                store,
                decision=selected_decision,
                reviewed_by="bob",
                expected_version=int(record.data.get("version") or 1),
                reason=reason,
                acknowledged_flags=soft,
                idempotency_key=f"wf3-v33-decision:{entry['image']}",
            )
            review_action = {
                "decision": selected_decision,
                "policy": "gold_free_deterministic_policy_gate",
            }
        elif submitted.get("status") == "refused_non_receipt":
            review_action = {
                "decision": "no_action",
                "policy": "gold_free_non_receipt_refusal",
            }
        rows.append(
            recorder.finish(
                case_id=f"wf3-{entry['image']}",
                workflow="wf3",
                condition="optimised_policy_gate",
                scenario_tier=entry["meta"]["tier"],
                gold_final_state=gold_final_state,
                model_draft=extraction,
                deterministic_checks=[{
                    "submission": submitted,
                    "source_review": {
                        "policy": "gold_free_no_oracle_correction",
                        "corrected_fields": [],
                    },
                    "decision": decision,
                }],
                review_action=review_action,
                reviewer_type="scripted",
                draft_outcome=_wf3_draft_matches(entry, fields, extraction),
                changed_fields=[],
                interaction_count=1 + int(decision is not None),
            )
        )
    return rows


def build_wf3_paired_cases(
    *, limit: int | None = None, result_status: ResultStatus = "legacy_pilot"
) -> list[EvalCase]:
    baseline = build_wf3_cases(limit=limit, result_status=result_status)
    for case in baseline:
        case.run_id = "wf3-paired"
        case.condition = "baseline_legacy_review"
    optimised = _wf3_optimised_cases(limit=limit, result_status=result_status)
    return [case for pair in zip(baseline, optimised) for case in pair]


def build_paired_suite(
    *,
    limit_per_workflow: int | None = None,
    result_status: ResultStatus = "legacy_pilot",
) -> list[EvalCase]:
    return [
        *build_wf1_paired_cases(
            limit=limit_per_workflow, result_status=result_status
        ),
        *build_wf2_paired_cases(
            limit=limit_per_workflow, result_status=result_status
        ),
        *build_wf3_paired_cases(
            limit=limit_per_workflow, result_status=result_status
        ),
    ]
