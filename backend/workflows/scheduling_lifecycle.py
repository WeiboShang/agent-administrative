"""WF2 deterministic lifecycle, candidate ranking and reusable context primitives.

This module keeps the LLM outside calendar state: it accepts an already interpreted
specification and turns it into explainable, reviewable candidate drafts.  Mutations
remain separate and only occur after an explicit human approval in the router.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Callable

from ..fixtures import org
from ..backends.records import RecordStore
from . import policy
from .scheduling import add_minutes, resolve_relative_date

DEFAULT_DURATION = 30
WORKDAY_START, WORKDAY_END = policy.WORKING_HOURS


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _time_minutes(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":"))
    return hour * 60 + minute


def _date_range(start: str, end: str) -> list[str]:
    start_day = datetime.strptime(start, "%Y-%m-%d").date()
    end_day = datetime.strptime(end, "%Y-%m-%d").date()
    return [
        (start_day + timedelta(days=offset)).isoformat()
        for offset in range((end_day - start_day).days + 1)
    ]


def _normalise_people(names: list[str] | None) -> tuple[list[str], list[str]]:
    resolved, unresolved = [], []
    for name in names or []:
        person = org.find_person(str(name))
        if person:
            resolved.append(person.user_id)
        elif str(name).strip():
            unresolved.append(str(name).strip())
    return list(dict.fromkeys(resolved)), unresolved


def normalise_spec(
    raw: dict[str, Any], *, now: datetime,
    date_resolver: Callable[[object, datetime], str | None] = resolve_relative_date,
) -> dict[str, Any]:
    """Produce one canonical create/update/reschedule/cancel/reuse specification."""
    operation = str(raw.get("operation") or "CREATE").upper()
    if operation not in {"CREATE", "UPDATE", "RESCHEDULE", "CANCEL", "REUSE"}:
        operation = "CREATE"
    duration = raw.get("duration_minutes") or DEFAULT_DURATION
    try:
        duration = max(15, min(480, int(duration)))
    except (TypeError, ValueError):
        duration = DEFAULT_DURATION

    date_window = (
        raw.get("date_window") if isinstance(raw.get("date_window"), dict) else {}
    )
    start = raw.get("date") or date_window.get("start")
    end = date_window.get("end") or start
    start = date_resolver(start, now) if start else None
    end = date_resolver(end, now) if end else start
    if start and end and end < start:
        start, end = end, start

    preferences = (
        raw.get("soft_preferences")
        if isinstance(raw.get("soft_preferences"), dict)
        else {}
    )
    hard = (
        raw.get("hard_constraints")
        if isinstance(raw.get("hard_constraints"), dict)
        else {}
    )
    exact_time = raw.get("exact_time") or raw.get("time") or raw.get("exact_start")
    if isinstance(exact_time, str) and "T" in exact_time:
        exact_time = exact_time.rsplit("T", 1)[-1][:5]
    participant_names = raw.get("participants")
    if not isinstance(participant_names, list):
        participant_names = raw.get("participant_names")
    if not isinstance(participant_names, list):
        participant_names = []
    return {
        "operation": operation,
        "target_event_id": raw.get("target_event_id"),
        "context_id": raw.get("context_id"),
        "title": str(raw.get("title") or "Untitled meeting").strip(),
        "participant_names": [
            str(item).strip()
            for item in participant_names
            if str(item).strip()
        ],
        "duration_minutes": duration,
        "date_window": {"start": start, "end": end},
        "exact_time": exact_time if isinstance(exact_time, str) else None,
        "location": str(raw.get("location") or raw.get("preferred_room") or "").strip()
        or None,
        "mode": str(raw.get("mode") or "virtual"),
        "agenda": str(raw.get("agenda") or "").strip(),
        "hard_constraints": {
            "working_hours_only": hard.get("working_hours_only", True),
            "required_room": hard.get("required_room", False),
        },
        "soft_preferences": {
            "preferred_period": preferences.get("preferred_period"),
            "avoid_lunch": bool(preferences.get("avoid_lunch", False)),
            "buffer_before_minutes": int(preferences.get("buffer_before_minutes") or 0),
            "buffer_after_minutes": int(preferences.get("buffer_after_minutes") or 0),
            "earliest": bool(preferences.get("earliest", False)),
        },
        "provenance": dict(raw.get("provenance") or {}),
    }


def _booked_events(
    store: RecordStore, target_event_id: str | None = None
) -> list[dict[str, Any]]:
    return [
        {"id": record.id, **record.data}
        for record in store.list("events", status="booked")
        if record.id != target_event_id
    ]


def _overlaps(start: str, end: str, other: dict[str, Any]) -> bool:
    return start < str(other.get("end") or "") and str(other.get("start") or "") < end


def _canonical_room(value: Any) -> str:
    """Resolve common display variants to one synthetic room identity."""
    text = " ".join(str(value or "").casefold().replace("-", " ").split())
    for room in org.ROOMS:
        aliases = {
            room.room_id.casefold(),
            room.name.casefold(),
            f"{room.name.casefold()} room",
            f"meeting room {room.name.casefold()}",
        }
        if text in aliases:
            return room.room_id
    return text


def _available(
    spec: dict[str, Any], day: str, start: str, store: RecordStore, *, actor: str | None
) -> tuple[bool, list[str]]:
    end = add_minutes(start, int(spec["duration_minutes"]))
    if end > WORKDAY_END or start < WORKDAY_START:
        return False, ["outside_working_hours"]
    participant_ids, unresolved = _normalise_people(spec["participant_names"])
    organiser = org.find_person(str(actor or ""))
    if organiser:
        participant_ids = list(dict.fromkeys([*participant_ids, organiser.user_id]))
    if unresolved:
        return False, ["unresolved_participant"]
    blockers: list[str] = []
    for event in _booked_events(store, spec.get("target_event_id")):
        if event.get("date") != day or not _overlaps(start, end, event):
            continue
        if set(participant_ids) & set(event.get("participants") or []):
            blockers.append("participant_conflict")
        if spec.get("location") and _canonical_room(spec["location"]) == _canonical_room(
            event.get("location")
        ):
            blockers.append("room_conflict")
    return not blockers, list(dict.fromkeys(blockers))


def _score(
    spec: dict[str, Any], day: str, start: str
) -> tuple[int, dict[str, int], list[str]]:
    preferences = spec["soft_preferences"]
    score = {
        "request_preference": 0,
        "buffer": 0,
        "room": 0,
        "urgency": 0,
        "disruption": 0,
    }
    reasons = ["all_participants_available"]
    hour = _time_minutes(start) // 60
    period = preferences.get("preferred_period")
    if period == "afternoon" and hour >= 12:
        score["request_preference"] += 30
        reasons.append("preferred_afternoon")
    if period == "morning" and hour < 12:
        score["request_preference"] += 30
        reasons.append("preferred_morning")
    if preferences.get("avoid_lunch") and not (12 <= hour < 13):
        score["buffer"] += 10
        reasons.append("lunch_avoided")
    if spec.get("location"):
        score["room"] += 10
        reasons.append("preferred_room_available")
    if preferences.get("earliest"):
        score["urgency"] += max(0, 20 - hour)
        reasons.append("earliest_preference")
    original = spec.get("original_event") or {}
    if spec["operation"] == "RESCHEDULE" and original:
        old_day, old_time = original.get("date"), original.get("start")
        if old_day == day:
            score["disruption"] -= 5
            reasons.append("same_day_minimal_disruption")
        if old_time == start:
            score["disruption"] -= 100
    return sum(score.values()), score, reasons


def _calendar_signature(store: RecordStore) -> str:
    rows = [
        {"id": record.id, "updated_at": record.updated_at, "status": record.status}
        for record in store.list("events")
    ]
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:16]


def recommend_candidates(
    spec: dict[str, Any], store: RecordStore, *, now: datetime, actor: str | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    """Return diversified, deterministic Top-K candidate drafts and a revalidation token."""
    missing = [
        field
        for field, value in (
            ("date_window", spec["date_window"].get("start")),
            ("participants", spec["participant_names"]),
        )
        if not value
    ]
    if missing:
        return {
            "candidates": [],
            "missing": missing,
            "blockers": [],
            "warnings": [],
            "validation_token": None,
        }

    start_day = spec["date_window"]["start"]
    end_day = spec["date_window"]["end"] or start_day

    # A flexible date window must not hide a clash at the slot the human actually
    # entered.  Candidate search can still find the same time on a later day, but the
    # starting date + exact time remains the requested slot and needs an explicit warning.
    requested_slot_blockers: list[str] = []
    exact_time = spec.get("exact_time")
    if exact_time:
        try:
            datetime.strptime(exact_time, "%H:%M")
        except (TypeError, ValueError):
            requested_slot_blockers = ["invalid_requested_time"]
        else:
            requested_slot_ok, requested_slot_blockers = _available(
                spec, start_day, exact_time, store, actor=actor
            )
            if requested_slot_ok:
                requested_slot_blockers = []

    def collect(*, enforce_exact: bool) -> tuple[list[dict[str, Any]], Counter[str]]:
        found: list[dict[str, Any]] = []
        blocked: Counter[str] = Counter()
        for day in _date_range(start_day, end_day):
            cursor = datetime.strptime(WORKDAY_START, "%H:%M")
            while cursor.strftime("%H:%M") < WORKDAY_END:
                start = cursor.strftime("%H:%M")
                if (
                    enforce_exact
                    and spec.get("exact_time")
                    and start != spec["exact_time"]
                ):
                    cursor += timedelta(minutes=30)
                    continue
                ok, blockers = _available(spec, day, start, store, actor=actor)
                if ok:
                    total, components, reasons = _score(spec, day, start)
                    found.append(
                        {
                            "candidate_id": f"slot-{day.replace('-', '')}-{start.replace(':', '')}",
                            "date": day,
                            "start": start,
                            "end": add_minutes(start, int(spec["duration_minutes"])),
                            "score": total,
                            "score_components": components,
                            "reason_codes": reasons,
                            "warning_codes": [],
                        }
                    )
                else:
                    blocked.update(blockers)
                cursor += timedelta(minutes=30)
        return found, blocked

    exact_requested = bool(exact_time)
    slots, blocker_counts = collect(enforce_exact=exact_requested)
    relaxed_exact = exact_requested and not slots
    if relaxed_exact:
        slots, blocker_counts = collect(enforce_exact=False)
        for slot in slots:
            slot["reason_codes"].append("alternative_to_requested_time")
            slot["warning_codes"].append("requested_time_unavailable")

    requested_slot_unavailable = bool(requested_slot_blockers) or relaxed_exact
    occupied_reasons = {
        "participant_conflict",
        "room_conflict",
    } & set(requested_slot_blockers)
    warning_code = (
        "requested_slot_occupied"
        if occupied_reasons
        else "requested_time_unavailable"
    )
    if requested_slot_unavailable:
        for slot in slots:
            if "requested_time_unavailable" not in slot["warning_codes"]:
                slot["warning_codes"].append("requested_time_unavailable")
            if occupied_reasons and warning_code not in slot["warning_codes"]:
                slot["warning_codes"].append(warning_code)

    slots.sort(key=lambda item: (-item["score"], item["date"], item["start"]))
    diverse: list[dict[str, Any]] = []
    labels = ["recommended", "earliest_available", "best_context_match"]
    for candidate in slots:
        if any(
            candidate["date"] == chosen["date"]
            and abs(_time_minutes(candidate["start"]) - _time_minutes(chosen["start"]))
            < 60
            for chosen in diverse
        ):
            continue
        candidate["label"] = (
            labels[len(diverse)] if len(diverse) < len(labels) else "alternative"
        )
        diverse.append(candidate)
        if len(diverse) == limit:
            break

    token_basis = {
        "calendar": _calendar_signature(store),
        "spec": spec,
        "generated_at": now.isoformat(),
    }
    token = hashlib.sha256(
        json.dumps(token_basis, sort_keys=True, default=str).encode()
    ).hexdigest()
    warnings: list[dict[str, Any]] = []
    if requested_slot_unavailable:
        requested_end = (
            add_minutes(exact_time, int(spec["duration_minutes"]))
            if exact_time and "invalid_requested_time" not in requested_slot_blockers
            else None
        )
        if occupied_reasons == {"participant_conflict", "room_conflict"}:
            conflict_text = "one or more participants and the selected room are busy"
        elif "participant_conflict" in occupied_reasons:
            conflict_text = "one or more participants are busy"
        elif "room_conflict" in occupied_reasons:
            conflict_text = "the selected room is busy"
        else:
            conflict_text = "the requested time is not available"
        warnings.append(
            {
                "code": warning_code,
                "message": (
                    f"The requested slot on {start_day} at {exact_time}"
                    f"{f'–{requested_end}' if requested_end else ''} is unavailable: "
                    f"{conflict_text}. The options below are available alternatives."
                ),
                "date": start_day,
                "start": exact_time,
                "end": requested_end,
                "reason_codes": requested_slot_blockers,
            }
        )

    return {
        "candidates": diverse,
        "missing": [],
        "blockers": (
            ["requested_time_unavailable"]
            if requested_slot_unavailable and diverse
            else []
            if diverse
            else ["no_feasible_slot"]
        ),
        "warnings": warnings,
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "validation_token": token,
        "calendar_version": _calendar_signature(store),
    }


def build_context(event_id: str, store: RecordStore) -> dict[str, Any] | None:
    record = store.get(event_id)
    if record is None or record.store != "events":
        return None
    data = record.data
    return {
        "context_id": f"context-{event_id}",
        "source_event_id": event_id,
        "title": data.get("title"),
        "participants": [
            item.get("name")
            for item in data.get("participant_details", [])
            if item.get("name")
        ],
        "duration_minutes": data.get("duration_minutes") or DEFAULT_DURATION,
        "location": data.get("location"),
        "mode": data.get("mode") or "virtual",
        "agenda": data.get("agenda") or "",
        "provenance": {"title": "reusable_context", "participants": "reusable_context"},
    }


def lifecycle_mutation(
    *,
    spec: dict[str, Any],
    candidate: dict[str, Any] | None,
    store: RecordStore,
    actor: str,
    idempotency_key: str,
    validation_token: str | None,
    calendar_version: str | None,
    now: datetime | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Execute a human-approved lifecycle operation with replay protection."""
    effective_now = now or datetime.now()
    event_time = effective_now.isoformat()
    for record in store.list("events"):
        if record.data.get("idempotency_key") == idempotency_key:
            return {"status": "idempotent_replay", "record_id": record.id}

    if calendar_version and calendar_version != _calendar_signature(store):
        return {
            "status": "stale_validation",
            "message": "calendar changed; revalidate first",
        }

    operation = spec["operation"]
    if operation == "CANCEL":
        target = store.get(str(spec.get("target_event_id") or ""))
        if target is None or target.status != "booked":
            return {"status": "target_not_found"}
        data = {
            **target.data,
            "lifecycle": [
                *(target.data.get("lifecycle") or []),
                {
                    "operation": "CANCEL",
                    "actor": actor,
                    "at": event_time,
                    "reason": reason,
                },
            ],
        }
        store.update(target.id, data=data, status="cancelled")
        return {"status": "cancelled", "record_id": target.id}

    if candidate is None:
        return {"status": "candidate_required"}
    fresh = recommend_candidates(spec, store, now=effective_now, actor=actor)
    if not any(
        item["candidate_id"] == candidate.get("candidate_id")
        for item in fresh["candidates"]
    ):
        return {
            "status": "stale_validation",
            "message": "candidate is no longer feasible",
        }

    target_id = spec.get("target_event_id")
    if operation in {"UPDATE", "RESCHEDULE"} and target_id:
        target = store.get(str(target_id))
        if target is None or target.status != "booked":
            return {"status": "target_not_found"}
        previous = dict(target.data)
        participant_ids, unresolved = _normalise_people(spec["participant_names"])
        if unresolved:
            return {"status": "unresolved_participant", "participants": unresolved}
        details = [
            {"name": person.name, "resolved": True}
            for value in spec["participant_names"]
            if (person := org.find_person(str(value))) is not None
        ]
        data = {
            **previous,
            "title": spec["title"],
            "date": candidate["date"],
            "start": candidate["start"],
            "end": candidate["end"],
            "duration_minutes": spec["duration_minutes"],
            "location": spec.get("location"),
            "mode": spec["mode"],
            "agenda": spec["agenda"],
            "participants": participant_ids,
            "participant_details": details,
            "version": int(previous.get("version") or 1) + 1,
            "idempotency_key": idempotency_key,
            "lifecycle": [
                *(previous.get("lifecycle") or []),
                {
                    "operation": operation,
                    "actor": actor,
                    "at": event_time,
                    "before": {
                        "date": previous.get("date"),
                        "start": previous.get("start"),
                    },
                    "after": {"date": candidate["date"], "start": candidate["start"]},
                },
            ],
        }
        store.update(target.id, data=data, status="booked")
        return {"status": operation.lower(), "record_id": target.id, "event": data}

    participant_ids, _ = _normalise_people(spec["participant_names"])
    # Smart Schedule's picker sends stable directory IDs (``chen``), while reused
    # contexts and API callers may send display names (``Chen Wei``).  Persist the
    # canonical display name in both cases; otherwise the calendar renders raw IDs and
    # later reuse turns those IDs into user-facing labels.
    details = [
        {"name": person.name, "resolved": True}
        for value in spec["participant_names"]
        if (person := org.find_person(str(value))) is not None
    ]
    data = {
        "title": spec["title"],
        "organizer": actor,
        "participants": participant_ids,
        "participant_details": details,
        "date": candidate["date"],
        "start": candidate["start"],
        "end": candidate["end"],
        "duration_minutes": spec["duration_minutes"],
        "location": spec.get("location"),
        "mode": spec["mode"],
        "agenda": spec["agenda"],
        "version": 1,
        "idempotency_key": idempotency_key,
        "entry_mode": "smart_schedule",
        "operation": operation,
        "candidate": candidate,
        "provenance": spec.get("provenance") or {},
        "lifecycle": [
            {
                "operation": operation,
                "actor": actor,
                "at": event_time,
                "candidate_id": candidate["candidate_id"],
            }
        ],
    }
    record = store.create("events", "event", data, status="booked")
    return {"status": "booked", "record_id": record.id, "event": data}


def save_context(
    context: dict[str, Any], store: RecordStore, *, actor: str
) -> dict[str, Any]:
    """Persist a confirmed reusable meeting context in the local synthetic workspace."""
    data = {
        "name": str(
            context.get("name") or context.get("title") or "Reusable meeting"
        ).strip(),
        "title": context.get("title"),
        "participants": list(context.get("participants") or []),
        "duration_minutes": int(context.get("duration_minutes") or DEFAULT_DURATION),
        "location": context.get("location"),
        "mode": context.get("mode") or "virtual",
        "agenda": context.get("agenda") or "",
        "recurrence": context.get("recurrence"),
        "confirmed_by": actor,
        "created_at": utc_now(),
        "use_count": 0,
    }
    record = store.create("events", "meeting_context", data, status="active")
    return {"context_id": record.id, **data}


def list_contexts(store: RecordStore) -> list[dict[str, Any]]:
    return [
        {"context_id": record.id, **record.data}
        for record in store.list(
            "events", record_type="meeting_context", status="active"
        )
    ]


def load_context(context_id: str, store: RecordStore) -> dict[str, Any] | None:
    record = store.get(context_id)
    if record is None or record.type != "meeting_context" or record.status != "active":
        return None
    return {"context_id": record.id, **record.data}


def apply_context(
    spec: dict[str, Any], context: dict[str, Any] | None
) -> dict[str, Any]:
    """Fill only absent fields: an explicit request always wins over saved context."""
    if not context:
        return spec
    merged = dict(spec)
    for key in ("title", "duration_minutes", "location", "mode", "agenda"):
        if merged.get(key) in (None, "", "Untitled meeting"):
            merged[key] = context.get(key)
            merged.setdefault("provenance", {})[key] = "reusable_context"
    if not merged.get("participant_names"):
        merged["participant_names"] = list(context.get("participants") or [])
        merged.setdefault("provenance", {})["participants"] = "reusable_context"
    merged["context_id"] = context["context_id"]
    if context.get("recurrence") and not merged.get("recurrence"):
        merged["recurrence"] = context["recurrence"]
    return merged


def next_occurrence_window(
    recurrence: dict[str, Any] | None, *, after: str
) -> dict[str, str] | None:
    """Return the next reviewable occurrence window; it never books automatically."""
    if not isinstance(recurrence, dict):
        return None
    interval = max(1, int(recurrence.get("interval_weeks") or 1))
    weekday = recurrence.get("weekday")
    try:
        day = datetime.strptime(after, "%Y-%m-%d").date() + timedelta(days=1)
    except ValueError:
        return None
    if isinstance(weekday, int) and 0 <= weekday <= 6:
        day += timedelta(days=(weekday - day.weekday()) % 7)
    else:
        day += timedelta(days=7 * interval)
    return {"start": day.isoformat(), "end": (day + timedelta(days=4)).isoformat()}


def analytics_rows(store: RecordStore) -> list[dict[str, Any]]:
    """Expose operation history for operational charts without model-quality claims."""
    rows = []
    for record in store.list("events"):
        if record.type not in {"event", "schedule_meeting"}:
            continue
        data = record.data
        rows.append(
            {
                "id": record.id,
                "status": record.status,
                "title": data.get("title"),
                "date": data.get("date"),
                "start": data.get("start"),
                "end": data.get("end"),
                "participants": [
                    item.get("name")
                    for item in data.get("participant_details", [])
                    if item.get("name")
                ]
                or data.get("participants", []),
                "location": data.get("location"),
                "entry_mode": data.get("entry_mode") or "quick_create",
                "operation": data.get("operation") or "CREATE",
                "lifecycle": data.get("lifecycle") or [],
                "context_id": data.get("context_id"),
                "duration_minutes": data.get("duration_minutes"),
            }
        )
    return rows
