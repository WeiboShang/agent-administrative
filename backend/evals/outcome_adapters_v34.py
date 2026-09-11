"""Oracle-free matched adapters for Automated Evaluation V3.4.

Gold and dataset metadata are read only after each condition has finished executing.
Both arms receive byte-identical frozen output and deterministically identical initial
workspace state.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..agent.vision_extract import (
    CRITICAL_RECEIPT_PROMPT,
    VISION_SYSTEM,
    receipt_to_fields,
)
from ..backends.calendar_backend import MockCalendarBackend
from ..backends.records import RecordStore
from ..fixtures import org
from ..workflows.expense import (
    decide_expense_evidence,
    submit_expense_evidence,
    validate_and_complete_expense,
)
from ..workflows.expense_reconciliation import reconcile_expense_evidence
from ..workflows.scheduling import execute_scheduling, validate_scheduling
from ..workflows.scheduling_lifecycle import lifecycle_mutation, normalise_spec, recommend_candidates
from ..workflows.thread_intake import normalise_seed
from ..workflows.triage import route_action, validate_triage
from .legacy_expense import decide_expense_baseline, submit_expense_baseline
from .outcomes_v3 import EvalCase, EvalCaseRecorder, ExpectedRecord, GoldFinalState, ResultStatus
from .provenance_v34 import (
    dataset_version,
    frozen_cache_bundle_version,
    frozen_cache_version,
    git_commit,
    source_version,
)
from .realiser import load_sched_cases
from .receipt_score import load_manifest
from .receipt_category_gold import observable_category_gold
from .task_success import _expense_matches

ROOT = Path(__file__).resolve().parents[2]
TRIAGE_DATASET = ROOT / "data/eval_datasets/triage_v34.jsonl"
TRIAGE_CACHE = ROOT / "data/eval_cache/triage_openai-gpt-oss-120b_v34.jsonl"
SCHEDULING_DATASET = ROOT / "data/eval_datasets/scheduling_realised.jsonl"
SCHEDULING_V341_DATASET = ROOT / "data/eval_datasets/scheduling_v341.jsonl"
SCHEDULING_V343_DATASET = ROOT / "data/eval_datasets/scheduling_v343.jsonl"
SCHEDULING_CACHE = ROOT / "data/eval_cache/scheduling_openai-gpt-oss-120b_realised_v33.jsonl"
SCHEDULING_V343_CACHE = ROOT / "data/eval_cache/scheduling_openai-gpt-oss-120b_v343.jsonl"
RECEIPT_MANIFEST = ROOT / "data/receipts/synthetic_v2/manifest.jsonl"
RECEIPT_CACHE = ROOT / "data/eval_cache/receipts_qwen3.6-27b_synthetic_v2.jsonl"
RECEIPT_CRITICAL_CACHE = ROOT / "data/eval_cache/receipts_qwen3.6-27b_critical_v342.jsonl"
RECEIPT_IMAGE_DIR = ROOT / "data/receipts/synthetic_v2"
TEXT_MODEL = "openai/gpt-oss-120b"
VISION_MODEL = "qwen/qwen3.6-27b"
V341_STATUSES = {"v3_4_1_verification", "v3_4_1_formal"}
V342_STATUSES = {"v3_4_2_verification", "v3_4_2_formal"}
V343_STATUSES = {"v3_4_3_verification", "v3_4_3_formal"}
CURRENT_STATUSES = V341_STATUSES | V342_STATUSES | V343_STATUSES
CURRENT_WF3_STATUSES = V342_STATUSES | V343_STATUSES


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _indexed(path: Path) -> dict[int, dict[str, Any]]:
    return {int(row["i"]): row["x"] for row in _jsonl(path)}


def _images(path: Path) -> dict[str, dict[str, Any]]:
    return {row["image"]: row["extraction"] for row in _jsonl(path)}


def _critical_images(path: Path) -> dict[str, dict[str, Any]]:
    rows = _jsonl(path)
    if len({row.get("image") for row in rows}) != len(rows):
        raise RuntimeError(f"duplicate images in critical cache: {path}")
    prompt_sha = hashlib.sha256(
        (VISION_SYSTEM + "\n" + CRITICAL_RECEIPT_PROMPT).encode("utf-8")
    ).hexdigest()
    for row in rows:
        image = row.get("image")
        image_path = RECEIPT_IMAGE_DIR / str(image)
        expected_image_sha = (
            hashlib.sha256(image_path.read_bytes()).hexdigest()
            if image_path.is_file() else None
        )
        if (
            row.get("schema_version") != "3.4.2"
            or row.get("model") != VISION_MODEL
            or row.get("prompt_sha256") != prompt_sha
            or row.get("image_sha256") != expected_image_sha
            or not isinstance(row.get("critical_read"), dict)
        ):
            raise RuntimeError(f"critical cache protocol mismatch: {image}")
    return {row["image"]: row["critical_read"] for row in rows}


def _take(rows: list[Any], limit: int | None) -> list[Any]:
    return rows if limit is None else rows[: max(0, limit)]


def _fixed_store(now: datetime) -> RecordStore:
    stamp = now.replace(tzinfo=timezone.utc).isoformat()
    return RecordStore(":memory:", now_fn=lambda: stamp)


def _recorder(
    store: RecordStore, *, run_id: str, dataset_label: str,
    dataset_paths: list[Path], cache_path: Path | list[Path], model: str, seed: int,
    result_status: ResultStatus,
) -> EvalCaseRecorder:
    return EvalCaseRecorder(
        store,
        run_id=run_id,
        git_commit=git_commit(),
        dataset_version=dataset_version(dataset_label, dataset_paths),
        model=model,
        config_version=source_version(),
        prompt_version=(
            frozen_cache_bundle_version(cache_path)
            if isinstance(cache_path, list) else frozen_cache_version(cache_path)
        ),
        result_status=result_status,
        seed=seed,
    )


def _wf1_gold(row: dict[str, Any], result_status: ResultStatus) -> GoldFinalState:
    required = []
    for action in row["gold"]["actions"]:
        kind = action["action_type"]
        critical = dict(action["critical_fields"])
        if result_status in CURRENT_STATUSES and kind == "expense_claim":
            # WF1 routes a source-grounded draft for downstream human verification.  Its
            # prompt exposes no canonical category taxonomy, so category cannot be an
            # exact field at this stage.  WF3 still scores canonical category.
            critical.pop("category", None)
        required.append(ExpectedRecord(
            store="events" if kind == "schedule_meeting" else "submissions",
            type=kind,
            data={
                "origin": {
                    "workflow": "wf1",
                    "thread_id": row["thread_id"],
                    "source_message_ids": [action["source_message_id"]],
                },
                "source_evidence": [{
                    "message_id": action["source_message_id"], "grounded": True
                }],
            },
            exact_data=critical,
        ))
    return GoldFinalState(required_records=required)


def _normalised_cached_actions(raw: dict[str, Any]) -> list[dict[str, Any]]:
    actions = []
    for action in raw.get("workflow_actions") or raw.get("detected_actions") or []:
        if not isinstance(action, dict):
            continue
        kind = action.get("action_type")
        actions.append({
            **action,
            "current_seed_fields": normalise_seed(
                str(kind), action.get("model_seed_fields") or action.get("seed_fields")
            ),
        })
    return actions


def _wf1_condition(
    index: int, row: dict[str, Any], raw: dict[str, Any], *, optimised: bool,
    result_status: ResultStatus,
) -> EvalCase:
    now = datetime(2026, 6, 30, 9, 0)
    store = _fixed_store(now)
    org.seed_from_org(store, today=now.date())
    recorder = _recorder(
        store, run_id="wf1-v34-paired", dataset_label="triage_v34",
        dataset_paths=[TRIAGE_DATASET], cache_path=TRIAGE_CACHE, model=TEXT_MODEL,
        seed=index, result_status=result_status,
    )
    checks: list[dict[str, Any]] = []
    if optimised:
        draft = validate_triage(
            raw, thread_id=row["thread_id"], messages=row["messages"],
            attachments=row["attachments"], now=now,
        )
        for action in draft["detected_actions"]:
            if action.get("action_type") in {"schedule_meeting", "expense_claim"}:
                checks.append(route_action(
                    action, store, now=now, acting_user="alice",
                    thread_id=row["thread_id"], attachments=row["attachments"],
                ))
    else:
        draft = {"detected_actions": _normalised_cached_actions(raw)}
        for action in draft["detected_actions"]:
            if action.get("action_type") != "schedule_meeting":
                continue
            seed = dict(action["current_seed_fields"])
            seed["organizer"] = "alice"
            event, missing, flags = validate_scheduling(seed, store, now=now)
            execution = {"status": "needs_input", "missing": missing}
            if not missing:
                execution = execute_scheduling(
                    event, store, decision="approve", now=now,
                    calendar_backend=MockCalendarBackend(),
                    override_soft_flags=bool(flags),
                    override_reason="Scripted evaluator approved surfaced warnings" if flags else None,
                )
            checks.append({"execution": execution})
    return recorder.finish(
        case_id=row["case_id"], workflow="wf1",
        condition="optimised_draft_only" if optimised else "baseline_gate0_route",
        scenario_tier=row["meta"]["tier"],
        gold_final_state=_wf1_gold(row, result_status),
        model_draft=raw, deterministic_checks=checks,
        review_action="route", reviewer_type="scripted", interaction_count=len(checks),
    )


def build_wf1_paired_cases(
    *, limit: int | None = None, result_status: ResultStatus = "v3_4_verification"
) -> list[EvalCase]:
    rows = _take(_jsonl(TRIAGE_DATASET), limit)
    cache = _indexed(TRIAGE_CACHE)
    output = []
    for index, row in enumerate(rows):
        if index not in cache:
            raise RuntimeError(f"missing frozen WF1 V3.4 output {index}")
        output.extend([
            _wf1_condition(index, row, cache[index], optimised=False, result_status=result_status),
            _wf1_condition(index, row, cache[index], optimised=True, result_status=result_status),
        ])
    return output


def _seed_wf2(row: Any, now: datetime) -> RecordStore:
    store = _fixed_store(now)
    org.seed_from_org(store, today=now.date())
    if prebook := row.meta.get("pre_book"):
        store.create("events", "event", prebook, status="booked")
    return store


def _wf2_gold(
    row: Any, result_status: ResultStatus = "v3_4_verification"
) -> GoldFinalState:
    gold = row.gold
    if gold.get("intent") == "none" or not gold.get("date"):
        return GoldFinalState()
    if row.meta.get("pre_book") and gold.get("time"):
        return GoldFinalState()
    data = {"date": gold["date"], "duration_minutes": gold["duration_minutes"]}
    if gold.get("time"):
        data["start"] = gold["time"]
    if result_status in V343_STATUSES:
        # Mode changes the realised meeting (online vs in-person), unlike free text.
        data["mode"] = gold["mode"]
    return GoldFinalState(required_records=[ExpectedRecord(
        store="events", type="event", status="booked", data=data,
        exact_data={"participants": gold["participants"]},
    )])


def _wf2_condition(
    index: int, row: Any, raw: dict[str, Any], *, optimised: bool,
    result_status: ResultStatus, dataset_path: Path = SCHEDULING_DATASET,
) -> EvalCase:
    now = datetime.fromisoformat(row.meta["now"])
    store = _seed_wf2(row, now)
    cache_path = SCHEDULING_V343_CACHE if result_status in V343_STATUSES else SCHEDULING_CACHE
    recorder = _recorder(
        store, run_id=("wf2-v343-paired" if result_status in V343_STATUSES else
                       "wf2-v342-paired" if result_status in V342_STATUSES else
                       "wf2-v341-paired" if result_status in V341_STATUSES else "wf2-v34-paired"),
        dataset_label=("scheduling_v343" if result_status in V343_STATUSES else
                       "scheduling_v341" if result_status in CURRENT_STATUSES else "scheduling_realised"),
        dataset_paths=[dataset_path], cache_path=cache_path,
        model=TEXT_MODEL, seed=index, result_status=result_status,
    )
    if optimised:
        spec = normalise_spec(raw, now=now)
        recommendation = recommend_candidates(spec, store, now=now, actor="alice")
        candidate = recommendation["candidates"][0] if recommendation["candidates"] else None
        # Source-only execution policy: exact-time requests never silently accept an
        # alternative; time-optional requests accept the deterministic best feasible slot.
        selected = candidate
        if candidate and spec.get("exact_time") and candidate["start"] != spec["exact_time"]:
            selected = None
        execution = lifecycle_mutation(
            spec=spec, candidate=selected, store=store, actor="alice",
            idempotency_key=(f"wf2-v343:{index}" if result_status in V343_STATUSES else
                             f"wf2-v342:{index}" if result_status in V342_STATUSES else
                             f"wf2-v341:{index}" if result_status in V341_STATUSES else f"wf2-v34:{index}"),
            validation_token=recommendation.get("validation_token"),
            calendar_version=recommendation.get("calendar_version"), now=now,
        ) if selected else {"status": "no_approved_candidate"}
        checks = [{"recommendation": recommendation, "execution": execution}]
    else:
        event, missing, flags = validate_scheduling(raw, store, now=now)
        execution = execute_scheduling(
            event, store, decision="approve", now=now,
            calendar_backend=MockCalendarBackend(), override_soft_flags=bool(flags),
            override_reason="Scripted evaluator approved surfaced warnings" if flags else None,
        )
        checks = [{"missing": missing, "execution": execution}]
    return recorder.finish(
        case_id=f"wf2-{index:04d}", workflow="wf2",
        condition="optimised_smart_schedule" if optimised else "baseline_quick_create",
        scenario_tier=row.meta["tier"], gold_final_state=_wf2_gold(row, result_status),
        model_draft=raw, deterministic_checks=checks,
        review_action={"decision": "approve"}, reviewer_type="scripted", interaction_count=1,
    )


def build_wf2_paired_cases(
    *, limit: int | None = None, result_status: ResultStatus = "v3_4_verification"
) -> list[EvalCase]:
    dataset_path = (
        SCHEDULING_V343_DATASET if result_status in V343_STATUSES else
        SCHEDULING_V341_DATASET if result_status in CURRENT_STATUSES else
        SCHEDULING_DATASET
    )
    rows = _take(load_sched_cases(str(dataset_path)), limit)
    cache = _indexed(
        SCHEDULING_V343_CACHE if result_status in V343_STATUSES else SCHEDULING_CACHE
    )
    output = []
    for index, row in enumerate(rows):
        output.extend([
            _wf2_condition(
                index, row, cache[index], optimised=False,
                result_status=result_status, dataset_path=dataset_path,
            ),
            _wf2_condition(
                index, row, cache[index], optimised=True,
                result_status=result_status, dataset_path=dataset_path,
            ),
        ])
    return output


def _wf3_gold(
    entry: dict[str, Any], store: RecordStore, result_status: ResultStatus
) -> GoldFinalState:
    if not entry["meta"].get("is_receipt", True):
        return GoldFinalState()
    gold = entry["gold"]
    fields = {
        "employee_name": "Alice Tan", "business_purpose": "Business expense",
        **{key: gold.get(key) for key in
           ("vendor", "date", "amount", "currency", "category", "line_items")},
    }
    accepted_data: dict[str, list[Any]] = {}
    if result_status in CURRENT_WF3_STATUSES:
        semantic = observable_category_gold(gold)
        policy_results: dict[str, bool] = {}
        for category in semantic.accepted:
            candidate = {**fields, "category": category}
            policy_results[category] = any(
                flag.severity == "hard"
                for flag in validate_and_complete_expense(candidate, store).flags
            )
        if len(set(policy_results.values())) != 1:
            raise RuntimeError(
                f"policy-sensitive category ambiguity in {entry['image']}: {policy_results}"
            )
        accepted_data["category"] = list(semantic.accepted)
        hard = next(iter(policy_results.values()))
    else:
        hard = any(flag.severity == "hard" for flag in validate_and_complete_expense(fields, store).flags)
    exact = ("vendor", "date", "amount", "currency") if accepted_data else (
        "vendor", "date", "amount", "currency", "category"
    )
    return GoldFinalState(required_records=[ExpectedRecord(
        store="submissions", type="expense_claim",
        status="rejected" if hard else "approved",
        data={key: gold.get(key) for key in exact},
        accepted_data=accepted_data,
    )])


def _wf3_condition(
    index: int, entry: dict[str, Any], extraction: dict[str, Any], *, optimised: bool,
    result_status: ResultStatus, critical_read: dict[str, Any] | None = None,
) -> EvalCase:
    now = datetime(2026, 7, 1, 9, 0)
    store = _fixed_store(now)
    org.seed_from_org(store, today=now.date())
    recorder = _recorder(
        store, run_id=("wf3-v343-paired" if result_status in V343_STATUSES else
                       "wf3-v342-paired" if result_status in V342_STATUSES else "wf3-v34-paired"),
        dataset_label="synthetic_v2",
        dataset_paths=[RECEIPT_MANIFEST, ROOT / "data/receipts/synthetic_v2"],
        cache_path=(
            [RECEIPT_CACHE, RECEIPT_CRITICAL_CACHE]
            if result_status in CURRENT_WF3_STATUSES else RECEIPT_CACHE
        ),
        model=VISION_MODEL, seed=index,
        result_status=result_status,
    )
    fields = receipt_to_fields(
        extraction, employee_name="Alice Tan", business_purpose="Business expense"
    )
    fixed_now = now.replace(tzinfo=timezone.utc).isoformat()
    decision = None
    review_decision = "no_action"
    reconciliation = {
        "status": "not_applied", "changed_fields": [], "requires_review": False,
    }
    if optimised:
        if result_status in CURRENT_WF3_STATUSES:
            fields, reconciliation = reconcile_expense_evidence(
                fields, extraction, store, second_read=critical_read
            )
        submitted = {"status": "refused_non_receipt"} if extraction.get("not_a_receipt") else submit_expense_evidence(
            fields, store, submitted_by="alice", extraction_snapshot=extraction,
            second_read=(critical_read if result_status in CURRENT_WF3_STATUSES else extraction),
            evidence={"receipt_ref": entry["image"]},
            idempotency_key=(
                f"wf3-v343-submit:{entry['image']}" if result_status in V343_STATUSES else
                f"wf3-v342-submit:{entry['image']}" if result_status in V342_STATUSES else
                f"wf3-v34-submit:{entry['image']}"
            ),
            now=fixed_now,
        )
        if submitted.get("record_id") and not reconciliation.get("requires_review"):
            record = store.get(submitted["record_id"])
            assert record is not None
            flags = record.data.get("policy_flags", [])
            hard = [flag for flag in flags if flag.get("severity") == "hard"]
            soft = [flag["rule"] for flag in flags if flag.get("severity") == "soft"]
            selected = "reject" if hard else "approve"
            review_decision = selected
            decision = decide_expense_evidence(
                record.id, store, decision=selected, reviewed_by="bob",
                expected_version=int(record.data.get("version") or 1),
                reason=(
                    "; ".join(str(flag.get("message")) for flag in hard) or
                    ("Acknowledged deterministic policy warning" if soft and result_status in CURRENT_WF3_STATUSES else None)
                ),
                acknowledged_flags=soft,
                idempotency_key=(
                    f"wf3-v343-decision:{entry['image']}" if result_status in V343_STATUSES else
                    f"wf3-v342-decision:{entry['image']}" if result_status in V342_STATUSES else
                    f"wf3-v34-decision:{entry['image']}"
                ),
                now=fixed_now,
            )
        elif submitted.get("record_id"):
            review_decision = "no_action"
            decision = {"status": "needs_human_review"}
    else:
        review_decision = "approve"
        submitted = submit_expense_baseline(fields, store, submitted_by="alice")
        if submitted.get("record_id"):
            decision = decide_expense_baseline(
                submitted["record_id"], store, decision="approve", reviewed_by="bob"
            )
    draft_ok = bool(extraction.get("not_a_receipt")) if not entry["meta"].get("is_receipt", True) else _expense_matches(fields, entry["gold"])
    gold_store = _fixed_store(now)
    org.seed_from_org(gold_store, today=now.date())
    return recorder.finish(
        case_id=f"wf3-{entry['image']}", workflow="wf3",
        condition="optimised_policy_gate" if optimised else "baseline_legacy_review",
        scenario_tier=entry["meta"]["tier"],
        gold_final_state=_wf3_gold(entry, gold_store, result_status),
        model_draft=(
            {"primary_read": extraction, "critical_read": critical_read}
            if result_status in CURRENT_WF3_STATUSES else extraction
        ),
        deterministic_checks=[{
            "submission": submitted, "decision": decision,
            "reconciliation": reconciliation,
            "independent_second_read": (
                "frozen_critical_read" if critical_read is not None
                else "unavailable" if result_status in CURRENT_WF3_STATUSES
                else "legacy_reused_primary"
            ),
        }],
        review_action={"decision": review_decision}, reviewer_type="scripted",
        draft_outcome=draft_ok, interaction_count=1 + int(decision is not None),
    )


def build_wf3_paired_cases(
    *, limit: int | None = None, result_status: ResultStatus = "v3_4_verification"
) -> list[EvalCase]:
    rows = _take(load_manifest(str(RECEIPT_MANIFEST)), limit)
    cache = _images(RECEIPT_CACHE)
    critical = _critical_images(RECEIPT_CRITICAL_CACHE) if result_status in CURRENT_WF3_STATUSES else {}
    if result_status in CURRENT_WF3_STATUSES:
        expected = {entry["image"] for entry in rows}
        missing = expected - set(critical)
        if missing:
            raise RuntimeError(f"incomplete WF3 V3.4.2 critical cache: {sorted(missing)}")
    output = []
    for index, entry in enumerate(rows):
        extraction = cache[entry["image"]]
        output.extend([
            _wf3_condition(
                index, entry, extraction, optimised=False, result_status=result_status,
                critical_read=critical.get(entry["image"]),
            ),
            _wf3_condition(
                index, entry, extraction, optimised=True, result_status=result_status,
                critical_read=critical.get(entry["image"]),
            ),
        ])
    return output


def build_paired_suite(
    *, limit_per_workflow: int | None = None,
    result_status: ResultStatus = "v3_4_verification",
) -> list[EvalCase]:
    scheduling_dataset = (
        SCHEDULING_V343_DATASET if result_status in V343_STATUSES else
        SCHEDULING_V341_DATASET if result_status in CURRENT_STATUSES else
        SCHEDULING_DATASET
    )
    scheduling_cache = (
        SCHEDULING_V343_CACHE if result_status in V343_STATUSES else SCHEDULING_CACHE
    )
    for path in (TRIAGE_DATASET, TRIAGE_CACHE, scheduling_dataset, scheduling_cache,
                 RECEIPT_MANIFEST, RECEIPT_CACHE):
        if not path.exists():
            raise FileNotFoundError(path)
    if result_status in CURRENT_WF3_STATUSES and not RECEIPT_CRITICAL_CACHE.exists():
        raise FileNotFoundError(RECEIPT_CRITICAL_CACHE)
    return [
        *build_wf1_paired_cases(limit=limit_per_workflow, result_status=result_status),
        *build_wf2_paired_cases(limit=limit_per_workflow, result_status=result_status),
        *build_wf3_paired_cases(limit=limit_per_workflow, result_status=result_status),
    ]
