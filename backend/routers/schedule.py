"""WF2 scheduling API — direct-entry request → LLM extract → validate → gate → book.

Shares the seeded RecordStore, and runs on the REAL clock (see :func:`_now`) so past dates
are actually past. The flagship Bob-conflict demo still works because the calendar is seeded
relative to today (``fixtures.org.busy_slots_for``), not pinned to a fixed date.
"""
import asyncio
from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agent.extract import llm_extract
from ..workflows import policy
from ..workflows.scheduling import execute_scheduling, suggest_free_slots, validate_scheduling
from ..workflows.scheduling_lifecycle import (
    analytics_rows,
    apply_context,
    build_context,
    lifecycle_mutation,
    list_contexts,
    next_occurrence_window,
    normalise_spec,
    recommend_candidates,
    save_context,
)
from ._store import store

router = APIRouter(prefix="/api/schedule")

def _now() -> datetime:
    """The real current time, read per request.

    WF2 used to pin this to a fixed demo date so "next Tuesday" landed on the seeded clash.
    That made every real-world date judgement meaningless: a meeting last week looked future,
    so the ``past_date`` check could never fire for the user. The clash is preserved instead
    by seeding the demo calendar RELATIVE to today (``fixtures.org.busy_slots_for``).

    Read per request, never cached at import — the server runs for days, and a frozen "now"
    would drift a little further from reality every hour it stays up.

    Evaluation is untouched: the harness scores ``validate_scheduling`` against its own fixed
    ``GEN_NOW`` (evals/scheduling_data.py) and never calls this router.
    """
    return datetime.now()


def _flags_json(flags: list[policy.Flag]) -> list[dict[str, str]]:
    return [{"rule": f.rule, "severity": f.severity, "message": f.message} for f in flags]


class RunRequest(BaseModel):
    input_text: str
    organizer: Optional[str] = None      # the acting user → shows on their own calendar
    # Optional structured hints from the guided-entry pickers. The LLM still extracts
    # everything from the text (title / people / location); a hint, when the user set one,
    # simply overrides that one field — a picked ISO date resolves as "explicit", so it
    # side-steps the relative-date ambiguity by construction (the user was explicit).
    date_hint: Optional[str] = None      # YYYY-MM-DD
    time_hint: Optional[str] = None      # HH:MM


@router.post("/run")
async def run(req: RunRequest) -> dict[str, Any]:
    extraction = await asyncio.to_thread(llm_extract, "scheduling", req.input_text)
    if req.organizer:
        extraction["organizer"] = req.organizer
    if req.date_hint:
        extraction["date"] = req.date_hint
    if req.time_hint:
        extraction["time"] = req.time_hint
    event, missing, flags = validate_scheduling(extraction, store, now=_now())
    # When the code found a clash it also computes the way out — the human picks a slot
    # rather than hunting for one. Only offered when there is something to resolve.
    alternatives = (suggest_free_slots(event, store, now=_now())
                    if any(f.rule in ("conflict", "room_double_booked") for f in flags) else [])
    return {"extraction": extraction, "event": event, "missing": missing,
            "flags": _flags_json(flags), "alternatives": alternatives}


class DecideRequest(BaseModel):
    event: dict[str, Any]
    decision: Literal["approve", "reject"]
    reason: Optional[str] = None
    changed_fields: Optional[list[str]] = None
    override_soft_flags: bool = False
    override_reason: Optional[str] = None


@router.post("/decide")
async def decide(req: DecideRequest) -> dict[str, Any]:
    return execute_scheduling(req.event, store, decision=req.decision,
                              reason=req.reason, changed_fields=req.changed_fields, now=_now(),
                              override_soft_flags=req.override_soft_flags,
                              override_reason=req.override_reason)


@router.get("/calendar")
async def calendar(actor: Optional[str] = None) -> dict[str, Any]:
    """Booked meetings. If ``actor`` is given, show only that person's calendar (meetings
    they organise or attend) — so switching who you act as shows their meetings."""
    events = []
    for r in store.list("events", status="booked"):
        d = r.data
        parts = d.get("participants", [])
        if actor and actor not in parts and d.get("organizer") != actor:
            continue
        who = [p.get("name") for p in d.get("participant_details", [])] or parts
        events.append({"id": r.id, "title": d.get("title"), "date": d.get("date"),
                       "start": d.get("start"), "end": d.get("end"),
                       "duration_minutes": d.get("duration_minutes"),
                       "participants": who, "location": d.get("location"),
                       # On a *booked* event these flags were live at the moment of booking,
                       # so the human saw them and went ahead — that is an override, and
                       # together with changed_fields it is the RQ3 record of what the human
                       # did with a warning: override it, edit around it, or reject.
                       "overridden_flags": d.get("overridden_flags", []),
                       "changed_fields": d.get("changed_fields", [])})
    events.sort(key=lambda e: (e["date"] or "", e["start"] or ""))
    return {"events": events}


@router.get("/drafts")
async def routed_drafts() -> dict[str, Any]:
    """WF1 meeting hand-offs awaiting WF2 review; never booked by this read."""
    statuses = {"needs_input", "pending_review"}
    return {"items": [
        {"id": record.id, "status": record.status, **record.data}
        for record in store.list("events", record_type="schedule_meeting")
        if record.status in statuses
    ]}

class RoutedDraftDecisionRequest(BaseModel):
    event: dict[str, Any]
    decision: Literal["approve", "reject"]
    reason: Optional[str] = None
    changed_fields: Optional[list[str]] = None
    reviewed_by: Optional[str] = None
    override_soft_flags: bool = False
    override_reason: Optional[str] = None


def _get_routed_meeting_draft(draft_id: str):
    record = store.get(draft_id)

    if (
        record is None
        or record.store != "events"
        or record.type != "schedule_meeting"
    ):
        raise HTTPException(status_code=404, detail="Routed meeting draft not found")

    return record


def _draft_extraction(data: dict[str, Any]) -> dict[str, Any]:
    """Convert the stored WF1 hand-off into the input expected by WF2 validation."""

    participant_names = data.get("participant_names")

    if not participant_names:
        participant_names = [
            item.get("name")
            for item in data.get("participant_details", [])
            if isinstance(item, dict) and item.get("name")
        ]

    return {
        **data,
        "participants": participant_names or [],
        "time": data.get("time") or data.get("start"),
    }


@router.get("/drafts/{draft_id}")
async def routed_draft_detail(draft_id: str) -> dict[str, Any]:
    """Load one WF1 meeting hand-off into the normal WF2 review flow."""

    record = _get_routed_meeting_draft(draft_id)

    if record.status not in {"needs_input", "pending_review"}:
        raise HTTPException(
            status_code=409,
            detail=f"Draft can no longer be reviewed: {record.status}",
        )

    extraction = _draft_extraction(record.data)
    event, missing, flags = validate_scheduling(
        extraction,
        store,
        now=_now(),
    )

    alternatives = (
        suggest_free_slots(event, store, now=_now())
        if any(
            flag.rule in {"conflict", "room_double_booked"}
            for flag in flags
        )
        else []
    )

    return {
        "draft_id": record.id,
        "draft_status": record.status,
        "source_path": (record.data.get("origin") or {}).get("source_path"),
        "extraction": extraction,
        "event": event,
        "missing": missing,
        "flags": _flags_json(flags),
        "alternatives": alternatives,
    }


@router.post("/drafts/{draft_id}/decide")
async def decide_routed_draft(
    draft_id: str,
    req: RoutedDraftDecisionRequest,
) -> dict[str, Any]:
    """Approve or reject a routed WF1 draft after WF2 review."""

    record = _get_routed_meeting_draft(draft_id)

    if record.status not in {"needs_input", "pending_review"}:
        raise HTTPException(
            status_code=409,
            detail=f"Draft has already been decided: {record.status}",
        )

    if req.decision not in {"approve", "reject"}:
        raise HTTPException(
            status_code=422,
            detail="decision must be approve or reject",
        )

    result = execute_scheduling(
        req.event,
        store,
        decision=req.decision,
        reason=req.reason,
        changed_fields=req.changed_fields,
        now=_now(),
        override_soft_flags=req.override_soft_flags,
        override_reason=req.override_reason,
    )

    new_data = {
        **record.data,
        "reviewed_by": req.reviewed_by,
        "review_reason": req.reason,
        "changed_fields": req.changed_fields or [],
        "decision_result": result,
    }

    if result.get("status") == "booked":
        new_data["downstream_record_id"] = result.get("record_id")
        store.update(
            draft_id,
            data=new_data,
            status="booked",
        )

    elif result.get("status") == "rejected":
        store.update(
            draft_id,
            data=new_data,
            status="rejected",
        )

    # Missing fields and unconfirmed warnings both keep the draft reviewable.
    elif result.get("status") == "blocked_missing_required":
        new_data["missing_required"] = result.get("missing") or []
        store.update(
            draft_id,
            data=new_data,
            status="needs_input",
        )

    elif result.get("status") in {
        "requires_override_confirmation",
        "override_reason_required",
    }:
        new_data["live_review_flags"] = result.get("flags") or []
        store.update(draft_id, data=new_data, status="pending_review")

    return {
        **result,
        "draft_id": draft_id,
        "draft_status": (
            "booked"
            if result.get("status") == "booked"
            else "rejected"
            if result.get("status") == "rejected"
            else "pending_review"
            if result.get("status") in {
                "requires_override_confirmation",
                "override_reason_required",
            }
            else "needs_input"
        ),
    }

class SmartCandidateRequest(BaseModel):
    spec: dict[str, Any]
    actor: str = "alice"


class SmartExecuteRequest(BaseModel):
    spec: dict[str, Any]
    candidate: dict[str, Any] | None = None
    actor: str = "alice"
    idempotency_key: str
    validation_token: str | None = None
    calendar_version: str | None = None
    reason: str | None = None


@router.post("/smart/candidates")
async def smart_candidates(req: SmartCandidateRequest) -> dict[str, Any]:
    spec = normalise_spec(req.spec, now=_now())
    if spec.get("target_event_id"):
        target = store.get(str(spec["target_event_id"]))
        if target:
            spec["original_event"] = target.data
    result = recommend_candidates(spec, store, now=_now(), actor=req.actor)
    return {"spec": spec, **result}


@router.post("/smart/execute")
async def smart_execute(req: SmartExecuteRequest) -> dict[str, Any]:
    spec = normalise_spec(req.spec, now=_now())
    if spec.get("target_event_id"):
        target = store.get(str(spec["target_event_id"]))
        if target:
            spec["original_event"] = target.data
    result = lifecycle_mutation(
        spec=spec,
        candidate=req.candidate,
        store=store,
        actor=req.actor,
        idempotency_key=req.idempotency_key,
        validation_token=req.validation_token,
        calendar_version=req.calendar_version,
        now=_now(),
        reason=req.reason,
    )
    # Smart Schedule is an interactive, human-approved booking path too.  Keep the
    # deterministic lifecycle core external-I/O-free (evaluation calls it directly), then
    # add the opt-in Google feasibility write only at this API boundary. Provider identity
    # stored by CREATE makes later UPDATE/RESCHEDULE/CANCEL target the same remote event.
    if result.get("status") in {"booked", "update", "reschedule", "cancelled"}:
        record = store.get(str(result.get("record_id") or ""))
        event = result.get("event") or (record.data if record else None)
        if event is None:
            return result
        try:
            from ..backends.calendar_backend import get_calendar_backend
            backend = get_calendar_backend()
            if result["status"] == "booked":
                sync = backend.book(event, event.get("participants", []))
            elif result["status"] in {"update", "reschedule"}:
                sync = backend.update(event, event.get("participants", []))
            else:
                sync = backend.cancel(event, event.get("participants", []))
            result["calendar_backend"] = sync
            if record is not None:
                # Keep the last known remote IDs on provider failure. They are required to
                # retry the same update/cancel; overwriting them with an error-only payload
                # would orphan the Google event permanently.
                sync_state = (
                    sync
                    if sync.get("status") != "error"
                    else {
                        **(record.data.get("calendar_sync") or {}),
                        "status": "error",
                        "error": sync.get("error"),
                    }
                )
                updated_event = {**record.data, "calendar_sync": sync_state}
                store.update(record.id, data=updated_event)
                if result.get("event") is not None:
                    result["event"] = updated_event
        except Exception as exc:  # noqa: BLE001 — local approval must survive provider faults
            result["calendar_backend"] = {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }
    return result


@router.get("/events/{event_id}")
async def event_detail(event_id: str) -> dict[str, Any]:
    record = store.get(event_id)
    if record is None or record.store != "events":
        return {"error": "event not found"}
    return {
        "id": record.id,
        "status": record.status,
        "event": record.data,
        "context": build_context(record.id, store),
    }


@router.post("/events/{event_id}/reuse")
async def reuse_event(event_id: str) -> dict[str, Any]:
    context = build_context(event_id, store)
    if context is None:
        return {"error": "event not found"}
    return {
        "spec": {
            "operation": "REUSE",
            "context_id": context["context_id"],
            "title": context["title"],
            "participants": context["participants"],
            "duration_minutes": context["duration_minutes"],
            "location": context["location"],
            "mode": context["mode"],
            "agenda": context["agenda"],
            "provenance": context["provenance"],
        }
    }

class ContextRequest(BaseModel):
    context: dict[str, Any]
    actor: str = "alice"


@router.get("/contexts")
async def contexts() -> dict[str, Any]:
    return {"contexts": list_contexts(store)}


@router.post("/contexts")
async def create_context(req: ContextRequest) -> dict[str, Any]:
    return {"context": save_context(req.context, store, actor=req.actor)}


@router.get("/analytics")
async def analytics() -> dict[str, Any]:
    return {"events": analytics_rows(store)}


@router.post("/events/{event_id}/next")
async def next_occurrence(event_id: str) -> dict[str, Any]:
    context = build_context(event_id, store)
    if context is None:
        return {"error": "event not found"}
    source = store.get(event_id)
    recurrence = (source.data.get("recurrence") if source else None) or context.get("recurrence")
    window = next_occurrence_window(recurrence, after=(source.data.get("date") if source else ""))
    if window is None:
        return {"error": "no fixed recurrence is configured"}
    spec = normalise_spec({
        "operation": "REUSE",
        **context,
        "date_window": window,
        "provenance": {"recurrence": "confirmed_context"},
    }, now=_now())
    return {"spec": apply_context(spec, context), "window": window}
