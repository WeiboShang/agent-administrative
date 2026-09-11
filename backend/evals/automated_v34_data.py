"""Build the sealed-input WF1 dataset for Automated Evaluation V3.4.

V3.3 remains immutable.  V3.4 retains its 33 still-valid meeting/noise/abstention cases
and replaces the six retired leave-only plus six meeting+leave cases with supported
expense-only and genuine meeting+expense cases.  The frozen model input is produced by
the same ``normalise_messages`` + ``triage_text`` contract as the Inbox router.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ..fixtures import org
from ..workflows.scheduling import resolve_relative_date
from ..workflows.thread_intake import normalise_attachments, normalise_messages, triage_text
from .realiser import load_thread_cases
from .triage_data import make_thread_case

ROOT = Path(__file__).resolve().parents[2]
V33_DATASET = ROOT / "data/eval_datasets/triage_realised.jsonl"
V34_DATASET = ROOT / "data/eval_datasets/triage_v34.jsonl"
NOW = datetime(2026, 6, 30, 9, 0)

_MEETING = re.compile(
    r"(?P<title>.+?) next (?P<weekday>Monday|Tuesday|Wednesday|Thursday|Friday) "
    r"at (?P<time>\d{2}:\d{2})\? (?P<names>.+?) too\.$",
    re.IGNORECASE,
)


def _messages(raw_text: str, *, thread_id: str) -> list[dict[str, Any]]:
    return normalise_messages({"raw_text": raw_text}, thread_id=thread_id)


def _gold_actions(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for message in messages:
        body = message["body"]
        if match := _MEETING.search(body):
            participant_ids = ["alice"]
            for name in re.split(r",\s*|\s+and\s+", match.group("names")):
                person = org.find_person(name.strip())
                if person and person.user_id not in participant_ids:
                    participant_ids.append(person.user_id)
            actions.append({
                "action_type": "schedule_meeting",
                "source_message_id": message["message_id"],
                "critical_fields": {
                    "date": resolve_relative_date(
                        f"next {match.group('weekday')}", NOW
                    ),
                    "start": match.group("time"),
                    "participants": participant_ids,
                },
            })
        if "Please reimburse it; the receipt is attached." in body:
            actions.append({
                "action_type": "expense_claim",
                "source_message_id": message["message_id"],
                "critical_fields": {
                    "employee_name": "Alice",
                    "date": "2026-06-29",
                    "amount": 48.20,
                    "currency": "GBP",
                    "category": "travel",
                },
            })
    return actions


def build_rows() -> list[dict[str, Any]]:
    old = load_thread_cases(str(V33_DATASET))
    retained = [case for case in old if case.meta["tier"] not in {"leave", "multi"}]
    cases = [
        *old[:6],
        *(make_thread_case("expense", 3400 + i) for i in range(6)),
        *(make_thread_case("multi", 3500 + i) for i in range(6)),
        *[case for case in retained if case.meta["tier"] != "meeting"],
    ]
    if len(cases) != 45:
        raise RuntimeError(f"expected 45 WF1 cases, got {len(cases)}")

    rows = []
    for index, case in enumerate(cases):
        thread_id = f"eval-v34-thread-{index:04d}"
        messages = _messages(case.raw_text, thread_id=thread_id)
        attachments: list[dict[str, Any]] = []
        for message in messages:
            if "receipt is attached" not in message["body"]:
                continue
            attachment_id = f"att-wf1-v34-{index:04d}-001"
            message["attachment_ids"] = [attachment_id]
            attachments.append({
                "attachment_id": attachment_id,
                "filename": f"synthetic-receipt-{index:04d}.png",
                "mime_type": "image/png",
                "byte_size": 1024,
                "evidence_type": "receipt",
            })
        attachments = normalise_attachments(attachments, thread_id=thread_id)
        data = {"messages": messages, "detected_actions": []}
        rows.append({
            "schema_version": "3.4",
            "case_id": f"wf1-{index:04d}",
            "thread_id": thread_id,
            "raw_text": case.raw_text,
            "messages": messages,
            "attachments": attachments,
            "model_input": triage_text(data),
            "gold": {"actions": _gold_actions(messages)},
            "meta": {"tier": case.meta["tier"], "synthetic": True},
        })
    return rows


def write_dataset(path: Path = V34_DATASET) -> Path:
    rows = build_rows()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    print(write_dataset())
