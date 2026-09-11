"""WF1 inbox API — list threads, triage (LLM), route/dismiss detected actions, archive.

Shares the seeded store. A fixed demo ``NOW`` so routed "next Tuesday" meetings resolve to
2026-07-07 and line up with the seeded calendar (as in the schedule router).
"""
import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..agent.extract import llm_extract
from ..backends.records import Record
from ..workflows.triage import check_retraction, route_action, validate_triage
from ..workflows.thread_intake import (
    ACTION_FIELDS,
    REVIEWABLE_ACTION_STATUSES,
    audit_event,
    ensure_memos,
    ensure_thread_data,
    normalise_seed,
    reconcile_actions,
    reconcile_memos,
    thread_status,
    triage_text,
    untriaged_messages,
    utc_now,
)
from ._store import store

router = APIRouter(prefix="/api/inbox")
NOW = datetime(2026, 6, 30, 9, 0)


def thread_now(rec: Record) -> datetime:
    """The basis for resolving relative dates in this thread.

    "next Tuesday" means next Tuesday *from when the message was written*, not from when
    the coordinator happens to read it — so resolve against the thread's ``received_at``.
    Falls back to the demo ``NOW`` for threads without one.
    """
    ts = rec.data.get("received_at")
    if ts:
        try:
            return datetime.fromisoformat(str(ts))
        except ValueError:
            pass
    return NOW


def _persist(rec: Record, data: dict[str, Any]) -> Record:
    """Persist a fully normalised thread and derive its workflow status."""
    return store.update(rec.id, data=data, status=thread_status(data["detected_actions"]))


def _thread_data(rec: Record) -> dict[str, Any]:
    return ensure_thread_data(rec.data, thread_id=rec.id)


def _requested_action(rec: Record, action_id: str) -> tuple[dict[str, Any], dict]:
    data = _thread_data(rec)
    actions = data["detected_actions"]
    action = next((item for item in actions if item["action_id"] == action_id), None)
    if action is None:
        raise HTTPException(status_code=404, detail="action not found")
    return data, action


def _check_expected_version(action: dict, expected_version: int) -> None:
    if action["version"] != expected_version:
        raise HTTPException(
            status_code=409,
            detail=(
                f"stale_version: action {action['action_id']} is version "
                f"{action['version']}, expected {expected_version}"
            ),
        )


@router.get("/threads")
async def threads() -> dict[str, Any]:
    items = []
    for record in store.list("threads"):
        data = _thread_data(record)
        for action in data["detected_actions"]:
            downstream = store.get(str(action.get("routed_to") or ""))
            action["downstream_status"] = downstream.status if downstream else None
            action["downstream_type"] = downstream.type if downstream else None

        items.append({
            "id": record.id,
            "status": "archived" if record.status == "archived"
            else thread_status(data["detected_actions"]),
            "subject": data.get("subject"),
            "source": data.get("source"),
            "raw_text": data.get("raw_text"),
            "received_at": data.get("received_at"),
            "summary": data.get("summary"),
            "key_points": data.get("key_points", []),
            "messages": data["messages"],
            "attachments": data["attachments"],
            "detected_actions": data["detected_actions"],
            "memo_items": data["memo_items"],
            "audit_events": data["audit_events"],
            "last_triaged_message_id": data.get("last_triaged_message_id"),
            "has_untriaged_messages": bool(untriaged_messages(data)),
        })
    return {"threads": items}


class ThreadRef(BaseModel):
    thread_id: str
    acting_user: str = "alice"


@router.post("/triage")
async def triage(req: ThreadRef) -> dict[str, Any]:
    rec = store.get(req.thread_id)
    if rec is None:
        return {"error": "thread not found"}
    data = _thread_data(rec)
    delta = untriaged_messages(data)
    if not delta:
        return {
            "status": "no_new_messages",
            "summary": data.get("summary"),
            "detected_actions": data["detected_actions"],
            "memo_items": data["memo_items"],
        }
    input_text = triage_text(data)
    extraction = await asyncio.to_thread(
        lambda: llm_extract("triage", input_text, source=data.get("source")))
    result = validate_triage(
        extraction, thread_id=req.thread_id, messages=data["messages"],
        attachments=data["attachments"], now=thread_now(rec))
    delta_text = "\n".join(message["body"] for message in delta)
    for flag in check_retraction(delta_text, result["detected_actions"]):
        result["detected_actions"][flag["action_index"]].setdefault("flags", []).append(
            {k: v for k, v in flag.items() if k != "action_index"})
    at = utc_now()
    data["detected_actions"] = reconcile_actions(
        data["detected_actions"], result["detected_actions"],
        thread_id=req.thread_id, at=at)
    data["memo_items"] = reconcile_memos(
        data["memo_items"], result["memo_items"], thread_id=req.thread_id, at=at)
    data["summary"] = result["summary"] or data.get("summary") or ""
    data["key_points"] = result["key_points"] or data.get("key_points") or []
    data["last_triaged_message_id"] = data["messages"][-1]["message_id"]
    data["analysis_runs"].append({
        "at": at,
        "message_ids": [message["message_id"] for message in delta],
        "proposed_action_count": len(result["detected_actions"]),
        "proposed_memo_count": len(result["memo_items"]),
    })
    audit_event(data, thread_id=req.thread_id, actor="agent", action="triage",
                reason_code="new_messages_analysed", at=at,
                message_ids=[message["message_id"] for message in delta])
    _persist(rec, data)
    return {
        "summary": data["summary"], "key_points": data["key_points"],
        "detected_actions": data["detected_actions"], "memo_items": data["memo_items"],
    }


class ActionRef(BaseModel):
    thread_id: str
    action_id: str
    expected_version: int = Field(ge=1)
    acting_user: str = "alice"


@router.post("/route")
async def route(req: ActionRef) -> dict[str, Any]:
    rec = store.get(req.thread_id)
    if rec is None:
        return {"error": "thread not found"}
    data, action = _requested_action(rec, req.action_id)
    if action.get("status") not in REVIEWABLE_ACTION_STATUSES:
        return {
            "status": "already_handled", "action_status": action.get("status"),
            "action_id": action["action_id"], "version": action["version"],
            "record_id": action.get("routed_to"),
        }
    _check_expected_version(action, req.expected_version)
    routed_version = action["version"]
    res = route_action(action, store, now=thread_now(rec),
                       acting_user=req.acting_user, thread_id=req.thread_id,
                       attachments=data["attachments"])
    if res.get("record_id"):
        action["status"] = "routed"
        action["routed_to"] = res.get("record_id")
        action["version"] += 1
        action["updated_at"] = utc_now()
        audit_event(data, thread_id=req.thread_id, actor=req.acting_user,
                    action="route_action", reason_code="human_route",
                    record_version=action["version"], action_id=action["action_id"],
                    action_version=routed_version, downstream_record_id=res["record_id"])
    _persist(rec, data)
    return {**res, "action_id": action["action_id"],
            "version": action["version"]}


@router.post("/dismiss")
async def dismiss(req: ActionRef) -> dict[str, Any]:
    rec = store.get(req.thread_id)
    if rec is None:
        return {"error": "thread not found"}
    data, action = _requested_action(rec, req.action_id)
    if action.get("status") not in REVIEWABLE_ACTION_STATUSES:
        return {
            "status": "already_handled", "action_status": action.get("status"),
            "action_id": action["action_id"], "version": action["version"],
            "record_id": action.get("routed_to"),
        }
    _check_expected_version(action, req.expected_version)
    action["status"] = "dismissed"
    action["version"] += 1
    action["updated_at"] = utc_now()
    audit_event(data, thread_id=req.thread_id, actor=req.acting_user,
                action="dismiss_action", reason_code="human_dismiss",
                record_version=action["version"], action_id=action["action_id"])
    _persist(rec, data)
    return {"status": "dismissed", "action_id": action["action_id"],
            "version": action["version"]}


@router.post("/archive")
async def archive(req: ThreadRef) -> dict[str, Any]:
    rec = store.get(req.thread_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="thread not found")
    data = _thread_data(rec)
    if any(action.get("status") in REVIEWABLE_ACTION_STATUSES
           and action.get("action_type") in ACTION_FIELDS
           for action in data["detected_actions"]):
        raise HTTPException(status_code=409, detail="pending_actions_must_be_resolved")
    audit_event(data, thread_id=req.thread_id, actor=req.acting_user, action="archive_thread",
                reason_code="human_archive")
    store.update(req.thread_id, data=data, status="archived")
    return {"status": "archived"}


class MessageCreate(BaseModel):
    sender: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1)
    sent_at: str | None = None
    attachment_ids: list[str] = Field(default_factory=list)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    acting_user: str = "alice"


@router.post("/threads/{thread_id}/messages")
async def add_message(thread_id: str, req: MessageCreate) -> dict[str, Any]:
    rec = store.get(thread_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="thread not found")
    data = _thread_data(rec)
    data["attachments"].extend(req.attachments)
    message_id = f"msg-{thread_id}-{len(data['messages']) + 1:03d}"
    message = {
        "message_id": message_id,
        "sender": req.sender.strip(),
        "sent_at": req.sent_at or utc_now(),
        "body": req.body.strip(),
        "attachment_ids": list(dict.fromkeys(req.attachment_ids)),
    }
    data["messages"].append(message)
    data["raw_text"] = "\n".join(
        f"{item['sender']}: {item['body']}" for item in data["messages"])
    data = ensure_thread_data(data, thread_id=thread_id)
    audit_event(data, thread_id=thread_id, actor=req.acting_user,
                action="append_message", reason_code="new_thread_message",
                message_id=message_id)
    _persist(rec, data)
    return {"status": "added", "message": data["messages"][-1],
            "has_untriaged_messages": True}


class ActionPatch(BaseModel):
    expected_version: int = Field(ge=1)
    fields: dict[str, Any] | None = None
    operation: str | None = None
    target_action_id: str | None = None
    source_evidence: list[dict[str, Any]] | None = None
    field_sources: dict[str, dict[str, Any]] | None = None
    attachment_ids: list[str] | None = None
    acting_user: str = "alice"
    reason: str | None = None


@router.patch("/threads/{thread_id}/actions/{action_id}")
async def edit_action(thread_id: str, action_id: str, req: ActionPatch) -> dict[str, Any]:
    rec = store.get(thread_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="thread not found")
    data, action = _requested_action(rec, action_id)
    if action.get("status") not in REVIEWABLE_ACTION_STATUSES:
        raise HTTPException(status_code=409, detail="action_is_already_handled")
    _check_expected_version(action, req.expected_version)
    action_type = str(action.get("action_type"))
    before = {
        "version": action["version"],
        "operation": action.get("operation"),
        "current_seed_fields": dict(action.get("current_seed_fields") or {}),
        "source_evidence": list(action.get("source_evidence") or []),
        "field_sources": dict(action.get("field_sources") or {}),
        "attachment_ids": list(action.get("attachment_ids") or []),
    }
    if req.fields is not None:
        unknown = set(req.fields) - ACTION_FIELDS.get(action_type, set())
        if unknown:
            raise HTTPException(status_code=422,
                                detail=f"unsupported_fields: {', '.join(sorted(unknown))}")
        merged = dict(action.get("current_seed_fields") or {})
        merged.update(req.fields)
        action["current_seed_fields"] = normalise_seed(action_type, merged)
    if req.operation is not None:
        if req.operation not in {"create", "amend", "cancel"}:
            raise HTTPException(status_code=422, detail="unsupported_operation")
        action["operation"] = req.operation
    if req.target_action_id is not None:
        action["target_action_id"] = req.target_action_id
    effective_operation = action.get("operation") or "create"
    target_action_id = action.get("target_action_id")
    if effective_operation in {"amend", "cancel"}:
        target = next((item for item in data["detected_actions"]
                       if item["action_id"] == target_action_id
                       and item["action_id"] != action_id), None)
        if target is None or target.get("status") != "routed":
            raise HTTPException(status_code=422,
                                detail="routed_target_action_id_required")
    if req.source_evidence is not None:
        action["source_evidence"] = req.source_evidence
    if req.field_sources is not None:
        action["field_sources"] = req.field_sources
    if req.attachment_ids is not None:
        action["attachment_ids"] = list(dict.fromkeys(req.attachment_ids))
    action["previous_versions"] = [*(action.get("previous_versions") or []), before]
    action["version"] += 1
    action["status"] = "edited"
    action["updated_at"] = utc_now()
    data = ensure_thread_data(data, thread_id=thread_id)
    action = next(item for item in data["detected_actions"] if item["action_id"] == action_id)
    audit_event(data, thread_id=thread_id, actor=req.acting_user,
                action="edit_action", reason_code=req.reason or "human_edit",
                record_version=action["version"], action_id=action_id,
                changed_fields=sorted(req.fields or {}))
    _persist(rec, data)
    return {"status": "edited", "action": action}


class MemoCreate(BaseModel):
    text: str = Field(min_length=1)
    item_type: str = "todo"
    date_phrase: str | None = None
    resolved_date: str | None = None
    date_relation: str | None = None
    source_evidence: list[dict[str, Any]] = Field(default_factory=list)
    acting_user: str = "alice"


@router.post("/threads/{thread_id}/memos")
async def add_memo(thread_id: str, req: MemoCreate) -> dict[str, Any]:
    rec = store.get(thread_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="thread not found")
    data = _thread_data(rec)
    raw = {
        "memo_id": f"memo-{thread_id}-{len(data['memo_items']) + 1:03d}",
        "text": req.text.strip(), "model_text": "", "current_text": req.text.strip(),
        "item_type": req.item_type, "date_phrase": req.date_phrase,
        "resolved_date": req.resolved_date, "date_relation": req.date_relation,
        "source_evidence": req.source_evidence, "version": 1,
        "status": "active", "is_completed": False,
        "position": len(data["memo_items"]), "created_at": utc_now(),
    }
    memo = ensure_memos([raw], thread_id=thread_id, messages=data["messages"])[0]
    data["memo_items"].append(memo)
    audit_event(data, thread_id=thread_id, actor=req.acting_user,
                action="create_memo", reason_code="human_created", memo_id=memo["memo_id"],
                record_version=memo["version"])
    _persist(rec, data)
    return {"status": "active", "memo": memo}


class MemoPatch(BaseModel):
    expected_version: int = Field(ge=1)
    text: str | None = None
    item_type: str | None = None
    date_phrase: str | None = None
    resolved_date: str | None = None
    date_relation: str | None = None
    is_completed: bool | None = None
    dismissed: bool | None = None
    position: int | None = Field(default=None, ge=0)
    acting_user: str = "alice"


@router.patch("/threads/{thread_id}/memos/{memo_id}")
async def edit_memo(thread_id: str, memo_id: str, req: MemoPatch) -> dict[str, Any]:
    rec = store.get(thread_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="thread not found")
    data = _thread_data(rec)
    memo = next((item for item in data["memo_items"] if item["memo_id"] == memo_id), None)
    if memo is None:
        raise HTTPException(status_code=404, detail="memo not found")
    if memo["version"] != req.expected_version:
        raise HTTPException(status_code=409,
                            detail=f"stale_version: memo is version {memo['version']}")
    if req.text is not None:
        if not req.text.strip():
            raise HTTPException(status_code=422, detail="memo text cannot be empty")
        memo["current_text"] = req.text.strip()
        memo["text"] = req.text.strip()
    if req.item_type is not None:
        if req.item_type not in {"todo", "important_date"}:
            raise HTTPException(status_code=422, detail="unsupported_memo_type")
        memo["item_type"] = req.item_type
    for key in ("date_phrase", "resolved_date", "date_relation", "position"):
        value = getattr(req, key)
        if value is not None:
            memo[key] = value
    if req.dismissed:
        memo["status"] = "dismissed"
        memo["dismissed_at"] = utc_now()
        memo["is_completed"] = False
    elif req.is_completed is not None:
        memo["is_completed"] = req.is_completed
        memo["status"] = "completed" if req.is_completed else "active"
    memo["version"] += 1
    memo["updated_at"] = utc_now()
    audit_event(data, thread_id=thread_id, actor=req.acting_user,
                action="update_memo", reason_code=memo["status"], memo_id=memo_id,
                record_version=memo["version"])
    _persist(rec, data)
    return {"status": memo["status"], "memo": memo}
