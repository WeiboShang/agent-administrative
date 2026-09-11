"""Low-level tools for the isolated WorkBench-style external agent.

The tools expose state and primitive mutations.  They deliberately do not call WF1 triage,
Smart Schedule, expense reconciliation or deterministic expense-policy decision functions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from .. import money
from ..backends.records import RecordStore
from ..fixtures import org
from ..workflows import policy
from .external_workbench_agent import ExternalTool
from .outcomes_v3 import WorkspaceState

OBJECT = "object"
STRING = "string"
NUMBER = "number"
INTEGER = "integer"
ARRAY = "array"


def _params(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": OBJECT,
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _string(description: str) -> dict[str, Any]:
    return {"type": STRING, "description": description}


def _optional_string(description: str) -> dict[str, Any]:
    return {"type": [STRING, "null"], "description": description}


def _string_array(description: str) -> dict[str, Any]:
    return {"type": ARRAY, "items": {"type": STRING}, "description": description}


@dataclass
class ToolContext:
    workflow: str
    store: RecordStore
    now: datetime
    case_id: str
    thread_id: str | None = None
    source_message_ids: set[str] = field(default_factory=set)
    attachment_ids: set[str] = field(default_factory=set)
    receipt_evidence: dict[str, Any] | None = None
    initial_state: WorkspaceState | None = None

    def capture_initial_state(self) -> None:
        self.initial_state = WorkspaceState.capture(self.store)


def _person_payload(query: str) -> dict[str, Any]:
    person = org.find_person(query)
    if person is None:
        return {"ok": True, "found": False}
    return {
        "ok": True,
        "found": True,
        "person": {
            "user_id": person.user_id,
            "name": person.name,
            "email": person.email,
            "role": person.role,
            "department": person.department,
        },
    }


def _lookup_person_tool() -> ExternalTool:
    return ExternalTool(
        name="lookup_person",
        description="Look up one synthetic organisation member by user ID, full name, or first name.",
        parameters=_params({"query": _string("Person name or user ID")}, ["query"]),
        handler=lambda args: _person_payload(str(args["query"])),
    )


def _normalise_people(values: list[Any]) -> list[str]:
    output: list[str] = []
    for value in values:
        person = org.find_person(str(value))
        if person is None:
            raise ValueError(f"unknown person: {value}")
        if person.user_id not in output:
            output.append(person.user_id)
    return output


def _record_payload(record: Any) -> dict[str, Any]:
    return {
        "id": record.id,
        "store": record.store,
        "type": record.type,
        "status": record.status,
        "data": record.data,
    }


def wf1_tools(context: ToolContext) -> list[ExternalTool]:
    if context.workflow != "wf1":
        raise ValueError("WF1 tools require a WF1 context")

    def list_records(args: dict[str, Any]) -> dict[str, Any]:
        store_name = str(args["store"])
        if store_name not in {"events", "submissions"}:
            raise ValueError("store must be events or submissions")
        records = context.store.list(
            store_name,
            record_type=(str(args["record_type"]) if args.get("record_type") else None),
            status=(str(args["status"]) if args.get("status") else None),
        )
        return {"ok": True, "records": [_record_payload(record) for record in records]}

    def create_meeting_draft(args: dict[str, Any]) -> dict[str, Any]:
        source_id = str(args["source_message_id"])
        if source_id not in context.source_message_ids:
            raise ValueError("source_message_id is not present in the visible thread")
        participants = _normalise_people(list(args["participants"]))
        if not participants:
            raise ValueError("at least one participant is required")
        title = str(args["title"]).strip()
        if not title:
            raise ValueError("title is required")
        event_date = args.get("date") or None
        start = args.get("start") or None
        duration = int(args.get("duration_minutes") or 30)
        missing = [name for name, value in (("date", event_date), ("time", start)) if not value]
        record = context.store.create(
            "events",
            "schedule_meeting",
            {
                "title": title,
                "organizer": "alice",
                "participants": participants,
                "date": event_date,
                "start": start,
                "duration_minutes": duration,
                "location": args.get("location") or None,
                "agenda": args.get("agenda") or "",
                "origin": {
                    "workflow": "wf1",
                    "thread_id": context.thread_id or context.case_id,
                    "source_message_ids": [source_id],
                },
                "source_evidence": [{"message_id": source_id, "grounded": True}],
                "missing_required": missing,
                "created_by_external_agent": True,
            },
            status="needs_input" if missing else "pending_review",
        )
        return {"ok": True, "record": _record_payload(record), "missing": missing}

    def create_expense_draft(args: dict[str, Any]) -> dict[str, Any]:
        source_id = str(args["source_message_id"])
        if source_id not in context.source_message_ids:
            raise ValueError("source_message_id is not present in the visible thread")
        attachment_ids = [str(value) for value in args.get("attachment_ids") or []]
        unknown = sorted(set(attachment_ids) - context.attachment_ids)
        if unknown:
            raise ValueError(f"unknown visible attachment IDs: {unknown}")
        employee = org.find_person(str(args["employee_name"]))
        if employee is None:
            raise ValueError("employee_name is not in the directory")
        required_values = {
            "vendor": str(args["vendor"]).strip(),
            "date": str(args["date"]).strip(),
            "currency": str(args["currency"]).strip().upper(),
            "category": str(args["category"]).strip(),
        }
        if not all(required_values.values()):
            raise ValueError("vendor, date, currency and category are required")
        amount = float(args["amount"])
        if amount <= 0:
            raise ValueError("amount must be positive")
        record = context.store.create(
            "submissions",
            "expense_claim",
            {
                "employee_name": employee.name,
                **required_values,
                "amount": amount,
                "business_purpose": str(args.get("business_purpose") or ""),
                "attachment_ids": attachment_ids,
                "origin": {
                    "workflow": "wf1",
                    "thread_id": context.thread_id or context.case_id,
                    "source_message_ids": [source_id],
                },
                "source_evidence": [{"message_id": source_id, "grounded": True}],
                "created_by_external_agent": True,
            },
            status="pending_review",
        )
        return {"ok": True, "record": _record_payload(record)}

    return [
        _lookup_person_tool(),
        ExternalTool(
            name="list_relevant_records",
            description="List existing meeting drafts or expense drafts when needed to avoid duplicate routing.",
            parameters=_params(
                {
                    "store": {"type": STRING, "enum": ["events", "submissions"]},
                    "record_type": _optional_string("Optional record type filter"),
                    "status": _optional_string("Optional status filter"),
                },
                ["store"],
            ),
            handler=list_records,
        ),
        ExternalTool(
            name="create_meeting_draft",
            description=(
                "Create a reviewable downstream meeting draft from one grounded thread message. "
                "This never books a calendar event."
            ),
            parameters=_params(
                {
                    "title": _string("Meeting title"),
                    "participants": _string_array("Participant names or user IDs"),
                    "date": _optional_string("ISO date if explicitly supported, otherwise null"),
                    "start": _optional_string("24-hour start time if explicitly supported, otherwise null"),
                    "duration_minutes": {"type": INTEGER, "minimum": 1},
                    "location": _optional_string("Location if supported, otherwise null"),
                    "agenda": _optional_string("Optional grounded agenda"),
                    "source_message_id": _string("Visible message ID supporting the action"),
                },
                ["title", "participants", "date", "start", "duration_minutes", "location", "agenda", "source_message_id"],
            ),
            handler=create_meeting_draft,
        ),
        ExternalTool(
            name="create_expense_draft",
            description="Create a reviewable downstream expense draft from grounded thread evidence; this does not approve it.",
            parameters=_params(
                {
                    "employee_name": _string("Claimant name or user ID"),
                    "vendor": _string("Vendor"),
                    "date": _string("Expense date in YYYY-MM-DD"),
                    "amount": {"type": NUMBER, "exclusiveMinimum": 0},
                    "currency": _string("Three-letter currency"),
                    "category": _string("Expense category stated or supported by the source"),
                    "business_purpose": _string("Grounded business purpose"),
                    "attachment_ids": _string_array("Visible receipt attachment IDs"),
                    "source_message_id": _string("Visible message ID supporting the action"),
                },
                ["employee_name", "vendor", "date", "amount", "currency", "category", "business_purpose", "attachment_ids", "source_message_id"],
            ),
            handler=create_expense_draft,
        ),
    ]


def _parse_datetime_window(day: str, start: str, end: str) -> tuple[date, str, str]:
    parsed = date.fromisoformat(day)
    datetime.strptime(start, "%H:%M")
    datetime.strptime(end, "%H:%M")
    if end <= start:
        raise ValueError("end must be later than start")
    return parsed, start, end


def wf2_tools(context: ToolContext) -> list[ExternalTool]:
    if context.workflow != "wf2":
        raise ValueError("WF2 tools require a WF2 context")

    def list_rooms(_: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "rooms": [
                {"room_id": room.room_id, "name": room.name, "capacity": room.capacity}
                for room in org.ROOMS
            ],
        }

    def list_events(args: dict[str, Any]) -> dict[str, Any]:
        start_date = date.fromisoformat(str(args["start_date"]))
        end_date = date.fromisoformat(str(args["end_date"]))
        if end_date < start_date:
            raise ValueError("end_date must not precede start_date")
        people = _normalise_people(list(args.get("participants") or []))
        rows = []
        for record in context.store.list("events", status="booked"):
            raw_date = record.data.get("date")
            try:
                event_date = date.fromisoformat(str(raw_date))
            except ValueError:
                continue
            if not start_date <= event_date <= end_date:
                continue
            if people and not set(people) & set(record.data.get("participants") or []):
                continue
            rows.append(_record_payload(record))
        return {"ok": True, "events": rows}

    def inspect_availability(args: dict[str, Any]) -> dict[str, Any]:
        day, start, end = _parse_datetime_window(
            str(args["date"]), str(args["start"]), str(args["end"])
        )
        people = _normalise_people(list(args["participants"]))
        room = args.get("location") or None
        conflicts: list[dict[str, Any]] = []
        for record in context.store.list("events", status="booked"):
            event = record.data
            if event.get("date") != day.isoformat():
                continue
            event_start, event_end = event.get("start"), event.get("end")
            if not event_start or not event_end or not (start < event_end and event_start < end):
                continue
            busy_people = sorted(set(people) & set(event.get("participants") or []))
            existing_room = event.get("location") or event.get("room")
            room_busy = bool(room and existing_room == room)
            if busy_people or room_busy:
                conflicts.append(
                    {
                        "event_id": record.id,
                        "title": event.get("title"),
                        "start": event_start,
                        "end": event_end,
                        "busy_participants": busy_people,
                        "room_busy": room_busy,
                    }
                )
        return {"ok": True, "available": not conflicts, "conflicts": conflicts}

    def create_event(args: dict[str, Any]) -> dict[str, Any]:
        day = date.fromisoformat(str(args["date"]))
        start = str(args["start"])
        duration = int(args["duration_minutes"])
        if duration <= 0:
            raise ValueError("duration_minutes must be positive")
        start_dt = datetime.combine(day, datetime.strptime(start, "%H:%M").time())
        end = (start_dt + timedelta(minutes=duration)).strftime("%H:%M")
        if start < "09:00" or end > "18:00":
            raise ValueError("event must stay within 09:00-18:00 working hours")
        participants = _normalise_people(list(args["participants"]))
        organizer = org.find_person(str(args["organizer"]))
        if organizer is None:
            raise ValueError("organizer is not in the directory")
        if not participants:
            raise ValueError("at least one participant is required")
        location = args.get("location") or None
        if location:
            known = {room.name for room in org.ROOMS} | {
                f"{room.name} room" for room in org.ROOMS
            }
            if location not in known:
                raise ValueError("unknown room location")
        record = context.store.create(
            "events",
            "event",
            {
                "title": str(args["title"]).strip(),
                "organizer": organizer.user_id,
                "participants": participants,
                "date": day.isoformat(),
                "start": start,
                "end": end,
                "duration_minutes": duration,
                "mode": str(args["mode"]),
                "location": location,
                "created_by_external_agent": True,
            },
            status="booked",
        )
        return {"ok": True, "record": _record_payload(record)}

    return [
        _lookup_person_tool(),
        ExternalTool(
            name="list_rooms",
            description="List synthetic meeting rooms and capacities.",
            parameters=_params({}, []),
            handler=list_rooms,
        ),
        ExternalTool(
            name="list_calendar_events",
            description="List booked calendar events in an inclusive date range, optionally filtered by participants.",
            parameters=_params(
                {
                    "start_date": _string("Inclusive ISO start date"),
                    "end_date": _string("Inclusive ISO end date"),
                    "participants": _string_array("Optional participant names or IDs; use an empty list for all"),
                },
                ["start_date", "end_date", "participants"],
            ),
            handler=list_events,
        ),
        ExternalTool(
            name="inspect_availability",
            description="Inspect participant and room conflicts for one proposed time window; this does not choose another slot.",
            parameters=_params(
                {
                    "participants": _string_array("Participant names or IDs"),
                    "date": _string("ISO date"),
                    "start": _string("24-hour start time"),
                    "end": _string("24-hour end time"),
                    "location": _optional_string("Room name or null"),
                },
                ["participants", "date", "start", "end", "location"],
            ),
            handler=inspect_availability,
        ),
        ExternalTool(
            name="create_calendar_event",
            description=(
                "Create one booked event at the exact supplied slot. This validates schema, identity, room name and "
                "working hours but does not check conflicts or select an alternative. Inspect availability first."
            ),
            parameters=_params(
                {
                    "title": _string("Meeting title"),
                    "organizer": _string("Organizer name or user ID"),
                    "participants": _string_array("Complete participant names or IDs"),
                    "date": _string("ISO date"),
                    "start": _string("24-hour start time"),
                    "duration_minutes": {"type": INTEGER, "minimum": 1},
                    "mode": {"type": STRING, "enum": ["virtual", "in_person"]},
                    "location": _optional_string("Known room name or null"),
                },
                ["title", "organizer", "participants", "date", "start", "duration_minutes", "mode", "location"],
            ),
            handler=create_event,
        ),
    ]


EXPENSE_POLICY_TEXT = {
    "currency": "Amounts are stored in the receipt currency and converted to frozen GBP for limits and budgets.",
    "limits_gbp": policy.PER_DIEM,
    "over_limit": "A claim above its category limit must be rejected.",
    "duplicate": "A claim matching an approved vendor, date, amount and currency must be rejected.",
    "budget": "Reject a claim that exceeds the remaining department budget or claimant quota.",
    "non_reimbursable": "Alcohol, tobacco, gambling, gift cards and fines are not reimbursable.",
    "future_date": "A receipt dated after the case date must not be approved without correction.",
    "evidence_disagreement": "A material disagreement between independent receipt reads requires abstention or rejection rather than approval.",
    "roles": "The claimant submits. A different authorised reviewer approves or rejects.",
}


def wf3_tools(context: ToolContext) -> list[ExternalTool]:
    if context.workflow != "wf3" or context.receipt_evidence is None:
        raise ValueError("WF3 tools require a WF3 context with frozen evidence")
    claimant_id = "alice"
    reviewer_id = "chen"

    def read_evidence(_: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "frozen_evidence": context.receipt_evidence}

    def read_policy(_: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "policy": EXPENSE_POLICY_TEXT}

    def inspect_claims(args: dict[str, Any]) -> dict[str, Any]:
        statuses = {str(value) for value in args.get("statuses") or []}
        rows = [
            _record_payload(record)
            for record in context.store.list("submissions", record_type="expense_claim")
            if not statuses or record.status in statuses
        ]
        return {"ok": True, "claims": rows}

    def inspect_budget(_: dict[str, Any]) -> dict[str, Any]:
        claimant = org.find_person(claimant_id)
        assert claimant is not None
        return {
            "ok": True,
            "claimant": claimant.user_id,
            "department": claimant.department,
            "department_remaining_gbp": policy.budget_remaining(claimant.department, context.store),
            "claimant_quota_remaining_gbp": policy.expense_quota_remaining(claimant.user_id, context.store),
        }

    def submit_claim(args: dict[str, Any]) -> dict[str, Any]:
        claimant = org.find_person(claimant_id)
        assert claimant is not None
        required = {
            "vendor": str(args["vendor"]).strip(),
            "date": str(args["date"]).strip(),
            "currency": str(args["currency"]).strip().upper(),
            "category": str(args["category"]).strip(),
            "business_purpose": str(args["business_purpose"]).strip(),
        }
        if not all(required.values()):
            raise ValueError("all required claim fields must be non-empty")
        date.fromisoformat(required["date"])
        amount = float(args["amount"])
        if amount <= 0:
            raise ValueError("amount must be positive")
        if money.rate_for(required["currency"]) is None:
            raise ValueError("currency is unsupported by the frozen conversion table")
        line_items = args.get("line_items") or []
        if not isinstance(line_items, list):
            raise ValueError("line_items must be a list")
        record = context.store.create(
            "submissions",
            "expense_claim",
            {
                "employee_name": claimant.name,
                **required,
                "amount": amount,
                "line_items": line_items,
                "submitted_by": claimant_id,
                "receipt_ref": context.case_id,
                **money.convert(amount, required["currency"]),
                "version": 1,
                "created_by_external_agent": True,
            },
            status="submitted",
        )
        return {"ok": True, "record": _record_payload(record), "delegated_actor": claimant_id}

    def approve_claim(args: dict[str, Any]) -> dict[str, Any]:
        record = context.store.get(str(args["record_id"]))
        if record is None or record.store != "submissions" or record.type != "expense_claim":
            raise ValueError("record is not an expense claim")
        if record.status != "submitted":
            raise ValueError("claim is not awaiting a decision")
        if record.data.get("submitted_by") == reviewer_id:
            raise ValueError("reviewer cannot approve their own claim")
        if not org.is_expense_approver(reviewer_id):
            raise ValueError("delegated reviewer is not authorised")
        updated = context.store.update(
            record.id,
            status="approved",
            data={
                **record.data,
                "version": int(record.data.get("version") or 1) + 1,
                "reviewed_by": reviewer_id,
                "decision_reason": str(args["reason"]),
            },
        )
        return {"ok": True, "record": _record_payload(updated), "delegated_actor": reviewer_id}

    def reject_claim(args: dict[str, Any]) -> dict[str, Any]:
        reason = str(args["reason"]).strip()
        if not reason:
            raise ValueError("a rejection reason is required")
        record = context.store.get(str(args["record_id"]))
        if record is None or record.store != "submissions" or record.type != "expense_claim":
            raise ValueError("record is not an expense claim")
        if record.status != "submitted":
            raise ValueError("claim is not awaiting a decision")
        if record.data.get("submitted_by") == reviewer_id:
            raise ValueError("reviewer cannot decide their own claim")
        if not org.is_expense_approver(reviewer_id):
            raise ValueError("delegated reviewer is not authorised")
        updated = context.store.update(
            record.id,
            status="rejected",
            data={
                **record.data,
                "version": int(record.data.get("version") or 1) + 1,
                "reviewed_by": reviewer_id,
                "decision_reason": reason,
            },
        )
        return {"ok": True, "record": _record_payload(updated), "delegated_actor": reviewer_id}

    line_item_schema = {
        "type": ARRAY,
        "items": {
            "type": OBJECT,
            "properties": {
                "desc": _string("Line-item description"),
                "amount": {"type": NUMBER},
            },
            "required": ["desc", "amount"],
            "additionalProperties": False,
        },
    }
    return [
        ExternalTool(
            name="read_receipt_evidence",
            description="Read the frozen primary and independent critical receipt evidence for this case.",
            parameters=_params({}, []),
            handler=read_evidence,
        ),
        ExternalTool(
            name="read_expense_policy",
            description="Read the uniform synthetic organisation expense policy; this does not decide the current claim.",
            parameters=_params({}, []),
            handler=read_policy,
        ),
        ExternalTool(
            name="inspect_existing_claims",
            description="List existing claims so the agent can compare evidence and reason about duplicates.",
            parameters=_params(
                {"statuses": _string_array("Optional statuses; use an empty list for all")},
                ["statuses"],
            ),
            handler=inspect_claims,
        ),
        ExternalTool(
            name="inspect_budget_state",
            description="Read Alice's remaining department budget and claimant quota without deciding the claim.",
            parameters=_params({}, []),
            handler=inspect_budget,
        ),
        ExternalTool(
            name="submit_expense_claim",
            description=(
                "Submit a claim as delegated claimant Alice. This enforces required schema and supported currency "
                "but performs no duplicate, limit, budget, evidence-reconciliation or policy decision."
            ),
            parameters=_params(
                {
                    "vendor": _string("Vendor from the evidence"),
                    "date": _string("Receipt date YYYY-MM-DD"),
                    "amount": {"type": NUMBER, "exclusiveMinimum": 0},
                    "currency": _string("Receipt currency"),
                    "category": _string("Expense category chosen by the agent"),
                    "business_purpose": _string("Business purpose"),
                    "line_items": line_item_schema,
                },
                ["vendor", "date", "amount", "currency", "category", "business_purpose", "line_items"],
            ),
            handler=submit_claim,
        ),
        ExternalTool(
            name="approve_expense_claim",
            description="Approve one submitted claim as delegated authorised reviewer Chen; no policy decision is computed by this tool.",
            parameters=_params(
                {
                    "record_id": _string("Submitted claim record ID"),
                    "reason": _string("Agent's policy and evidence rationale"),
                },
                ["record_id", "reason"],
            ),
            handler=approve_claim,
        ),
        ExternalTool(
            name="reject_expense_claim",
            description="Reject one submitted claim as delegated authorised reviewer Chen with a reason.",
            parameters=_params(
                {"record_id": _string("Submitted claim record ID"), "reason": _string("Rejection reason")},
                ["record_id", "reason"],
            ),
            handler=reject_claim,
        ),
    ]
