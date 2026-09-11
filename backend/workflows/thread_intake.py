"""WF1 thread state, evidence grounding, reconciliation and audit primitives.

All functions are deterministic except explicit audit timestamps supplied at mutation time.
Pre-contract rows are normalised by an idempotent startup migration; the same normaliser is
also applied defensively at the API boundary.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from .triage_contract import ensure_action_contract

SUPPORTED_ACTIONS = {"schedule_meeting", "expense_claim"}
REVIEWABLE_ACTION_STATUSES = {"pending", "proposed", "edited"}
MEMO_TYPES = {"todo", "important_date"}
THREAD_SCHEMA_VERSION = 2

ACTION_FIELDS: dict[str, set[str]] = {
    "schedule_meeting": {
        "title", "participants", "date", "date_phrase", "time", "start_time",
        "duration_minutes", "location", "location_or_video", "agenda", "mode",
    },
    "expense_claim": {
        "employee_name", "vendor", "date", "expense_date", "amount", "currency",
        "category", "business_purpose", "cost_centre", "evidence_type",
        "missing_receipt_declaration",
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _integer(value: Any, default: int = 1) -> int:
    if isinstance(value, bool):
        return default
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


def _normal_text(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _with_flag(item: dict, rule: str, message: str, severity: str = "soft") -> None:
    flags = item.setdefault("flags", [])
    if not any(flag.get("rule") == rule and flag.get("message") == message for flag in flags):
        flags.append({"rule": rule, "severity": severity, "message": message})


def normalise_attachments(raw: Any, *, thread_id: str) -> list[dict[str, Any]]:
    attachments: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, original in enumerate(raw if isinstance(raw, list) else []):
        item = dict(original) if isinstance(original, dict) else {"filename": str(original)}
        fallback = f"att-{thread_id}-{index + 1:03d}"
        attachment_id = str(item.get("attachment_id") or item.get("id") or fallback).strip()
        if not attachment_id or attachment_id in used:
            attachment_id = fallback
        used.add(attachment_id)
        mime = str(item.get("mime_type") or item.get("content_type") or "application/octet-stream")
        byte_size = item.get("byte_size", item.get("size"))
        if isinstance(byte_size, bool) or not isinstance(byte_size, (int, float)):
            byte_size = None
        attachments.append({
            **item,
            "attachment_id": attachment_id,
            "filename": str(item.get("filename") or attachment_id),
            "mime_type": mime,
            "byte_size": int(byte_size) if byte_size is not None else None,
            "evidence_type": item.get("evidence_type") or (
                "receipt" if mime.startswith("image/") or mime == "application/pdf" else "supporting"
            ),
        })
    return attachments


def normalise_messages(data: dict[str, Any], *, thread_id: str) -> list[dict[str, Any]]:
    raw_messages = data.get("messages")
    messages: list[dict[str, Any]] = []
    used: set[str] = set()
    if isinstance(raw_messages, list) and raw_messages:
        for index, original in enumerate(raw_messages):
            if not isinstance(original, dict):
                continue
            fallback = f"msg-{thread_id}-{index + 1:03d}"
            message_id = str(original.get("message_id") or original.get("id") or fallback).strip()
            if not message_id or message_id in used:
                message_id = fallback
            used.add(message_id)
            messages.append({
                "message_id": message_id,
                "sender": str(original.get("sender") or "Unknown"),
                "sent_at": original.get("sent_at") or original.get("timestamp")
                or data.get("received_at"),
                "body": str(original.get("body") or original.get("text") or ""),
                "attachment_ids": list(dict.fromkeys(original.get("attachment_ids") or [])),
            })
        return messages

    for index, line in enumerate(str(data.get("raw_text") or "").splitlines()):
        if not line.strip():
            continue
        match = re.match(r"^([^:]{1,80}):\s*(.*)$", line)
        sender, body = (match.group(1), match.group(2)) if match else ("Unknown", line)
        messages.append({
            "message_id": f"msg-{thread_id}-{index + 1:03d}",
            "sender": sender.strip(),
            "sent_at": data.get("received_at"),
            "body": body.strip(),
            "attachment_ids": [],
        })
    return messages


def _evidence_item(original: Any, message_map: dict[str, dict]) -> dict[str, Any] | None:
    if not isinstance(original, dict):
        return None
    message_id = str(original.get("message_id") or "")
    span = str(original.get("span") or "").strip()
    message = message_map.get(message_id)
    grounded = bool(message and span and _normal_text(span) in _normal_text(message.get("body")))
    if not message_id and not span:
        return None
    return {"message_id": message_id, "span": span, "grounded": grounded}


def ground_action(action: dict[str, Any], *, messages: list[dict[str, Any]],
                  attachments: list[dict[str, Any]]) -> dict[str, Any]:
    result = dict(action)
    message_map = {message["message_id"]: message for message in messages}
    evidence = [item for item in (
        _evidence_item(raw, message_map) for raw in result.get("source_evidence") or []
    ) if item]
    legacy_span = str(result.get("source_span") or "").strip()
    if not evidence and legacy_span:
        match = next((message for message in messages
                      if _normal_text(legacy_span) in _normal_text(message.get("body"))), None)
        evidence = [{
            "message_id": match["message_id"] if match else "",
            "span": legacy_span,
            "grounded": bool(match),
        }]
    result["source_evidence"] = evidence
    result.pop("source_span", None)
    if not evidence or any(not item["grounded"] for item in evidence):
        _with_flag(result, "evidence_unresolved", "source evidence does not match a thread message")

    field_sources: dict[str, dict[str, Any]] = {}
    for field_name, raw in (result.get("field_sources") or {}).items():
        item = _evidence_item(raw, message_map)
        if item:
            field_sources[str(field_name)] = item
            if not item["grounded"]:
                _with_flag(result, "field_evidence_unresolved",
                           f"evidence for {field_name} does not match its message")
    result["field_sources"] = field_sources

    available = {item["attachment_id"] for item in attachments}
    requested = list(dict.fromkeys(result.get("attachment_ids") or []))
    result["attachment_ids"] = [item for item in requested if item in available]
    invalid = [item for item in requested if item not in available]
    if invalid:
        _with_flag(result, "attachment_unresolved",
                   f"unknown attachment reference(s): {', '.join(invalid)}")
    return result


def normalise_seed(action_type: str, raw: Any) -> dict[str, Any]:
    seed = dict(raw) if isinstance(raw, dict) else {}
    allowed = ACTION_FIELDS.get(action_type, set())
    seed = {key: value for key, value in seed.items() if key in allowed}
    if action_type == "schedule_meeting":
        if "date" not in seed and "date_phrase" in seed:
            seed["date"] = seed["date_phrase"]
        if "time" not in seed and "start_time" in seed:
            seed["time"] = seed["start_time"]
        if "location" not in seed and "location_or_video" in seed:
            seed["location"] = seed["location_or_video"]
    elif action_type == "expense_claim" and "date" not in seed and "expense_date" in seed:
        seed["date"] = seed["expense_date"]
    return seed


def action_missing_fields(action: dict[str, Any]) -> list[str]:
    seed = action.get("current_seed_fields") or {}
    if action.get("action_type") == "schedule_meeting":
        required = ("title", "participants", "date")
    elif action.get("action_type") == "expense_claim":
        required = ("employee_name", "vendor", "date", "amount", "currency",
                    "category", "business_purpose")
    else:
        return []
    return [key for key in required if seed.get(key) in (None, "", [])]


def ensure_actions(actions: Any, *, thread_id: str, messages: list[dict[str, Any]],
                   attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contracted = ensure_action_contract(actions if isinstance(actions, list) else [],
                                        thread_id=thread_id)
    output: list[dict[str, Any]] = []
    base_time = messages[0].get("sent_at") if messages else None
    for action in contracted:
        action_type = str(action.get("action_type") or "none")
        model_seed = normalise_seed(action_type, action.get("model_seed_fields"))
        current_seed = normalise_seed(action_type, action.get("current_seed_fields"))
        action["model_seed_fields"] = model_seed
        action["current_seed_fields"] = current_seed
        action.setdefault("status", "proposed")
        action.setdefault("created_at", base_time)
        action.setdefault("updated_at", action.get("created_at"))
        action.setdefault("previous_versions", [])
        action = ground_action(action, messages=messages, attachments=attachments)
        action["missing_fields"] = action_missing_fields(action)
        output.append(action)
    return output


def ensure_memos(memos: Any, *, thread_id: str,
                 messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    message_map = {message["message_id"]: message for message in messages}
    for index, original in enumerate(memos if isinstance(memos, list) else []):
        if not isinstance(original, dict):
            continue
        memo = dict(original)
        memo_id = str(memo.get("memo_id") or f"memo-{thread_id}-{index + 1:03d}")
        current_text = str(memo.get("current_text") or memo.get("text") or "").strip()
        model_text = str(memo.get("model_text") or memo.get("text") or current_text).strip()
        is_completed = bool(memo.get("is_completed", False))
        status = memo.get("status")
        if status not in {"active", "completed", "dismissed"}:
            status = "completed" if is_completed else "active"
        evidence = [item for item in (
            _evidence_item(raw, message_map) for raw in memo.get("source_evidence") or []
        ) if item]
        memo.update({
            "memo_id": memo_id,
            "version": _integer(memo.get("version")),
            "text": current_text,
            "model_text": model_text,
            "current_text": current_text,
            "item_type": memo.get("item_type") if memo.get("item_type") in MEMO_TYPES else "todo",
            "date_phrase": memo.get("date_phrase"),
            "resolved_date": memo.get("resolved_date"),
            "date_relation": memo.get("date_relation"),
            "is_completed": status == "completed",
            "status": status,
            "position": int(memo.get("position", index)),
            "source_evidence": evidence,
            "created_at": memo.get("created_at") or (messages[0].get("sent_at") if messages else None),
            "updated_at": memo.get("updated_at") or memo.get("created_at"),
            "dismissed_at": memo.get("dismissed_at"),
            "flags": list(memo.get("flags") or []),
        })
        if evidence and any(not item["grounded"] for item in evidence):
            _with_flag(memo, "evidence_unresolved", "memo evidence does not match its message")
        output.append(memo)
    return sorted(output, key=lambda item: (item["position"], item["memo_id"]))


def ensure_thread_data(data: dict[str, Any], *, thread_id: str) -> dict[str, Any]:
    result = dict(data)
    attachments = normalise_attachments(result.get("attachments"), thread_id=thread_id)
    messages = normalise_messages(result, thread_id=thread_id)
    valid_attachment_ids = {item["attachment_id"] for item in attachments}
    for message in messages:
        message["attachment_ids"] = [item for item in message["attachment_ids"]
                                     if item in valid_attachment_ids]
    result.update({
        "messages": messages,
        "attachments": attachments,
        "detected_actions": ensure_actions(
            result.get("detected_actions"), thread_id=thread_id,
            messages=messages, attachments=attachments),
        "memo_items": ensure_memos(result.get("memo_items"), thread_id=thread_id,
                                    messages=messages),
        "audit_events": list(result.get("audit_events") or []),
        "analysis_runs": list(result.get("analysis_runs") or []),
        "last_triaged_message_id": result.get("last_triaged_message_id"),
        "thread_schema_version": THREAD_SCHEMA_VERSION,
    })
    return result


def _next_id(prefix: str, thread_id: str, existing: list[dict], key: str) -> str:
    used = {str(item.get(key)) for item in existing}
    index = len(existing) + 1
    candidate = f"{prefix}-{thread_id}-{index:03d}"
    while candidate in used:
        index += 1
        candidate = f"{prefix}-{thread_id}-{index:03d}"
    return candidate


def _action_fingerprint(action: dict[str, Any]) -> str:
    return json.dumps({
        "action_type": action.get("action_type"),
        "seed": action.get("current_seed_fields") or {},
    }, sort_keys=True, default=str)


def reconcile_actions(existing: list[dict[str, Any]], proposed: list[dict[str, Any]], *,
                      thread_id: str, at: str) -> list[dict[str, Any]]:
    actions = [dict(item) for item in existing]
    for proposal in proposed:
        operation = proposal.get("operation", "create")
        target_id = proposal.get("target_action_id")
        target_index = next((index for index, item in enumerate(actions)
                             if item.get("action_id") == target_id), None)
        if operation in {"amend", "cancel"} and target_index is not None:
            target = dict(actions[target_index])
            prior_version = _integer(target.get("version"))
            history = list(target.get("previous_versions") or [])
            history.append({
                "version": prior_version,
                "operation": target.get("operation", "create"),
                "current_seed_fields": target.get("current_seed_fields") or {},
                "source_evidence": target.get("source_evidence") or [],
                "status": target.get("status"),
                "routed_to": target.get("routed_to"),
                "updated_at": target.get("updated_at"),
            })
            merged = dict(target.get("current_seed_fields") or {})
            if operation == "amend":
                merged.update(proposal.get("current_seed_fields") or {})
            target.update(proposal)
            target.update({
                "action_id": target_id,
                "target_action_id": target_id,
                "version": prior_version + 1,
                "operation": operation,
                "model_seed_fields": dict(proposal.get("model_seed_fields") or {}),
                "current_seed_fields": merged,
                "status": "proposed",
                "routed_to": None,
                "target_record_id": actions[target_index].get("routed_to"),
                "previous_versions": history,
                "updated_at": at,
            })
            target["missing_fields"] = action_missing_fields(target)
            actions[target_index] = target
            continue

        if operation in {"amend", "cancel"} and target_index is None:
            _with_flag(proposal, "target_unresolved",
                       "amend/cancel target could not be resolved in this thread")
        if operation == "create" and any(
            _action_fingerprint(item) == _action_fingerprint(proposal) for item in actions
        ):
            continue
        proposal = dict(proposal)
        proposal.update({
            "action_id": _next_id("act", thread_id, actions, "action_id"),
            "version": 1,
            "status": "proposed",
            "created_at": at,
            "updated_at": at,
        })
        actions.append(proposal)
    return actions


def _memo_fingerprint(memo: dict[str, Any]) -> tuple[str, str]:
    return (_normal_text(memo.get("current_text") or memo.get("text")),
            str(memo.get("resolved_date") or memo.get("date_phrase") or ""))


def reconcile_memos(existing: list[dict[str, Any]], proposed: list[dict[str, Any]], *,
                    thread_id: str, at: str) -> list[dict[str, Any]]:
    memos = [dict(item) for item in existing]
    existing_keys = {_memo_fingerprint(item) for item in memos}
    for proposal in proposed:
        fingerprint = _memo_fingerprint(proposal)
        if not fingerprint[0] or fingerprint in existing_keys:
            continue
        memo = dict(proposal)
        memo.update({
            "memo_id": _next_id("memo", thread_id, memos, "memo_id"),
            "version": 1,
            "status": "active",
            "is_completed": False,
            "position": len(memos),
            "created_at": at,
            "updated_at": at,
        })
        memos.append(memo)
        existing_keys.add(fingerprint)
    return memos


def audit_event(data: dict[str, Any], *, thread_id: str, actor: str, action: str,
                reason_code: str, record_version: int | None = None,
                at: str | None = None, **details: Any) -> dict[str, Any]:
    events = data.setdefault("audit_events", [])
    event = {
        "event_id": f"audit-{thread_id}-{len(events) + 1:04d}",
        "actor": actor,
        "action": action,
        "timestamp": at or utc_now(),
        "record_version": record_version,
        "reason_code": reason_code,
        **details,
    }
    events.append(event)
    return event


def thread_status(actions: list[dict[str, Any]]) -> str:
    actionable = [item for item in actions if item.get("action_type") in SUPPORTED_ACTIONS]
    if not actionable:
        return "analysed"
    pending = [item for item in actionable if item.get("status") in REVIEWABLE_ACTION_STATUSES]
    handled = [item for item in actionable if item.get("status") in {"routed", "dismissed"}]
    if pending and handled:
        return "partially_routed"
    if pending:
        return "in_review"
    return "resolved"


def migrate_thread_records(store: Any) -> dict[str, int]:
    """Persist every thread in the canonical schema once, preserving archived state."""
    migrated = 0
    for record in store.list("threads"):
        if record.data.get("thread_schema_version") == THREAD_SCHEMA_VERSION:
            continue
        data = ensure_thread_data(record.data, thread_id=record.id)
        status = record.status if record.status == "archived" else thread_status(
            data["detected_actions"]
        )
        store.update(record.id, data=data, status=status)
        migrated += 1
    return {"migrated": migrated}


def untriaged_messages(data: dict[str, Any]) -> list[dict[str, Any]]:
    messages = data.get("messages") or []
    last_id = data.get("last_triaged_message_id")
    if not last_id:
        return list(messages)
    for index, message in enumerate(messages):
        if message.get("message_id") == last_id:
            return messages[index + 1:]
    return list(messages)


def triage_text(data: dict[str, Any]) -> str:
    delta = untriaged_messages(data)
    active = [item for item in data.get("detected_actions") or []
              if item.get("status") != "dismissed"]
    context = ""
    if active:
        compact = [{
            "action_id": item.get("action_id"),
            "action_type": item.get("action_type"),
            "status": item.get("status"),
            "current_seed_fields": item.get("current_seed_fields"),
        } for item in active]
        context = "Existing action state (reference IDs for amend/cancel):\n" + json.dumps(
            compact, ensure_ascii=False, sort_keys=True) + "\n\nNew messages:\n"
    return context + "\n".join(
        (
            f"[{message['message_id']}] {message['sender']}: {message['body']}"
            + (
                f" [attachments: {', '.join(message.get('attachment_ids') or [])}]"
                if message.get("attachment_ids")
                else ""
            )
        )
        for message in delta
    )
