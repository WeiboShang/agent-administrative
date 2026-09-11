"""Gold-free case envelopes and dedicated smoke fixtures for the external agent."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from ..backends.records import RecordStore
from ..fixtures import org
from .external_workbench_tools import ToolContext, wf1_tools, wf2_tools, wf3_tools
from .outcomes_v3 import ExpectedRecord, GoldFinalState

ROOT = Path(__file__).resolve().parents[2]
FORMAL_SOURCE_PATH = ROOT / "data/eval_datasets/external_workbench_sources.jsonl"
FORMAL_MANIFEST_PATH = ROOT / "data/eval_datasets/external_workbench_manifest.json"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ExternalCaseSource:
    case_id: str
    workflow: Literal["wf1", "wf2", "wf3"]
    now: str
    task: str
    source: dict[str, Any]
    initial_records: list[dict[str, Any]] = field(default_factory=list)
    source_sha256: str = ""

    def __post_init__(self) -> None:
        if not self.source_sha256:
            visible = {
                "case_id": self.case_id,
                "workflow": self.workflow,
                "now": self.now,
                "task": self.task,
                "source": self.source,
                "initial_records": self.initial_records,
            }
            object.__setattr__(self, "source_sha256", sha256_json(visible))

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExternalCaseSource":
        return cls(**value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def build_context(self) -> ToolContext:
        now = datetime.fromisoformat(self.now)
        store = RecordStore(":memory:", now_fn=lambda: now.isoformat())
        org.seed_from_org(store, today=now.date())
        for row in self.initial_records:
            store.create(
                str(row["store"]),
                str(row["type"]),
                dict(row["data"]),
                status=str(row["status"]),
            )
        context = ToolContext(
            workflow=self.workflow,
            store=store,
            now=now,
            case_id=self.case_id,
            thread_id=self.source.get("thread_id"),
            source_message_ids={
                str(message["message_id"])
                for message in self.source.get("messages") or []
            },
            attachment_ids={
                str(attachment["attachment_id"])
                for attachment in self.source.get("attachments") or []
            },
            receipt_evidence=self.source.get("receipt_evidence"),
        )
        context.capture_initial_state()
        return context

    def build_tools(self, context: ToolContext) -> list[Any]:
        return {
            "wf1": wf1_tools,
            "wf2": wf2_tools,
            "wf3": wf3_tools,
        }[self.workflow](context)


def _wf1_task(messages: list[dict[str, Any]], attachments: list[dict[str, Any]]) -> str:
    return (
        "Process the administrative thread below. Create downstream meeting or expense "
        "drafts only for concrete, currently supported requests, and ground each draft in "
        "a visible message ID. Do not create drafts for hypothetical, social, cancelled or "
        "FYI-only language. A WF1 meeting action must remain a reviewable draft and must "
        "never book a calendar event. If no supported action exists, leave state unchanged "
        "and give a final response.\n\nMessages:\n"
        + json.dumps(messages, ensure_ascii=False, indent=2)
        + "\n\nAttachments:\n"
        + json.dumps(attachments, ensure_ascii=False, indent=2)
    )


def _wf2_task(request: str) -> str:
    return (
        "Act as the delegated scheduling assistant for organiser Alice. Resolve people and "
        "inspect current calendar state before creating an event. If the request gives a "
        "date but omits a time, choose an available in-hours slot on that date. If the date "
        "is unresolved, the text is not an actionable meeting request, or an explicitly "
        "requested exact slot conflicts, leave state unchanged. Do not choose a different "
        "slot when an exact requested time is unavailable. Otherwise create exactly one "
        "event and then give a final response.\n\nScheduling request:\n"
        + request
    )


def _wf3_task(case_id: str) -> str:
    return (
        "Process the synthetic expense evidence for receipt reference "
        f"{case_id}. Read the frozen evidence and the organisation policy, inspect relevant "
        "claims and budget state, then act under the registered delegation: submit as Alice "
        "and make the final approve/reject decision as authorised reviewer Chen. The tools "
        "do not make the policy decision. If the evidence is not a receipt or is too "
        "conflicted to support a claim, leave state unchanged or abstain rather than invent "
        "fields. Finish with a concise response."
    )


def smoke_cases() -> list[ExternalCaseSource]:
    """Return six non-formal cases that do not copy any sealed source case."""
    now = "2026-08-31T09:00:00"
    wf1_meeting_messages = [
        {
            "message_id": "smoke-wf1-m1",
            "sender": "Dana",
            "body": "Please create a review draft for a 30-minute onboarding check-in with Evan on 4 September 2026 at 10:30.",
            "attachment_ids": [],
        }
    ]
    wf1_fyi_messages = [
        {
            "message_id": "smoke-wf1-fyi-1",
            "sender": "Fiona",
            "body": "For information only: the office plants were watered this morning. No action is needed.",
            "attachment_ids": [],
        }
    ]
    valid_receipt = {
        "primary_read": {
            "vendor": "NorthStar Books",
            "date": "2026-08-28",
            "amount": 42.0,
            "currency": "GBP",
            "category_guess": "supplies",
            "line_items": [{"desc": "Reference manual", "amount": 42.0}],
        },
        "critical_read": {
            "vendor": "NorthStar Books",
            "date": "2026-08-28",
            "amount": 42.0,
            "currency": "GBP",
        },
    }
    non_receipt = {
        "primary_read": {"not_a_receipt": True, "reason": "image is a blank geometric test card"},
        "critical_read": {"not_a_receipt": True},
    }
    return [
        ExternalCaseSource(
            case_id="smoke-wf1-meeting",
            workflow="wf1",
            now=now,
            task=_wf1_task(wf1_meeting_messages, []),
            source={"thread_id": "smoke-thread-meeting", "messages": wf1_meeting_messages, "attachments": []},
        ),
        ExternalCaseSource(
            case_id="smoke-wf1-no-action",
            workflow="wf1",
            now=now,
            task=_wf1_task(wf1_fyi_messages, []),
            source={"thread_id": "smoke-thread-fyi", "messages": wf1_fyi_messages, "attachments": []},
        ),
        ExternalCaseSource(
            case_id="smoke-wf2-available",
            workflow="wf2",
            now=now,
            task=_wf2_task(
                "Please schedule a 30-minute virtual release-readiness meeting with Dana Okoro on 2026-09-04 at 13:30."
            ),
            source={"request": "release-readiness meeting"},
        ),
        ExternalCaseSource(
            case_id="smoke-wf2-no-action",
            workflow="wf2",
            now=now,
            task=_wf2_task("Thanks for the calendar update. No meeting is required."),
            source={"request": "no meeting required"},
        ),
        ExternalCaseSource(
            case_id="smoke-wf3-valid",
            workflow="wf3",
            now=now,
            task=_wf3_task("smoke-receipt-valid"),
            source={"receipt_evidence": valid_receipt},
        ),
        ExternalCaseSource(
            case_id="smoke-wf3-no-action",
            workflow="wf3",
            now=now,
            task=_wf3_task("smoke-not-a-receipt"),
            source={"receipt_evidence": non_receipt},
        ),
    ]


def smoke_gold(case_id: str) -> GoldFinalState:
    """Post-execution-only contracts for the dedicated smoke fixtures."""
    contracts: dict[str, GoldFinalState] = {
        "smoke-wf1-meeting": GoldFinalState(
            required_records=[
                ExpectedRecord(
                    store="events",
                    type="schedule_meeting",
                    data={
                        "origin": {
                            "workflow": "wf1",
                            "thread_id": "smoke-thread-meeting",
                            "source_message_ids": ["smoke-wf1-m1"],
                        }
                    },
                    exact_data={
                        "participants": ["evan"],
                        "date": "2026-09-04",
                        "start": "10:30",
                    },
                )
            ]
        ),
        "smoke-wf1-no-action": GoldFinalState(),
        "smoke-wf2-available": GoldFinalState(
            required_records=[
                ExpectedRecord(
                    store="events",
                    type="event",
                    status="booked",
                    data={
                        "organizer": "alice",
                        "date": "2026-09-04",
                        "start": "13:30",
                        "end": "14:00",
                        "duration_minutes": 30,
                        "mode": "virtual",
                    },
                    exact_data={"participants": ["dana"]},
                )
            ]
        ),
        "smoke-wf2-no-action": GoldFinalState(),
        "smoke-wf3-valid": GoldFinalState(
            required_records=[
                ExpectedRecord(
                    store="submissions",
                    type="expense_claim",
                    status="approved",
                    data={
                        "vendor": "NorthStar Books",
                        "date": "2026-08-28",
                        "amount": 42.0,
                        "currency": "GBP",
                        "category": "supplies",
                    },
                )
            ]
        ),
        "smoke-wf3-no-action": GoldFinalState(),
    }
    return contracts[case_id]


def load_formal_sources(path: Path = FORMAL_SOURCE_PATH) -> list[ExternalCaseSource]:
    return [
        ExternalCaseSource.from_dict(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
