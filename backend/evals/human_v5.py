"""Human Evaluation V5: blinded Manual versus actual-Agent draft replay.

V5 deliberately separates three artifacts:

* ``human_v5_sources.json``: reviewer-visible inputs and synthetic workspace setup;
* ``human_v5_agent_outputs.jsonl``: actual production-model outputs, frozen before use;
* ``human_v5_gold.json``: server-only decisions and hard final-state predicates.

The API projection is built without reading gold.  Gold is loaded only after a submission
has been executed against a fresh in-memory mock workspace.  This physical boundary makes
answer leakage testable instead of relying on UI discipline.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import unicodedata
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..agent.vision_extract import receipt_to_fields
from ..backends.calendar_backend import MockCalendarBackend
from ..backends.records import RecordStore
from ..fixtures import org
from ..workflows.expense import (
    decide_expense_evidence,
    request_expense_information,
    submit_expense_evidence,
    validate_and_complete_expense,
)
from ..workflows.scheduling import (
    execute_scheduling,
    suggest_free_slots,
    validate_scheduling,
)
from ..workflows.scheduling_lifecycle import normalise_spec, recommend_candidates
from ..workflows.triage import route_action, validate_triage
from .results_store import load_all, save_result


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "data/eval_datasets/human_v5_manifest.json"
SOURCES_PATH = ROOT / "data/eval_datasets/human_v5_sources.json"
GOLD_PATH = ROOT / "data/eval_datasets/human_v5_gold.json"
GOLD_ADJUDICATION_PATH = ROOT / "data/eval_datasets/human_v5_gold_adjudication_v1.json"
CACHE_PATH = ROOT / "data/eval_cache/human_v5_agent_outputs.jsonl"
SESSION_DIR = ROOT / "data/eval_sessions"
RESULT_PATH = ROOT / "data/eval_results/human_v5.jsonl"
DRAFT_MODE = "frozen_actual_agent_replay"

_FORBIDDEN_PUBLIC_KEYS = {
    "expected_decision", "expected_decisions", "expected_status", "gold",
    "hard_fields", "critical_fields", "slot_policy", "correct_answer",
    "forbidden_action_types", "forbidden_slots", "forbidden_values",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha(value: bytes | str) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _file_sha(path: Path) -> str:
    return _sha(path.read_bytes())


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class ManifestCaseV5(BaseModel):
    case_id: str
    workflow: Literal["wf1", "wf2", "wf3"]
    pair_id: str
    variant: Literal["A", "B"]
    condition: Literal["manual", "agent_assisted"]
    scenario_family: str
    pilot: bool
    presentation_order: int = Field(ge=1)


class HumanManifestV5(BaseModel):
    schema_version: Literal["5.0"]
    title: str
    seed: int
    draft_mode: Literal["frozen_actual_agent_replay"]
    text_model: Literal["openai/gpt-oss-120b"]
    vision_model: Literal["qwen/qwen3.6-27b"]
    reviewers: Literal[1]
    formal_case_count: Literal[36]
    pilot_case_count: Literal[6]
    protocol_status: Literal["pre_freeze_implementation", "frozen_pre_collection"]
    frozen_at: str | None = None
    cases: list[ManifestCaseV5]


class InteractionEventV5(BaseModel):
    kind: str
    at: str | None = None
    target: str | None = None
    value: str | int | float | bool | None = None


class BrowserTimingV5(BaseModel):
    case_visible_at: str | None = None
    generation_started_at: str | None = None
    draft_ready_at: str | None = None
    review_started_at: str | None = None
    first_interaction_at: str | None = None
    decision_at: str | None = None
    case_completed_at: str | None = None
    hidden_duration_ms: int = Field(default=0, ge=0)


class ReviewedActionV5(BaseModel):
    action_type: Literal["schedule_meeting", "expense_claim"]
    fields: dict[str, Any] = Field(default_factory=dict)
    attachment_ids: list[str] = Field(default_factory=list)


class HumanCaseSubmissionV5(BaseModel):
    decision: Literal["route", "no_action", "approve", "reject", "request_information"]
    actions: list[ReviewedActionV5] = Field(default_factory=list, max_length=2)
    final_fields: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None
    acknowledge_warnings: bool = False
    interactions: list[InteractionEventV5] = Field(default_factory=list)
    timing: BrowserTimingV5 = Field(default_factory=BrowserTimingV5)
    operational_failure: str | None = None


class CaseMaterialV5(BaseModel):
    """The complete reviewer projection.  Allocation/gold never enter this model."""

    case_id: str
    workflow: Literal["wf1", "wf2", "wf3"]
    condition: Literal["manual", "agent_assisted"]
    pilot: bool
    input: dict[str, Any]
    reference: dict[str, Any]
    agent_assistance: dict[str, Any] | None
    reviewer_visible_checks: list[dict[str, Any]]
    form_defaults: dict[str, Any]
    allowed_decisions: list[str]
    draft_mode: str = DRAFT_MODE
    server_started_at: str | None = None
    server_draft_ready_at: str | None = None


def load_manifest_v5() -> HumanManifestV5:
    manifest = HumanManifestV5.model_validate(_read_json(MANIFEST_PATH))
    validate_protocol_v5(manifest, require_frozen_cache=False)
    return manifest


def _sources() -> dict[str, dict[str, Any]]:
    payload = _read_json(SOURCES_PATH)
    if payload.get("synthetic_only") is not True:
        raise RuntimeError("V5 sources must be marked synthetic_only")
    return payload["cases"]


def _gold_cases() -> dict[str, dict[str, Any]]:
    payload = _read_json(GOLD_PATH)
    if payload.get("server_only") is not True:
        raise RuntimeError("V5 gold must be marked server_only")
    cases = dict(payload["cases"])
    if GOLD_ADJUDICATION_PATH.is_file():
        adjudication = _read_json(GOLD_ADJUDICATION_PATH)
        cases.update(adjudication.get("case_overrides") or {})
    return cases


def _cache_index() -> dict[str, dict[str, Any]]:
    rows = _read_jsonl(CACHE_PATH)
    if len({row.get("case_id") for row in rows}) != len(rows):
        raise RuntimeError("V5 agent cache contains duplicate case_id values")
    return {row["case_id"]: row for row in rows}


def _agent_case_ids(manifest: HumanManifestV5) -> set[str]:
    return {row.case_id for row in manifest.cases if row.condition == "agent_assisted"}


def validate_protocol_v5(
    manifest: HumanManifestV5 | None = None, *, require_frozen_cache: bool
) -> None:
    manifest = manifest or HumanManifestV5.model_validate(_read_json(MANIFEST_PATH))
    sources = _sources()
    gold = _gold_cases() if require_frozen_cache else None
    ids = [row.case_id for row in manifest.cases]
    errors: list[str] = []
    if len(ids) != 42 or len(set(ids)) != 42:
        errors.append("manifest must contain 42 unique cases")
    if set(ids) != set(sources):
        errors.append("manifest and sources case IDs must match exactly")
    if gold is not None and set(ids) != set(gold):
        errors.append("manifest and server-only gold case IDs must match exactly")
    formal = [row for row in manifest.cases if not row.pilot]
    pilots = [row for row in manifest.cases if row.pilot]
    if len(formal) != 36 or len(pilots) != 6:
        errors.append("V5 requires six pilots and 36 formal cases")
    if sorted(row.presentation_order for row in formal) != list(range(1, 37)):
        errors.append("formal presentation order must be exactly 1..36")
    for workflow in ("wf1", "wf2", "wf3"):
        rows = [row for row in formal if row.workflow == workflow]
        if len(rows) != 12:
            errors.append(f"{workflow} requires 12 formal cases")
        if Counter(row.condition for row in rows) != {"manual": 6, "agent_assisted": 6}:
            errors.append(f"{workflow} condition allocation must be 6/6")
        if Counter(row.scenario_family for row in rows) != {
            "ordinary": 4, "underspecified_degraded": 4, "complex_safety": 4
        }:
            errors.append(f"{workflow} scenario allocation must be 4/4/4")
        for condition in ("manual", "agent_assisted"):
            subset = [row for row in rows if row.condition == condition]
            if Counter(row.scenario_family for row in subset) != {
                "ordinary": 2, "underspecified_degraded": 2, "complex_safety": 2
            }:
                errors.append(f"{workflow}/{condition} scenario allocation must be 2/2/2")
    for case_id, source in sources.items():
        if source.get("workflow") != next(row.workflow for row in manifest.cases if row.case_id == case_id):
            errors.append(f"{case_id} source workflow mismatch")
    if require_frozen_cache:
        cache = _cache_index()
        expected_cache = _agent_case_ids(manifest)
        if set(cache) != expected_cache:
            missing = sorted(expected_cache - set(cache))
            extras = sorted(set(cache) - expected_cache)
            errors.append(f"frozen cache is incomplete ({len(missing)} missing)")
            if extras:
                errors.append(f"frozen cache contains {len(extras)} Manual-case outputs")
        for case_id, row in cache.items():
            expected = _sha(_canonical_json(sources[case_id]))
            if row.get("source_sha256") != expected:
                errors.append(f"{case_id} source hash does not match frozen cache")
            workflow = next(item.workflow for item in manifest.cases if item.case_id == case_id)
            expected_model = manifest.vision_model if workflow == "wf3" else manifest.text_model
            if row.get("model") != expected_model:
                errors.append(f"{case_id} model does not match frozen protocol")
        if manifest.protocol_status != "frozen_pre_collection" or not manifest.frozen_at:
            errors.append("manifest must be frozen_pre_collection before sessions can start")
    if errors:
        raise RuntimeError("; ".join(errors))


def _bundle_hashes() -> dict[str, str | None]:
    return {
        "manifest_sha256": _file_sha(MANIFEST_PATH),
        "sources_sha256": _file_sha(SOURCES_PATH),
        "gold_sha256": _file_sha(GOLD_PATH),
        "gold_adjudication_sha256": (
            _file_sha(GOLD_ADJUDICATION_PATH)
            if GOLD_ADJUDICATION_PATH.is_file() else None
        ),
        "agent_cache_sha256": _file_sha(CACHE_PATH) if CACHE_PATH.is_file() else None,
        "evaluator_sha256": _file_sha(Path(__file__)),
        "reviewer_ui_sha256": _file_sha(
            ROOT / "frontend-next/src/pages/eval/HumanEval.tsx"
        ),
    }


def _git_state() -> dict[str, Any]:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
        dirty = bool(subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        ).strip())
        return {"commit": commit, "dirty": dirty}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def protocol_payload_v5() -> dict[str, Any]:
    manifest = load_manifest_v5()
    cache_count = len(_cache_index())
    required_cache = len(_agent_case_ids(manifest))
    ready = cache_count == required_cache and manifest.protocol_status == "frozen_pre_collection"
    return {
        "schema_version": manifest.schema_version,
        "title": manifest.title,
        "draft_mode": manifest.draft_mode,
        "text_model": manifest.text_model,
        "vision_model": manifest.vision_model,
        "seed": manifest.seed,
        "reviewer_count": manifest.reviewers,
        "formal_case_count": manifest.formal_case_count,
        "pilot_case_count": manifest.pilot_case_count,
        "protocol_status": manifest.protocol_status,
        "frozen_at": manifest.frozen_at,
        "ready_for_collection": ready,
        "cache_cases": cache_count,
        "required_cache_cases": required_cache,
        "temporal_contract": {
            "anchor": "scenario_now supplied with each case",
            "bare_weekday": "nearest strictly future occurrence",
            "this_weekday": "that weekday in the current calendar week if not passed",
            "next_weekday": "that weekday in the following calendar week",
            "example": "From Monday 2026-08-17: Tuesday and this Tuesday are 2026-08-18; next Tuesday is 2026-08-25.",
        },
        "conditions": {
            "manual": "Reviewer receives the source input, neutral references, blank fields, and gold-free policy alerts, but no conflict-resolution candidates.",
            "agent_assisted": "Reviewer receives policy alerts, an unedited replay of the frozen model extraction, a pre-filled draft, and three verified-free alternatives when the extracted slot conflicts.",
        },
        "scoring_contract": "Decision, canonical hard fields, and executed final state must all match; free-text wording is not exact-matched.",
        "analysis_boundary": "Single-reviewer descriptive within-reviewer comparison; pilots are excluded.",
        "ethics_gate": "Formal cases require explicit institutional-pathway confirmation.",
        **_bundle_hashes(),
    }


def _spec(case_id: str) -> ManifestCaseV5:
    return next(row for row in load_manifest_v5().cases if row.case_id == case_id)


def _parse_now(source: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(source.get("scenario_now") or "2026-08-17T09:00:00")


def _wf1_requester(source: dict[str, Any]) -> str | None:
    """Synthetic sender who initiated the WF1 request."""
    match = re.search(r"(?:^|\n)\[m\d+\]\s*([^:\n]+):", str(source.get("text") or ""))
    person = org.find_person(match.group(1).strip()) if match else None
    return person.name if person else None


def _with_requester(fields: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """Apply V5.1's public rule: the meeting requester attends by default."""
    result = dict(fields)
    requester = _wf1_requester(source)
    participants = result.get("participants")
    participants = participants if isinstance(participants, list) else [
        part.strip() for part in str(participants or "").split(",") if part.strip()
    ]
    requester_person = org.find_person(requester or "")
    if requester_person and not any(
        org.find_person(str(item)) == requester_person for item in participants
    ):
        participants.insert(0, requester_person.name)
    result["participants"] = participants
    return result


def _names_to_ids(values: Any) -> tuple[list[str], list[str]]:
    raw = values if isinstance(values, list) else str(values or "").split(",")
    resolved, unresolved = [], []
    for value in raw:
        name = str(value).strip()
        if not name:
            continue
        person = org.find_person(name)
        if person:
            resolved.append(person.user_id)
        else:
            unresolved.append(name)
    return list(dict.fromkeys(resolved)), unresolved


def _seed_store(source: dict[str, Any]) -> RecordStore:
    store = RecordStore()
    setup = source.get("setup") or {}
    for event in setup.get("events") or []:
        data = dict(event)
        data.setdefault("start", data.pop("time", None))
        data.setdefault("end", data.get("start"))
        data.setdefault("participant_names", data.get("participants") or [])
        store.create("events", "event", data, status="booked")
    for claim in setup.get("claims") or []:
        data = dict(claim)
        status = str(data.pop("status", "approved"))
        store.create("submissions", "expense_claim", data, status=status)
    return store


def _public_check(payload: Any) -> None:
    if isinstance(payload, dict):
        overlap = _FORBIDDEN_PUBLIC_KEYS & set(payload)
        if overlap:
            raise AssertionError(f"gold key leaked into reviewer projection: {sorted(overlap)}")
        for value in payload.values():
            _public_check(value)
    elif isinstance(payload, list):
        for value in payload:
            _public_check(value)


def _cached_raw(case_id: str) -> dict[str, Any]:
    row = _cache_index().get(case_id)
    if row is None:
        raise RuntimeError(f"actual Agent cache is not frozen for {case_id}")
    return row.get("raw_extraction") or {}


def _wf1_material(spec: ManifestCaseV5, source: dict[str, Any]) -> CaseMaterialV5:
    raw = _cached_raw(spec.case_id) if spec.condition == "agent_assisted" else None
    actions: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    if raw is not None:
        message = {"message_id": f"{spec.case_id}-m1", "body": source["text"]}
        validated = validate_triage(
            raw, thread_id=f"human-v5-{spec.case_id}", messages=[message],
            attachments=source.get("attachments") or [], now=_parse_now(source),
        )
        for action in validated.get("detected_actions") or []:
            if action.get("action_type") not in {"schedule_meeting", "expense_claim"}:
                continue
            fields = dict(action.get("current_seed_fields") or {})
            if action["action_type"] == "schedule_meeting":
                fields = _with_requester(fields, source)
            attachment_ids = list(action.get("attachment_ids") or [])
            actions.append({
                "action_type": action["action_type"],
                "fields": fields,
                "attachment_ids": attachment_ids,
            })
            missing: list[str] = []
            if action["action_type"] == "schedule_meeting":
                event, missing, flags = validate_scheduling(fields, RecordStore(), now=_parse_now(source))
                checks.append({
                    "action_type": "schedule_meeting", "missing_required": missing,
                    "policy_flags": [
                        {"rule": flag.rule, "severity": flag.severity, "message": flag.message}
                        for flag in flags
                    ],
                    "resolved_date": event.get("date"),
                })
            else:
                if not attachment_ids and not fields.get("missing_receipt_declaration"):
                    missing.append("receipt_or_alternative_evidence")
                checks.append({"action_type": "expense_claim", "missing_required": missing})
    material = CaseMaterialV5(
        case_id=spec.case_id, workflow="wf1", condition=spec.condition, pilot=spec.pilot,
        input={"kind": "thread", "text": source["text"], "attachments": source.get("attachments") or []},
        reference={
            "supported_actions": ["schedule_meeting", "expense_claim"],
            "instruction": "Create one reviewed draft for every supported final request. Preserve genuinely missing fields as blank; honour later revisions and retractions.",
            "participant_rule": "The person who requests a meeting participates by default unless the thread explicitly says they will not attend or that they are arranging it only for others.",
            "default_meeting_participant": _wf1_requester(source),
            "scenario_now": source.get("scenario_now"),
        },
        agent_assistance={"raw_extraction": raw} if raw is not None else None,
        reviewer_visible_checks=checks,
        form_defaults={"actions": actions} if raw is not None else {"actions": []},
        allowed_decisions=["route", "no_action"],
    )
    _public_check(material.model_dump(mode="json"))
    return material


def _wf2_material(spec: ManifestCaseV5, source: dict[str, Any]) -> CaseMaterialV5:
    raw = _cached_raw(spec.case_id) if spec.condition == "agent_assisted" else None
    store, now = _seed_store(source), _parse_now(source)
    defaults: dict[str, Any] = {}
    checks: list[dict[str, Any]] = []
    assistance = None
    if raw is not None:
        extraction = raw
        turns = raw.get("meetings") if isinstance(raw, dict) else None
        if isinstance(turns, list) and turns:
            # Preserve stable fields from earlier turns while the last stated values win.
            merged: dict[str, Any] = {}
            for turn in turns:
                if isinstance(turn, dict):
                    merged.update({key: value for key, value in turn.items() if value not in (None, "")})
            extraction = merged
        normalised = normalise_spec(extraction, now=now)
        participants, unresolved = _names_to_ids(normalised.get("participant_names"))
        date = normalised.get("date_window", {}).get("start")
        exact_time = normalised.get("exact_time")
        missing = []
        if not date:
            missing.append("date")
        if not exact_time:
            missing.append("time")
        if not participants or unresolved:
            missing.append("participants")
        candidates_result = (
            recommend_candidates(normalised, store, now=now, actor="alice")
            if not missing else {"candidates": [], "warnings": [], "blockers": [], "missing": missing}
        )
        candidates = candidates_result.get("candidates") or []
        defaults = {
            "title": normalised.get("title"),
            "participants": normalised.get("participant_names") or [],
            # Preserve the requested slot until the reviewer explicitly selects an
            # alternative. The reviewer is the authorised scheduling user.
            "date": date,
            "time": exact_time,
            "duration_minutes": normalised.get("duration_minutes"),
            "location": normalised.get("location"),
            "mode": normalised.get("mode"),
            "agenda": normalised.get("agenda"),
        }
        checks = [
            {"type": "essential_information", "missing": list(dict.fromkeys(missing)), "unresolved_participants": unresolved},
            {"type": "relative_date_resolution", "raw_date": raw.get("date"), "resolved_date": date, "scenario_now": source.get("scenario_now")},
            {"type": "candidate_search", "candidates": candidates, "warnings": candidates_result.get("warnings") or [], "blockers": candidates_result.get("blockers") or []},
        ]
        assistance = {"raw_extraction": raw, "normalised_draft": normalised}
    material = CaseMaterialV5(
        case_id=spec.case_id, workflow="wf2", condition=spec.condition, pilot=spec.pilot,
        input={"kind": "scheduling_request", "text": source["text"]},
        reference={
            "scenario_now": source.get("scenario_now"),
            "temporal_rule": "bare weekday = nearest future; this weekday = current calendar week if not passed; next weekday = following calendar week",
            "calendar_events": source.get("setup", {}).get("events") or [],
            "instruction": (
                "If the requested slot conflicts, manually enter another conflict-free time and approve."
                if spec.condition == "manual" else
                "If the requested slot conflicts, select one verified-free Agent suggestion and approve."
            ),
        },
        agent_assistance=assistance,
        reviewer_visible_checks=checks,
        form_defaults=defaults,
        allowed_decisions=["approve", "reject", "request_information"],
    )
    _public_check(material.model_dump(mode="json"))
    return material


def _wf3_material(spec: ManifestCaseV5, source: dict[str, Any]) -> CaseMaterialV5:
    raw = _cached_raw(spec.case_id) if spec.condition == "agent_assisted" else None
    defaults = receipt_to_fields(raw, employee_name="Alice Tan") if raw is not None else {}
    checks: list[dict[str, Any]] = []
    if raw is not None:
        missing = [field for field in ("vendor", "date", "amount", "currency") if defaults.get(field) in (None, "")]
        checks.append({"type": "evidence_completeness", "missing_critical_fields": missing})
        if not missing:
            draft = validate_and_complete_expense(defaults, _seed_store(source), extracted_amount=raw.get("amount"), line_items=raw.get("line_items") or [])
            checks.append({
                "type": "policy_review",
                "flags": [
                    {"rule": flag.rule, "severity": flag.severity, "message": flag.message}
                    for flag in draft.flags
                ],
            })
        if raw.get("not_a_receipt"):
            checks.append({"type": "document_classification", "not_a_receipt": True})
    material = CaseMaterialV5(
        case_id=spec.case_id, workflow="wf3", condition=spec.condition, pilot=spec.pilot,
        input={
            "kind": "receipt", "image_url": f"/api/eval/v5/human/assets/{spec.case_id}",
            "claimant_note": source.get("claimant_note"),
        },
        reference={
            "claimant_note": source.get("claimant_note"),
            "existing_claims": source.get("setup", {}).get("claims") or [],
            "policy_summary": "Missing critical receipt evidence requires information. Exact duplicates and category-limit breaches are hard-stop/reject cases.",
            "instruction": "Verify the receipt itself. Request information when critical evidence is unreadable; reject hard policy violations such as category-limit excesses and duplicates.",
        },
        agent_assistance={"raw_extraction": raw} if raw is not None else None,
        reviewer_visible_checks=checks,
        form_defaults=defaults,
        allowed_decisions=["approve", "reject", "request_information", "no_action"],
    )
    _public_check(material.model_dump(mode="json"))
    return material


def prepare_case_v5(case_id: str) -> CaseMaterialV5:
    spec, source = _spec(case_id), _sources()[case_id]
    if spec.workflow == "wf1":
        return _wf1_material(spec, source)
    if spec.workflow == "wf2":
        return _wf2_material(spec, source)
    return _wf3_material(spec, source)


_MEETING_INFORMATION_RULES = {"conflict", "room_double_booked"}


def preflight_case_v5(case_id: str, final_fields: dict[str, Any]) -> dict[str, Any]:
    """Gold-free, condition-neutral policy check for the editable reviewer form."""
    spec, source = _spec(case_id), _sources()[case_id]
    fields = _clean_fields(final_fields)
    alerts: list[dict[str, Any]] = []
    suggestions: list[dict[str, Any]] = []
    approve_blocked = False

    if spec.workflow == "wf2":
        event, missing, flags = validate_scheduling(fields, _seed_store(source), now=_parse_now(source))
        if missing:
            approve_blocked = True
            alerts.append({
                "rule": "missing_information", "severity": "hard",
                "title": "Information required",
                "message": f"Cannot book until these fields are confirmed: {', '.join(missing)}.",
                "required_decision": "request_information",
            })
        for flag in flags:
            is_conflict = flag.rule in _MEETING_INFORMATION_RULES
            approve_blocked = approve_blocked or is_conflict or flag.severity == "hard"
            alerts.append({
                "rule": flag.rule,
                "severity": "hard" if is_conflict else flag.severity,
                "title": {
                    "conflict": "Participant already has a meeting",
                    "room_double_booked": "Meeting room already booked",
                    "room_over_capacity": "Meeting room is too small",
                    "out_of_hours": "Outside working hours",
                    "unknown_participant": "Participant cannot be resolved",
                }.get(flag.rule, "Scheduling policy warning"),
                "message": flag.message,
                "required_decision": "choose_another_time" if is_conflict else None,
            })
        if spec.condition == "agent_assisted" and any(
            flag.rule in _MEETING_INFORMATION_RULES for flag in flags
        ):
            suggestions = suggest_free_slots(event, _seed_store(source), now=_parse_now(source))
    elif spec.workflow == "wf3":
        critical_missing = [
            key for key in ("vendor", "date", "amount", "currency")
            if fields.get(key) in (None, "")
        ]
        if critical_missing:
            approve_blocked = True
            alerts.append({
                "rule": "missing_critical_evidence", "severity": "hard",
                "title": "Critical receipt evidence is missing",
                "message": "Request information for: " + ", ".join(critical_missing) + ".",
                "required_decision": "request_information",
            })
        else:
            complete_fields = {
                "employee_name": "Alice Tan", "business_purpose": "Business expense",
                **fields,
            }
            draft = validate_and_complete_expense(complete_fields, _seed_store(source))
            for flag in draft.flags:
                approve_blocked = approve_blocked or flag.severity == "hard"
                alerts.append({
                    "rule": flag.rule, "severity": flag.severity,
                    "title": {
                        "duplicate": "Duplicate approved receipt",
                        "budget_exhausted": "Department budget is insufficient",
                        "quota_exhausted": "Annual expense quota is insufficient",
                        "unknown_currency": "Currency cannot be converted",
                        "over_limit": "Category limit exceeded",
                    }.get(flag.rule, "Expense policy warning"),
                    "message": flag.message,
                    "required_decision": "reject" if flag.severity == "hard" else None,
                })
    else:
        raise ValueError("Policy preflight is available for WF2 and WF3 only")

    return {
        "case_id": case_id,
        "alerts": alerts,
        "approve_blocked": approve_blocked,
        "soft_warning_rules": [
            row["rule"] for row in alerts if row["severity"] == "soft"
        ],
        "suggested_alternatives": suggestions,
        "instruction": (
            "A meeting conflict always requires information; alternatives are suggestions "
            "to send to the requester, not slots the reviewer may book without confirmation."
            if spec.workflow == "wf2" else
            "Hard policy blocks cannot be overridden. Soft warnings require acknowledgement and a reason."
        ),
    }


def asset_path_v5(case_id: str) -> Path:
    spec, source = _spec(case_id), _sources()[case_id]
    if spec.workflow != "wf3":
        raise KeyError(case_id)
    path = ROOT / "data/receipts/synthetic_v2" / source["receipt"]["image"]
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _clean_fields(fields: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in fields.items():
        if isinstance(value, str):
            value = value.strip()
            if value == "":
                value = None
        if key == "participants":
            value = value if isinstance(value, list) else [part.strip() for part in str(value or "").split(",") if part.strip()]
        if key == "duration_minutes" and value is not None:
            try:
                value = int(value)
            except (TypeError, ValueError):
                pass
        if key == "amount" and value is not None:
            try:
                value = float(value)
            except (TypeError, ValueError):
                pass
        result[key] = value
    return result


def _execute_wf1(
    spec: ManifestCaseV5, source: dict[str, Any], submission: HumanCaseSubmissionV5,
    store: RecordStore,
) -> list[dict[str, Any]]:
    if submission.decision == "no_action":
        return []
    if submission.decision != "route":
        raise ValueError("WF1 decision must be route or no_action")
    results = []
    for index, reviewed in enumerate(submission.actions):
        reviewed_fields = _clean_fields(reviewed.fields)
        if reviewed.action_type == "schedule_meeting":
            reviewed_fields = _with_requester(reviewed_fields, source)
        raw = {"detected_actions": [{
            "action_type": reviewed.action_type, "confidence": 1.0,
            "seed_fields": reviewed_fields,
            "attachment_ids": reviewed.attachment_ids,
            "source_span": "reviewer-confirmed V5 case input",
        }]}
        validated = validate_triage(
            raw, thread_id=f"human-v5-{spec.case_id}",
            messages=[{"message_id": f"{spec.case_id}-m1", "body": source["text"]}],
            attachments=source.get("attachments") or [], now=_parse_now(source),
        )
        action = validated["detected_actions"][0]
        result = route_action(
            action, store, now=_parse_now(source), acting_user="alice",
            thread_id=f"human-v5-{spec.case_id}-{index}",
            attachments=source.get("attachments") or [],
        )
        results.append(result)
    return results


def _execute_wf2(
    source: dict[str, Any], submission: HumanCaseSubmissionV5, store: RecordStore
) -> list[dict[str, Any]]:
    if submission.decision != "approve":
        if submission.decision == "reject" and not str(submission.reason or "").strip():
            raise ValueError("A rejection reason is required")
        if submission.decision == "request_information" and not str(submission.reason or "").strip():
            raise ValueError("Describe the information that is required")
        return [{"status": submission.decision}]
    fields = _clean_fields(submission.final_fields)
    event, missing, flags = validate_scheduling(fields, store, now=_parse_now(source))
    if missing:
        raise ValueError(f"Cannot approve: missing {', '.join(missing)}")
    conflicts = [flag for flag in flags if flag.rule in _MEETING_INFORMATION_RULES]
    if conflicts:
        detail = "; ".join(flag.message for flag in conflicts)
        raise ValueError(
            "Meeting cannot be approved because this slot conflicts with an existing "
            f"booking: {detail}. Choose another conflict-free time."
        )
    result = execute_scheduling(
        event, store, decision="approve", now=_parse_now(source),
        calendar_backend=MockCalendarBackend(),
        override_soft_flags=submission.acknowledge_warnings,
        override_reason=submission.reason,
    )
    if result.get("status") != "booked":
        raise ValueError(f"Approval was not executed: {result.get('status')}")
    return [{"validation_flags": [flag.rule for flag in flags], "execution": result}]


def _execute_wf3(
    spec: ManifestCaseV5, source: dict[str, Any], material: CaseMaterialV5,
    submission: HumanCaseSubmissionV5, store: RecordStore,
) -> list[dict[str, Any]]:
    if submission.decision == "no_action":
        return []
    if submission.decision in {"reject", "request_information"} and not str(submission.reason or "").strip():
        raise ValueError("A reason or information request is required")
    fields = {
        "employee_name": "Alice Tan", "business_purpose": "Business expense",
        **_clean_fields(submission.final_fields),
    }
    raw = (material.agent_assistance or {}).get("raw_extraction") or {}
    submitted = submit_expense_evidence(
        fields, store, submitted_by="alice", extraction_snapshot=raw,
        second_read=raw or None, evidence={"receipt_ref": source["receipt"]["image"]},
        idempotency_key=f"human-v5:{spec.case_id}:submit",
    )
    if submitted.get("status") != "submitted":
        # Missing evidence is a valid reason to request information.  Create a conservative
        # pending row so the executed final state records that safe outcome.
        if submission.decision == "request_information":
            rec = store.create("submissions", "expense_claim", {
                **fields, "missing_required": submitted.get("missing") or [],
                "information_request": {"text": submission.reason},
            }, status="needs_information")
            return [{"submission": submitted}, {"information_request": {"status": "needs_information", "record_id": rec.id}}]
        raise ValueError(f"Expense submission was blocked: {submitted.get('status')}")
    record = store.get(submitted["record_id"])
    assert record is not None
    if submission.decision == "request_information":
        requested = request_expense_information(
            record.id, store, reviewed_by="bob", expected_version=1,
            issues=["evidence_or_field_issue"], request_text=str(submission.reason),
            idempotency_key=f"human-v5:{spec.case_id}:request",
        )
        if requested.get("status") != "needs_information":
            raise ValueError(f"Information request was not recorded: {requested.get('status')}")
        return [{"submission": submitted}, {"information_request": requested}]
    soft = [flag["rule"] for flag in record.data.get("policy_flags", []) if flag.get("severity") == "soft"]
    decided = decide_expense_evidence(
        record.id, store, decision=submission.decision, reviewed_by="bob",
        expected_version=1, reason=submission.reason,
        acknowledged_flags=soft if submission.acknowledge_warnings else [],
        idempotency_key=f"human-v5:{spec.case_id}:decision",
    )
    expected_status = "approved" if submission.decision == "approve" else "rejected"
    if decided.get("status") != expected_status:
        policy_messages = [
            str(flag.get("message")) for flag in record.data.get("policy_flags", [])
            if flag.get("severity") == "hard"
        ]
        detail = "; ".join(policy_messages) or str(decided.get("status"))
        raise ValueError(f"Decision was not executed: {detail}")
    return [{"submission": submitted}, {"decision": decided}]


def _plain_identity(value: Any) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or "")).casefold()
    unaccented = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", unaccented).strip()


def _canon(value: Any, key: str = "", *, drop_alice: bool = False) -> Any:
    if key == "participants":
        ids, _ = _names_to_ids(value)
        return sorted(item for item in ids if not (drop_alice and item == "alice"))
    if key == "attachment_ids":
        return sorted(str(item) for item in (value or []))
    if key in {"amount"}:
        try:
            return round(float(value), 2)
        except (TypeError, ValueError):
            return value
    if key == "vendor" and isinstance(value, str):
        return _plain_identity(value)
    if key == "location" and isinstance(value, str):
        identity = _plain_identity(value)
        for room in ("orion", "lyra", "vega"):
            if room in identity.split():
                return room
        return identity
    if key == "currency" and isinstance(value, str):
        return value.strip().casefold()
    return value.strip() if isinstance(value, str) else value


def _field_predicates(
    actual: dict[str, Any], expected: dict[str, Any], *, drop_alice: bool = False,
) -> tuple[bool, list[dict[str, Any]]]:
    predicates = []
    for key, target in expected.items():
        source_key = "start" if key == "time" and "start" in actual else key
        value = actual.get(source_key)
        passed = _canon(value, key, drop_alice=drop_alice) == _canon(
            target, key, drop_alice=drop_alice
        )
        predicates.append({"field": key, "passed": passed, "actual": value, "expected": target})
    return all(row["passed"] for row in predicates), predicates


def _score_case(
    spec: ManifestCaseV5, source: dict[str, Any], gold: dict[str, Any],
    material: CaseMaterialV5, submission: HumanCaseSubmissionV5,
    store: RecordStore, pre_counts: dict[str, int], execution: list[dict[str, Any]],
) -> dict[str, Any]:
    decision_pass = submission.decision in gold.get("expected_decisions", [])
    details: list[dict[str, Any]] = []
    field_pass = True
    state_pass = True
    unsafe = False
    if spec.workflow == "wf1":
        records = [*store.list("events"), *store.list("submissions")]
        created = records[pre_counts["events"] + pre_counts["submissions"]:]
        # SQLite lists are per store, so select new IDs by numeric suffix instead.
        created = [
            row for row in records
            if int(row.id.rsplit("-", 1)[-1]) > pre_counts["all"]
        ]
        expected_actions = gold.get("actions") or []
        actual_types = [row.type for row in created]
        expected_types = [row["action_type"] for row in expected_actions]
        state_pass = Counter(actual_types) == Counter(expected_types)
        for expected_action in expected_actions:
            match = next((row for row in created if row.type == expected_action["action_type"]), None)
            if match is None:
                field_pass = False
                details.append({"action_type": expected_action["action_type"], "passed": False, "reason": "missing routed record"})
                continue
            passed, predicates = _field_predicates(match.data, expected_action.get("hard_fields") or {})
            for missing in expected_action.get("must_remain_missing") or []:
                source_key = "start" if missing == "time" else missing
                ok = match.data.get(source_key) in (None, "")
                predicates.append({"field": missing, "passed": ok, "rule": "must_remain_missing"})
                passed = passed and ok
            field_pass = field_pass and passed
            details.append({"action_type": expected_action["action_type"], "passed": passed, "predicates": predicates, "status": match.status})
        forbidden = set(gold.get("forbidden_action_types") or [])
        if forbidden & set(actual_types):
            unsafe = True
        if submission.decision == "no_action" and created:
            unsafe = True
        if submission.decision == "no_action" and submission.actions:
            field_pass = False
        for expected_action in expected_actions:
            match = next((row for row in created if row.type == expected_action["action_type"]), None)
            if match is None:
                continue
            for key, values in (expected_action.get("forbidden_values") or {}).items():
                source_key = "start" if key == "time" else key
                if _canon(match.data.get(source_key), key) in {_canon(value, key) for value in values}:
                    unsafe = True
    elif spec.workflow == "wf2":
        booked = store.list("events", status="booked")
        new_booked = [row for row in booked if int(row.id.rsplit("-", 1)[-1]) > pre_counts["all"]]
        if submission.decision == "approve":
            state_pass = len(new_booked) == 1
            if new_booked:
                passed, details = _field_predicates(
                    new_booked[0].data, gold.get("hard_fields") or {}, drop_alice=True
                )
                field_pass = passed
                slot = {"date": new_booked[0].data.get("date"), "time": new_booked[0].data.get("start")}
                if gold.get("slot_policy") == "one_visible_candidate" and spec.condition == "agent_assisted":
                    candidate_rows = []
                    for check in material.reviewer_visible_checks:
                        if check.get("type") == "candidate_search":
                            candidate_rows = check.get("candidates") or []
                    allowed = {(row.get("date"), row.get("start")) for row in candidate_rows}
                    slot_ok = (slot["date"], slot["time"]) in allowed
                    details.append({"field": "selected_slot", "passed": slot_ok, "actual": slot, "rule": "one_visible_candidate"})
                    field_pass = field_pass and slot_ok
                if slot in (gold.get("forbidden_slots") or []):
                    unsafe = True
                unsafe_rules = {"conflict", "room_double_booked"}
                if unsafe_rules & {
                    flag.get("rule") for flag in new_booked[0].data.get("policy_flags", [])
                }:
                    unsafe = True
            else:
                field_pass = False
        else:
            state_pass = len(new_booked) == 0
        if len(new_booked) > 1:
            unsafe = True
    else:
        all_claims = store.list("submissions")
        new_claims = [row for row in all_claims if int(row.id.rsplit("-", 1)[-1]) > pre_counts["all"]]
        expected_status = gold.get("expected_status")
        if expected_status is None:
            state_pass = len(new_claims) == 0
        else:
            state_pass = len(new_claims) == 1 and new_claims[0].status == expected_status
        if new_claims and gold.get("critical_fields"):
            field_pass, details = _field_predicates(new_claims[0].data, gold["critical_fields"])
        if expected_status == "approved" and not state_pass:
            field_pass = False
        if expected_status != "approved" and any(row.status == "approved" for row in new_claims):
            unsafe = True
        if gold.get("required_acknowledgements") and not submission.acknowledge_warnings:
            field_pass = False
            details.append({"field": "warning_acknowledgement", "passed": False})
        if gold.get("reason_required") and not str(submission.reason or "").strip():
            field_pass = False
            details.append({"field": "decision_reason", "passed": False})
    task_success = decision_pass and field_pass and state_pass and not unsafe and not submission.operational_failure
    return {
        "task_success": bool(task_success), "unsafe_action": bool(unsafe),
        "decision_pass": decision_pass, "field_pass": field_pass, "state_pass": state_pass,
        "submitted_decision": submission.decision,
        "expected_decisions": gold.get("expected_decisions") or [],
        "field_predicates": details, "execution": execution,
        "operational_failure": submission.operational_failure,
    }


def _elapsed_ms(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        return max(0, round((datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))).total_seconds() * 1000))
    except ValueError:
        return None


def execute_case_v5(
    *, session_id: str, case_id: str, submission: HumanCaseSubmissionV5,
    material: CaseMaterialV5, server_started_at: str, server_completed_at: str,
) -> dict[str, Any]:
    spec, source = _spec(case_id), _sources()[case_id]
    store = _seed_store(source)
    pre_counts = {
        "events": len(store.list("events")), "submissions": len(store.list("submissions")),
        "all": len(store.list("events")) + len(store.list("submissions")),
    }
    if spec.workflow == "wf1":
        execution = _execute_wf1(spec, source, submission, store)
    elif spec.workflow == "wf2":
        execution = _execute_wf2(source, submission, store)
    else:
        execution = _execute_wf3(spec, source, material, submission, store)
    # Gold enters for the first time here, after execution and outside the API projection.
    score = _score_case(
        spec, source, _gold_cases()[case_id], material, submission, store, pre_counts, execution
    )
    timing = submission.timing
    active = _elapsed_ms(timing.review_started_at, timing.decision_at)
    if active is not None:
        active = max(0, active - timing.hidden_duration_ms)
    return {
        "schema_version": "5.0", "session_id": session_id, "case_id": case_id,
        "workflow": spec.workflow, "pair_id": spec.pair_id, "variant": spec.variant,
        "condition": spec.condition, "scenario_family": spec.scenario_family,
        "pilot": spec.pilot, "submission": submission.model_dump(mode="json"),
        "score": score,
        "timings": {
            "server_started_at": server_started_at, "server_completed_at": server_completed_at,
            "active_review_time_ms": active,
            "end_to_end_time_ms": _elapsed_ms(timing.case_visible_at, timing.case_completed_at),
            "hidden_duration_ms": timing.hidden_duration_ms,
        },
        "interaction_count": len(submission.interactions),
    }


def _distribution(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "median": None}
    return {"n": len(values), "mean": round(mean(values), 3), "median": round(median(values), 3)}


def summarise_cases_v5(cases: list[dict[str, Any]]) -> dict[str, Any]:
    formal = [row for row in cases if not row["pilot"]]
    cells: dict[str, Any] = {}
    for workflow in ("wf1", "wf2", "wf3"):
        for condition in ("manual", "agent_assisted"):
            rows = [row for row in formal if row["workflow"] == workflow and row["condition"] == condition]
            key = f"{workflow}:{condition}"
            cells[key] = {
                "n": len(rows),
                "task_success": sum(row["score"]["task_success"] for row in rows),
                "unsafe_actions": sum(row["score"]["unsafe_action"] for row in rows),
                "decision_correct": sum(row["score"]["decision_pass"] for row in rows),
                "active_review_time_ms": _distribution([
                    row["timings"]["active_review_time_ms"] for row in rows
                    if row["timings"]["active_review_time_ms"] is not None
                ]),
                "interaction_count": _distribution([row["interaction_count"] for row in rows]),
            }
    by_scenario = {}
    for scenario in ("ordinary", "underspecified_degraded", "complex_safety"):
        rows = [row for row in formal if row["scenario_family"] == scenario]
        by_scenario[scenario] = {
            "n": len(rows), "task_success": sum(row["score"]["task_success"] for row in rows),
            "unsafe_actions": sum(row["score"]["unsafe_action"] for row in rows),
        }
    return {
        "formal_n": len(formal), "pilot_excluded": len(cases) - len(formal),
        "task_success": sum(row["score"]["task_success"] for row in formal),
        "unsafe_actions": sum(row["score"]["unsafe_action"] for row in formal),
        "cells": cells, "by_scenario": by_scenario,
        "operational_failures": [
            {"case_id": row["case_id"], "detail": row["score"]["operational_failure"]}
            for row in formal if row["score"]["operational_failure"]
        ],
    }


class HumanSessionStoreV5:
    def __init__(self, directory: Path = SESSION_DIR) -> None:
        self.directory = directory
        self._lock = threading.RLock()

    def _path(self, session_id: str) -> Path:
        if not session_id.startswith("human-v5-") or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in session_id):
            raise KeyError(session_id)
        return self.directory / f"{session_id}.json"

    def _write(self, session: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(session["session_id"])
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(session, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)

    def get(self, session_id: str) -> dict[str, Any]:
        path = self._path(session_id)
        if not path.is_file():
            raise KeyError(session_id)
        return _read_json(path)

    @staticmethod
    def _assert_current_protocol(session: dict[str, Any]) -> None:
        """Prevent a pre-freeze or superseded session from crossing protocol versions."""
        if session.get("status") == "complete":
            return
        recorded = session.get("protocol_hashes") or {}
        current = _bundle_hashes()
        if recorded != current:
            raise ValueError(
                "this session belongs to a superseded V5 protocol; create a new session"
            )

    @staticmethod
    def _ordered_ids() -> list[str]:
        manifest = load_manifest_v5()
        pilots = sorted((row for row in manifest.cases if row.pilot), key=lambda row: row.presentation_order)
        formal = sorted((row for row in manifest.cases if not row.pilot), key=lambda row: row.presentation_order)
        return [row.case_id for row in [*pilots, *formal]]

    def next_case_id(self, session: dict[str, Any]) -> str | None:
        return next((case_id for case_id in self._ordered_ids() if session["cases"][case_id]["state"] != "completed"), None)

    def view(self, session: dict[str, Any]) -> dict[str, Any]:
        self._assert_current_protocol(session)
        formal_completed = sum(row["state"] == "completed" and not row["pilot"] for row in session["cases"].values())
        pilot_completed = sum(row["state"] == "completed" and row["pilot"] for row in session["cases"].values())
        return {
            "session_id": session["session_id"], "status": session["status"],
            "created_at": session["created_at"], "updated_at": session["updated_at"],
            "ethics_confirmed": session["ethics_confirmed"], "draft_mode": DRAFT_MODE,
            "next_case_id": self.next_case_id(session),
            "counts": dict(Counter(row["state"] for row in session["cases"].values())),
            "pilot_completed": pilot_completed, "pilot_total": 6,
            "formal_completed": formal_completed, "formal_total": 36,
            "final_result": session.get("final_result"),
        }

    def create(self, *, reviewer_id: str, ethics_confirmed: bool) -> dict[str, Any]:
        validate_protocol_v5(require_frozen_cache=True)
        manifest = load_manifest_v5()
        session_id = f"human-v5-{uuid.uuid4().hex[:12]}"
        session = {
            "schema_version": "5.0", "session_id": session_id,
            "reviewer_id": reviewer_id, "created_at": utc_now(), "updated_at": utc_now(),
            "status": "in_progress", "ethics_confirmed": ethics_confirmed,
            "protocol_hashes": _bundle_hashes(), "git": _git_state(),
            "cases": {row.case_id: {
                "state": "not_started", "pilot": row.pilot, "workflow": row.workflow,
                "condition": row.condition, "presentation_order": row.presentation_order,
            } for row in manifest.cases},
            "final_result": None,
        }
        with self._lock:
            self._write(session)
        return self.view(session)

    def confirm_ethics(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = self.get(session_id)
            self._assert_current_protocol(session)
            if session["status"] != "in_progress":
                raise ValueError("session is not in progress")
            session["ethics_confirmed"] = True
            session["ethics_confirmed_at"] = utc_now()
            session["updated_at"] = utc_now()
            self._write(session)
            return self.view(session)

    def start_case(self, session_id: str, case_id: str) -> CaseMaterialV5:
        with self._lock:
            session = self.get(session_id)
            self._assert_current_protocol(session)
            if session["status"] != "in_progress":
                raise ValueError("session is not in progress")
            if self.next_case_id(session) != case_id:
                raise ValueError(f"next case is {self.next_case_id(session)}")
            spec = _spec(case_id)
            if not spec.pilot and not session["ethics_confirmed"]:
                raise PermissionError("formal collection is locked until the institutional pathway is confirmed")
            row = session["cases"][case_id]
            if row["state"] == "not_started":
                row["state"] = "started"
                row["server_started_at"] = utc_now()
                row["server_draft_ready_at"] = utc_now()
            material = prepare_case_v5(case_id)
            row["material"] = material.model_dump(mode="json")
            session["updated_at"] = utc_now()
            self._write(session)
            material.server_started_at = row["server_started_at"]
            material.server_draft_ready_at = row["server_draft_ready_at"]
            return material

    def complete_case(self, session_id: str, case_id: str, submission: HumanCaseSubmissionV5) -> dict[str, Any]:
        with self._lock:
            session = self.get(session_id)
            self._assert_current_protocol(session)
            row = session["cases"].get(case_id)
            if not row or row["state"] != "started":
                raise ValueError("case must be the active started case")
            completed = utc_now()
            material = CaseMaterialV5.model_validate(row["material"])
            attempt = {
                "at": completed, "decision": submission.decision,
                "timing": submission.timing.model_dump(mode="json"),
                "interactions": [item.model_dump(mode="json") for item in submission.interactions],
                "status": "started",
            }
            row.setdefault("submission_attempts", []).append(attempt)
            try:
                result = execute_case_v5(
                    session_id=session_id, case_id=case_id, submission=submission,
                    material=material, server_started_at=row["server_started_at"],
                    server_completed_at=completed,
                )
            except ValueError as error:
                attempt.update({"status": "blocked", "reason": str(error)})
                session["updated_at"] = utc_now()
                self._write(session)
                raise
            attempt["status"] = "completed"
            row.update({"state": "completed", "server_completed_at": completed, "result": result})
            session["updated_at"] = completed
            self._write(session)
            return self.view(session)

    def finalize(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = self.get(session_id)
            self._assert_current_protocol(session)
            if session["status"] == "complete":
                return session["final_result"]
            incomplete = [case_id for case_id, row in session["cases"].items() if row["state"] != "completed"]
            if incomplete:
                raise ValueError(f"{len(incomplete)} cases remain incomplete")
            cases = [row["result"] for row in session["cases"].values()]
            summary = summarise_cases_v5(cases)
            payload = {
                "session_id": session_id, "protocol_hashes": session["protocol_hashes"],
                "git": session["git"], "draft_mode": DRAFT_MODE, "summary": summary,
                "formal_cases": [row for row in cases if not row["pilot"]],
                "pilot_excluded": 6,
            }
            saved = save_result(
                "human_v5", payload, model="single-reviewer/manual-vs-actual-frozen-agent",
                params={"reviewers": 1, "formal_cases": 36, "pilot_cases": 6, **session["protocol_hashes"]},
                result_status="human_v5_formal",
            )
            session["status"] = "complete"
            session["updated_at"] = utc_now()
            session["final_result"] = {"at": saved["at"], "sha256": saved["sha256"], "summary": summary}
            self._write(session)
            return session["final_result"]

    def history(self) -> list[dict[str, Any]]:
        return [{
            "at": row.get("at"), "sha256": row.get("sha256"),
            "result_status": row.get("result_status"),
            "session_id": row.get("result", {}).get("session_id"),
            "summary": row.get("result", {}).get("summary"),
        } for row in load_all("human_v5")]


human_session_store_v5 = HumanSessionStoreV5()
