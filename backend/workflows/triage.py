"""WF1 triage / intake — deterministic core (docs/workflow_design.md).

The LLM reads a multi-party thread and proposes ``detected_actions``; this module
validates/normalises them and, on the human's Route, dispatches an action into its
downstream workflow as a draft (WF2 schedule / WF3 expense), passing the reviewed
reviewed fields and provenance straight through (the hand-off rule: no re-extraction).
WF1 never approves or executes the downstream action. Everything here is deterministic
CODE (docs/workflow_design.md).
"""
import re
from datetime import datetime
from typing import Any

from ..backends.records import RecordStore
from . import policy
from .scheduling import resolve_relative_date, validate_scheduling
from .thread_intake import (
    SUPPORTED_ACTIONS,
    ensure_actions,
    ensure_memos,
    normalise_seed,
)

ROUTABLE = SUPPORTED_ACTIONS


def validate_triage(extraction: dict, *, thread_id: str = "unbound",
                    messages: list[dict[str, Any]] | None = None,
                    attachments: list[dict[str, Any]] | None = None,
                    now: datetime | None = None) -> dict:
    """Normalise grounded workflow actions and memo proposals from the LLM.

    A 'none' entry is only meaningful as the *sole* result (FYI thread → the UI offers
    "archive, no action"); next to real actions it is model noise, so drop it there.
    """
    messages = messages or []
    attachments = attachments or []
    actions = []
    raw_actions = extraction.get("workflow_actions") or extraction.get("detected_actions") or []
    for a in raw_actions:
        if not isinstance(a, dict):
            continue
        atype = a.get("action_type")
        if atype not in ROUTABLE and atype != "none":
            continue
        seed = normalise_seed(
            str(atype), a.get("model_seed_fields") or a.get("seed_fields")
        )
        confidence = a.get("model_confidence", a.get("confidence", 0.0))
        actions.append({
            "action_type": atype,
            "operation": a.get("operation") or "create",
            "target_action_id": a.get("target_action_id") or a.get("target_action_ref"),
            "model_confidence": round(float(confidence or 0.0), 2),
            "model_seed_fields": dict(seed),
            "current_seed_fields": dict(seed),
            "source_span": a.get("source_span") or "",
            "source_evidence": a.get("source_evidence") or [],
            "field_sources": a.get("field_sources") or {},
            "attachment_ids": a.get("attachment_ids") or [],
            "rationale": a.get("rationale") or "",
            "status": "proposed",
        })
    routable = [a for a in actions if a["action_type"] in ROUTABLE]
    if routable:
        actions = routable
    actions = ensure_actions(actions, thread_id=thread_id, messages=messages,
                             attachments=attachments)

    memo_proposals = []
    for raw in extraction.get("memo_items") or []:
        if not isinstance(raw, dict) or not str(raw.get("text") or "").strip():
            continue
        date_phrase = raw.get("date_phrase")
        resolved_date = raw.get("resolved_date")
        if not resolved_date and date_phrase and now:
            resolved_date = resolve_relative_date(str(date_phrase), now)
        memo_proposals.append({
            "text": str(raw.get("text")).strip(),
            "model_text": str(raw.get("text")).strip(),
            "current_text": str(raw.get("text")).strip(),
            "item_type": raw.get("item_type") or "todo",
            "date_phrase": date_phrase,
            "resolved_date": resolved_date,
            "date_relation": raw.get("date_relation"),
            "model_confidence": round(float(
                raw.get("model_confidence", raw.get("confidence", 0.0)) or 0.0
            ), 2),
            "source_evidence": raw.get("source_evidence") or [],
        })
    memos = ensure_memos(memo_proposals, thread_id=thread_id, messages=messages)
    return {
        "summary": extraction.get("summary") or extraction.get("thread_summary") or "",
        "key_points": extraction.get("key_points") or [],
        "detected_actions": actions,
        "memo_items": memos,
    }


def _flags_json(flags: list[policy.Flag]) -> list[dict[str, str]]:
    return [{"rule": f.rule, "severity": f.severity, "message": f.message} for f in flags]


# ── Retraction check (WF1's deterministic consistency layer) ─────────────────────────
# A thread can specify a meeting in full and then call it off further down. The model
# anchors on the detailed plan and reports the action; booking a cancelled meeting is a
# real-world harm. This is the WF1 analogue of WF3's arithmetic self-consistency: the LLM
# reads the fields correctly, deterministic CODE checks them against what the thread says
# LATER. Soft only — the human decides (docs/workflow_design.md).
#
# Cues are split by strength to keep false positives down: a STRONG cue is unambiguous on
# its own; a WEAK cue only counts with a meeting noun in the same line. "Change of plan" and
# "moved" are deliberately excluded — they usually signal a RESCHEDULE, not a cancellation.
_STRONG_RETRACTION = re.compile(
    r"\bcancel(?:led|s|ling)?\b"
    r"|\bscrap (?:that|it|the)\b"
    r"|\bcall(?:ed|ing)?\s+(?:\w+\s+){0,2}off\b"
    r"|\b(?:meeting|call|sync|session|catch[- ]?up)\s+is\s+off\b"
    r"|\bnot going ahead\b",
    re.IGNORECASE)
_WEAK_RETRACTION = re.compile(
    r"\bno need\b|\bnever mind\b|\bignore the above\b"
    r"|\blet'?s (?:not|skip)\b|\bskip (?:it|that|the)\b|\bdon'?t need\b",
    re.IGNORECASE)
_MEETING_NOUN = re.compile(
    r"\b(?:meeting|meet|call|sync|session|catch[- ]?up|standup|review)\b", re.IGNORECASE)


def has_retraction_cue(line: str) -> bool:
    """True if this single line calls a plan off (strong cue, or weak cue + meeting noun)."""
    if _STRONG_RETRACTION.search(line):
        return True
    return bool(_WEAK_RETRACTION.search(line) and _MEETING_NOUN.search(line))


def check_retraction(raw_text: str, actions: list[dict]) -> list[dict[str, Any]]:
    """Soft-flag any routable action that the thread later calls off.

    Scans only the lines AFTER the action's first evidence span — a cancellation that precedes
    the request is not a retraction of it. When the span cannot be located (the model
    paraphrased it), the whole thread is scanned: missing the span must not silently
    disable the check.
    """
    lines = [ln for ln in (raw_text or "").splitlines() if ln.strip()]
    flags: list[dict[str, Any]] = []
    for i, action in enumerate(actions):
        if action.get("action_type") != "schedule_meeting":
            continue
        evidence = action.get("source_evidence") or []
        span = str(evidence[0].get("span") or "").strip().lower() if evidence else ""
        start = 0
        if span:
            for j, ln in enumerate(lines):
                if span in ln.lower():
                    start = j + 1
                    break
        hit = next((ln for ln in lines[start:] if has_retraction_cue(ln)), None)
        if hit:
            flags.append({
                "rule": "possible_retraction", "severity": "soft", "action_index": i,
                "message": f"a later line appears to call this off: {hit.strip()[:120]!r}",
            })
    return flags


def _existing_route(store: RecordStore, key: str) -> tuple[str, Any] | None:
    for store_name in ("events", "submissions"):
        for record in store.list(store_name):
            if record.data.get("idempotency_key") == key:
                return store_name, record
    return None


def route_action(action: dict, store: RecordStore, *, now: datetime,
                 acting_user: str, thread_id: str,
                 attachments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Create a downstream draft from a human-routed action; never execute it in WF1."""
    atype = action.get("action_type")
    operation = action.get("operation", "create")
    seed = dict(action.get("current_seed_fields") or {})
    idempotency_key = (
        f"wf1:{thread_id}:{action.get('action_id')}:{action.get('version')}:{atype}"
    )
    existing = _existing_route(store, idempotency_key)
    if existing:
        store_name, record = existing
        return {
            "routed": "calendar" if store_name == "events" else "expenses",
            "status": record.status,
            "record_id": record.id,
            "missing": record.data.get("missing_required") or [],
            "idempotent_replay": True,
        }

    origin = {
        "workflow": "wf1",
        "thread_id": thread_id,
        "action_id": action.get("action_id"),
        "action_version": action.get("version"),
        "source_message_ids": [
            evidence["message_id"]
            for evidence in action.get("source_evidence", [])
            if isinstance(evidence, dict) and evidence.get("message_id")
        ],
        "source_path": f"/inbox?thread={thread_id}&action={action.get('action_id')}",
    }
    shared = {
        "origin": origin,
        "operation": operation,
        "target_action_id": action.get("target_action_id"),
        "target_record_id": action.get("target_record_id"),
        "idempotency_key": idempotency_key,
        "attachment_ids": list(action.get("attachment_ids") or []),
        "source_evidence": list(action.get("source_evidence") or []),
        "field_sources": dict(action.get("field_sources") or {}),
        "routed_by": acting_user,
    }

    if operation == "cancel":
        target_store = "events" if atype == "schedule_meeting" else "submissions"
        record_type = "schedule_meeting" if atype == "schedule_meeting" else "expense_claim"
        rec = store.create(target_store, record_type, {
            **shared, "current_seed_fields": seed,
            "missing_required": [] if action.get("target_record_id") else ["target_record_id"],
        }, status="pending_review")
        return {"routed": "calendar" if target_store == "events" else "expenses",
                "status": "pending_review", "record_id": rec.id,
                "missing": rec.data["missing_required"]}

    if atype == "schedule_meeting":
        seed["organizer"] = acting_user
        event, missing, flags = validate_scheduling(seed, store, now=now)
        status = "needs_input" if missing else "pending_review"
        event.update({
            **shared,
            "missing_required": missing,
            "policy_flags": _flags_json(flags),
        })
        rec = store.create("events", "schedule_meeting", event, status=status)
        return {"routed": "calendar", "status": status, "record_id": rec.id,
                "missing": missing, "flags": event["policy_flags"]}

    if atype == "expense_claim":
        if seed.get("date"):
            seed["date"] = resolve_relative_date(str(seed["date"]), now) or seed["date"]
        attachment_map = {item.get("attachment_id"): item for item in attachments or []}
        evidence = [attachment_map[item] for item in action.get("attachment_ids") or []
                    if item in attachment_map]
        declaration = bool(seed.get("missing_receipt_declaration"))
        if declaration:
            status = "pending_exception_review"
        elif evidence:
            status = "pending_extraction"
        else:
            status = "needs_evidence"
        missing = list(action.get("missing_fields") or [])
        if not evidence and not declaration:
            missing = [*missing, "receipt_or_alternative_evidence"]
        rec = store.create("submissions", "expense_claim", {
            **seed,
            **shared,
            "evidence_refs": evidence,
            "extraction_snapshot": None,
            "submitted_snapshot": None,
            "submitted_by": acting_user,
            "missing_required": list(dict.fromkeys(missing)),
            "policy_flags": [],
        }, status=status)
        return {"routed": "expenses", "status": status, "record_id": rec.id,
                "missing": rec.data["missing_required"]}

    return {"routed": "none", "status": "not_routable"}
