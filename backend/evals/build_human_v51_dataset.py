"""Build the replacement Human Evaluation V5.1 synthetic case bundle.

Run once before freezing. It archives the exposed V5 protocol artifacts, writes new
reviewer sources/server-only gold, resets only the V5.1 Agent cache, and leaves completed
session/result evidence untouched.
"""
from __future__ import annotations

import json
import random
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DATASETS = ROOT / "data/eval_datasets"
CACHE_DIR = ROOT / "data/eval_cache"
ARCHIVE = ROOT / "data/eval_archive/human_v5_exposed_20260820"


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _receipt_gold() -> dict[str, dict[str, Any]]:
    path = CACHE_DIR / "receipts_qwen3.6-27b_synthetic_v2.jsonl"
    return {row["image"]: row["gold"] for row in map(json.loads, path.read_text(encoding="utf-8").splitlines())}


def build() -> None:
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    for name, base in (
        ("human_v5_manifest.json", DATASETS),
        ("human_v5_sources.json", DATASETS),
        ("human_v5_gold.json", DATASETS),
        ("human_v5_agent_outputs.jsonl", CACHE_DIR),
    ):
        source = base / name
        target = ARCHIVE / name
        if source.exists() and not target.exists():
            shutil.copy2(source, target)

    now = "2026-08-17T09:00:00"
    sources: dict[str, dict[str, Any]] = {
        "pilot-wf1-manual-v51": {"workflow": "wf1", "scenario_now": now, "channel": "chat", "text": "[m1] Dana: Please create two drafts: a 30-minute Zoom check-in with Chen on 2026-08-21 at 10:30, and an expense claim for receipt att-p51-01 from CityCab, GBP 19.20, dated 2026-08-15, for client travel.", "attachments": [{"attachment_id": "att-p51-01", "filename": "pilot-citycab.png", "mime_type": "image/png"}]},
        "pilot-wf1-agent-v51": {"workflow": "wf1", "scenario_now": now, "channel": "chat", "text": "[m1] Fiona: Please arrange a 30-minute Zoom review with Bob tomorrow at 14:00.\n[m2] Fiona: Keep the meeting; no other action is needed.", "attachments": []},
        "pilot-wf2-manual-v51": {"workflow": "wf2", "scenario_now": now, "text": "Please arrange a 30-minute planning call with Chen at 15:00. The date is not agreed.", "setup": {"events": []}},
        "pilot-wf2-agent-v51": {"workflow": "wf2", "scenario_now": now, "text": "Book Dana and Chen in Orion this Thursday at 09:00 for 60 minutes.", "setup": {"events": [{"title": "Existing planning session", "date": "2026-08-20", "start": "09:00", "end": "09:30", "participants": ["dana"], "location": "Orion"}]}},
        "pilot-wf3-manual-v51": {"workflow": "wf3", "claimant_note": "Please reimburse this client-site taxi receipt as travel.", "receipt": {"manifest": "synthetic_v2", "image": "clean_8.png"}, "setup": {"claims": [{"employee_name": "Bob Rivera", "vendor": "CityCab", "date": "2026-06-06", "amount": 11.16, "currency": "GBP", "category": "travel", "business_purpose": "Client travel", "status": "approved"}]}},
        "pilot-wf3-agent-v51": {"workflow": "wf3", "claimant_note": "Please reimburse this client dinner as meals.", "receipt": {"manifest": "synthetic_v2", "image": "over_limit_5.png"}, "setup": {"claims": []}},

        "wf1-v51-p01-a": {"workflow": "wf1", "scenario_now": now, "channel": "email", "text": "[m1] Dana: Please schedule a 45-minute supplier-risk review with Chen and Evan in Lyra on 2026-08-24 at 10:30.", "attachments": []},
        "wf1-v51-p01-b": {"workflow": "wf1", "scenario_now": now, "channel": "chat", "text": "[m1] Fiona: Please book a 30-minute Zoom call with Bob next Thursday at 16:00 about the operations handover.", "attachments": []},
        "wf1-v51-p02-a": {"workflow": "wf1", "scenario_now": now, "channel": "email", "text": "[m1] Alice: Prepare an expense claim for attached receipt att-v51-02a: CityCab, GBP 27.80, dated 2026-08-16, for client travel.", "attachments": [{"attachment_id": "att-v51-02a", "filename": "citycab-v51.png", "mime_type": "image/png"}]},
        "wf1-v51-p02-b": {"workflow": "wf1", "scenario_now": now, "channel": "email", "text": "[m1] Evan: Submit attached invoice att-v51-02b from NorthPeak Hotel, EUR 132.40, dated 2026-08-12, as conference accommodation.", "attachments": [{"attachment_id": "att-v51-02b", "filename": "northpeak-v51.pdf", "mime_type": "application/pdf"}]},
        "wf1-v51-p03-a": {"workflow": "wf1", "scenario_now": now, "channel": "chat", "text": "[m1] Bob: Please arrange a 60-minute forecast review with Chen and Dana next Wednesday. No time has been agreed.", "attachments": []},
        "wf1-v51-p03-b": {"workflow": "wf1", "scenario_now": now, "channel": "email", "text": "[m1] Dana: Please set up a 30-minute Zoom vendor call with Evan at 13:30. The day still needs confirmation.", "attachments": []},
        "wf1-v51-p04-a": {"workflow": "wf1", "scenario_now": now, "channel": "chat", "text": "[m1] Chen: My password reset is complete.\n[m2] Evan: The maintenance message is FYI only.\n[m3] Dana: HR already recorded my leave.", "attachments": []},
        "wf1-v51-p04-b": {"workflow": "wf1", "scenario_now": now, "channel": "email", "text": "[m1] Fiona: Facilities should replace the kitchen light and IT should check the spare monitor. No meeting or reimbursement is requested.", "attachments": []},
        "wf1-v51-p05-a": {"workflow": "wf1", "scenario_now": now, "channel": "chat", "text": "[m1] Alice: Schedule a 45-minute Orion review with Chen on 2026-08-25 at 13:00 about the Q4 budget.\n[m2] Alice: Also prepare an expense claim for receipt att-v51-05a: BrightMart, GBP 31.20, dated 2026-08-14, for workshop supplies.", "attachments": [{"attachment_id": "att-v51-05a", "filename": "brightmart-v51.png", "mime_type": "image/png"}]},
        "wf1-v51-p05-b": {"workflow": "wf1", "scenario_now": now, "channel": "email", "text": "[m1] Evan: Create two drafts: a 30-minute Zoom handover with Dana and Fiona on 2026-08-26 at 15:00, and a claim for receipt att-v51-05b from CityCab, GBP 21.50, dated 2026-08-15, for site travel.", "attachments": [{"attachment_id": "att-v51-05b", "filename": "citycab-site-v51.png", "mime_type": "image/png"}]},
        "wf1-v51-p06-a": {"workflow": "wf1", "scenario_now": now, "channel": "chat", "text": "[m1] Dana: Arrange a 30-minute review with Chen this Wednesday at 10:00.\n[m2] Dana: Change of plan: use next Friday at 15:00 on Zoom instead.", "attachments": []},
        "wf1-v51-p06-b": {"workflow": "wf1", "scenario_now": now, "channel": "chat", "text": "[m1] Alice: Claim receipt att-v51-06b for a GBP 26.00 dinner.\n[m2] Alice: Cancel that expense request; it was personal.\n[m3] Alice: Separately, schedule a 30-minute Zoom audit call with Bob on 2026-08-28 at 14:30.", "attachments": [{"attachment_id": "att-v51-06b", "filename": "personal-v51.png", "mime_type": "image/png"}]},

        "wf2-v51-p01-a": {"workflow": "wf2", "scenario_now": now, "text": "Book Dana and Evan for a 45-minute supplier briefing on 2026-08-24 at 11:00 over Zoom.", "setup": {"events": []}},
        "wf2-v51-p01-b": {"workflow": "wf2", "scenario_now": now, "text": "Please arrange a 30-minute launch review with Chen in Lyra tomorrow at 16:00.", "setup": {"events": []}},
        "wf2-v51-p02-a": {"workflow": "wf2", "scenario_now": now, "text": "Schedule Dana and Fiona in Vega this Wednesday at 13:00 for 45 minutes.", "setup": {"events": []}},
        "wf2-v51-p02-b": {"workflow": "wf2", "scenario_now": now, "text": "Arrange a 60-minute Zoom renewal review with Evan next Friday at 10:00.", "setup": {"events": []}},
        "wf2-v51-p03-a": {"workflow": "wf2", "scenario_now": now, "text": "Please arrange a 30-minute controls call with Chen next Tuesday. The time is not agreed.", "setup": {"events": []}},
        "wf2-v51-p03-b": {"workflow": "wf2", "scenario_now": now, "text": "Set up a 45-minute launch meeting with Dana at 14:30 in Orion. The date is undecided.", "setup": {"events": []}},
        "wf2-v51-p04-a": {"workflow": "wf2", "scenario_now": now, "text": "Could Evan discuss recruitment early next week at 10:30 for 30 minutes on Zoom?", "setup": {"events": []}},
        "wf2-v51-p04-b": {"workflow": "wf2", "scenario_now": now, "text": "Arrange a 30-minute forecast call with someone from Finance this Friday at 13:00.", "setup": {"events": []}},
        "wf2-v51-p05-a": {"workflow": "wf2", "scenario_now": now, "text": "Book Dana and Chen in Lyra this Thursday at 10:00 for 60 minutes.", "setup": {"events": [{"title": "Existing supplier workshop", "date": "2026-08-20", "start": "10:00", "end": "10:30", "participants": ["dana"], "location": "Lyra"}]}},
        "wf2-v51-p05-b": {"workflow": "wf2", "scenario_now": now, "text": "Book Evan and Fiona in Vega this Wednesday at 11:00 for 30 minutes.", "setup": {"events": [{"title": "Existing release review", "date": "2026-08-19", "start": "11:00", "end": "11:30", "participants": ["fiona"], "location": "Vega"}]}},
        "wf2-v51-p06-a": {"workflow": "wf2", "scenario_now": now, "text": "[m1] Dana: Schedule Chen, Evan and me this Wednesday at 14:00 for 45 minutes.\n[m2] Dana: Final choice is next Friday at 10:00 in Orion, with the same people.", "setup": {"events": [{"title": "Existing Evan planning", "date": "2026-08-28", "start": "10:00", "end": "10:30", "participants": ["evan"], "location": "Orion"}]}},
        "wf2-v51-p06-b": {"workflow": "wf2", "scenario_now": now, "text": "[m1] Bob: Arrange a 30-minute Zoom audit call tomorrow at 08:30 with Chen and Fiona.\n[m2] Bob: Final time is tomorrow at 09:30 with the same participants.", "setup": {"events": [{"title": "Existing Chen review", "date": "2026-08-18", "start": "09:30", "end": "10:00", "participants": ["chen"], "location": "Online"}]}},
    }

    receipt_cases = {
        "wf3-v51-p01-a": ("clean_0.png", "Workshop materials; reimburse as supplies.", "supplies"),
        "wf3-v51-p01-b": ("clean_1.png", "Team lunch during planning; reimburse as meals.", "meals"),
        "wf3-v51-p02-a": ("clean_2.png", "Client lunch; reimburse as meals.", "meals"),
        "wf3-v51-p02-b": ("clean_3.png", "Conference breakfast; reimburse as accommodation.", "accommodation"),
        "wf3-v51-p03-a": ("skewed_2.png", "Workshop supplies; verify the skewed receipt.", "supplies"),
        "wf3-v51-p03-b": ("skewed_3.png", "Prototype supplies; verify the skewed receipt.", "supplies"),
        "wf3-v51-p04-a": ("cropped_8.png", "The submitted image is the only evidence.", "other"),
        "wf3-v51-p04-b": ("cropped_10.png", "The submitted image is the only evidence.", "travel"),
        "wf3-v51-p05-a": ("over_limit_0.png", "Please reimburse this client dinner as meals.", "meals"),
        "wf3-v51-p05-b": ("over_limit_1.png", "Please reimburse this recruitment dinner as meals.", "meals"),
        "wf3-v51-p06-a": ("clean_4.png", "Please reimburse this client travel receipt.", "travel"),
        "wf3-v51-p06-b": ("clean_5.png", "Please reimburse this client travel receipt.", "travel"),
    }
    receipt_gold = _receipt_gold()
    for case_id, (image, note, category) in receipt_cases.items():
        setup = {"claims": []}
        if "p06" in case_id:
            g = receipt_gold[image]
            setup = {"claims": [{"employee_name": "Bob Rivera", "vendor": g["vendor"], "date": g["date"], "amount": g["amount"], "currency": g["currency"], "category": category, "business_purpose": "Previously approved", "status": "approved"}]}
        sources[case_id] = {"workflow": "wf3", "claimant_note": note, "receipt": {"manifest": "synthetic_v2", "image": image}, "setup": setup}

    gold: dict[str, dict[str, Any]] = {
        "pilot-wf1-manual-v51": {"expected_decisions": ["route"], "actions": [{"action_type": "schedule_meeting", "hard_fields": {"date": "2026-08-21", "time": "10:30", "participants": ["dana", "chen"], "duration_minutes": 30}}, {"action_type": "expense_claim", "hard_fields": {"vendor": "CityCab", "date": "2026-08-15", "amount": 19.2, "currency": "GBP", "attachment_ids": ["att-p51-01"]}}]},
        "pilot-wf1-agent-v51": {"expected_decisions": ["route"], "actions": [{"action_type": "schedule_meeting", "hard_fields": {"date": "2026-08-18", "time": "14:00", "participants": ["fiona", "bob"], "duration_minutes": 30}}]},
        "pilot-wf2-manual-v51": {"expected_decisions": ["request_information"], "missing_information": ["date"]},
        "pilot-wf2-agent-v51": {"expected_decisions": ["approve"], "hard_fields": {"participants": ["dana", "chen"], "duration_minutes": 60, "location": "Orion"}, "slot_policy": "conflict_free_alternative"},
        "pilot-wf3-manual-v51": {"expected_decisions": ["reject"], "expected_status": "rejected", "critical_fields": {"vendor": "CityCab", "date": "2026-06-06", "amount": 11.16, "currency": "GBP"}, "reason_required": True, "required_flags": ["duplicate"]},
        "pilot-wf3-agent-v51": {"expected_decisions": ["reject"], "expected_status": "rejected", "critical_fields": {"vendor": "Café Aurora", "date": "2026-06-19", "amount": 85.0, "currency": "GBP"}, "reason_required": True, "required_flags": ["over_limit"]},
        "wf1-v51-p01-a": {"expected_decisions": ["route"], "actions": [{"action_type": "schedule_meeting", "hard_fields": {"date": "2026-08-24", "time": "10:30", "participants": ["dana", "chen", "evan"], "duration_minutes": 45, "location": "Lyra"}}]},
        "wf1-v51-p01-b": {"expected_decisions": ["route"], "actions": [{"action_type": "schedule_meeting", "hard_fields": {"date": "2026-08-27", "time": "16:00", "participants": ["fiona", "bob"], "duration_minutes": 30}}]},
        "wf1-v51-p02-a": {"expected_decisions": ["route"], "actions": [{"action_type": "expense_claim", "hard_fields": {"vendor": "CityCab", "date": "2026-08-16", "amount": 27.8, "currency": "GBP", "attachment_ids": ["att-v51-02a"]}}]},
        "wf1-v51-p02-b": {"expected_decisions": ["route"], "actions": [{"action_type": "expense_claim", "hard_fields": {"vendor": "NorthPeak Hotel", "date": "2026-08-12", "amount": 132.4, "currency": "EUR", "attachment_ids": ["att-v51-02b"]}}]},
        "wf1-v51-p03-a": {"expected_decisions": ["route"], "actions": [{"action_type": "schedule_meeting", "hard_fields": {"date": "2026-08-26", "time": None, "participants": ["bob", "chen", "dana"], "duration_minutes": 60}, "must_remain_missing": ["time"]}]},
        "wf1-v51-p03-b": {"expected_decisions": ["route"], "actions": [{"action_type": "schedule_meeting", "hard_fields": {"date": None, "time": "13:30", "participants": ["dana", "evan"], "duration_minutes": 30}, "must_remain_missing": ["date"]}]},
        "wf1-v51-p04-a": {"expected_decisions": ["no_action"], "actions": []},
        "wf1-v51-p04-b": {"expected_decisions": ["no_action"], "actions": []},
        "wf1-v51-p05-a": {"expected_decisions": ["route"], "actions": [{"action_type": "schedule_meeting", "hard_fields": {"date": "2026-08-25", "time": "13:00", "participants": ["alice", "chen"], "duration_minutes": 45, "location": "Orion"}}, {"action_type": "expense_claim", "hard_fields": {"vendor": "BrightMart", "date": "2026-08-14", "amount": 31.2, "currency": "GBP", "attachment_ids": ["att-v51-05a"]}}]},
        "wf1-v51-p05-b": {"expected_decisions": ["route"], "actions": [{"action_type": "schedule_meeting", "hard_fields": {"date": "2026-08-26", "time": "15:00", "participants": ["evan", "dana", "fiona"], "duration_minutes": 30}}, {"action_type": "expense_claim", "hard_fields": {"vendor": "CityCab", "date": "2026-08-15", "amount": 21.5, "currency": "GBP", "attachment_ids": ["att-v51-05b"]}}]},
        "wf1-v51-p06-a": {"expected_decisions": ["route"], "actions": [{"action_type": "schedule_meeting", "hard_fields": {"date": "2026-08-28", "time": "15:00", "participants": ["dana", "chen"], "duration_minutes": 30}, "forbidden_values": {"date": ["2026-08-19"], "time": ["10:00"]}}]},
        "wf1-v51-p06-b": {"expected_decisions": ["route"], "actions": [{"action_type": "schedule_meeting", "hard_fields": {"date": "2026-08-28", "time": "14:30", "participants": ["alice", "bob"], "duration_minutes": 30}}], "forbidden_action_types": ["expense_claim"]},
    }

    wf2_exact = {
        "wf2-v51-p01-a": ("2026-08-24", "11:00", ["dana", "evan"], 45, None),
        "wf2-v51-p01-b": ("2026-08-18", "16:00", ["chen"], 30, "Lyra"),
        "wf2-v51-p02-a": ("2026-08-19", "13:00", ["dana", "fiona"], 45, "Vega"),
        "wf2-v51-p02-b": ("2026-08-28", "10:00", ["evan"], 60, None),
    }
    for case_id, (date, time, people, duration, location) in wf2_exact.items():
        hard = {"date": date, "time": time, "participants": people, "duration_minutes": duration}
        if location:
            hard["location"] = location
        gold[case_id] = {"expected_decisions": ["approve"], "hard_fields": hard, "slot_policy": "exact_requested"}
    gold.update({
        "wf2-v51-p03-a": {"expected_decisions": ["request_information"], "missing_information": ["time"]},
        "wf2-v51-p03-b": {"expected_decisions": ["request_information"], "missing_information": ["date"]},
        "wf2-v51-p04-a": {"expected_decisions": ["request_information"], "missing_information": ["date"]},
        "wf2-v51-p04-b": {"expected_decisions": ["request_information"], "missing_information": ["participants"]},
        "wf2-v51-p05-a": {"expected_decisions": ["approve"], "hard_fields": {"participants": ["dana", "chen"], "duration_minutes": 60, "location": "Lyra"}, "slot_policy": "conflict_free_alternative"},
        "wf2-v51-p05-b": {"expected_decisions": ["reject", "request_information"], "missing_information": ["conflicting_time"]},
        "wf2-v51-p06-a": {"expected_decisions": ["approve"], "hard_fields": {"participants": ["chen", "evan", "dana"], "duration_minutes": 45, "location": "Orion"}, "slot_policy": "conflict_free_alternative"},
        "wf2-v51-p06-b": {"expected_decisions": ["reject", "request_information"], "missing_information": ["conflicting_time"]},
    })
    for case_id, (image, _, _) in receipt_cases.items():
        g = receipt_gold[image]
        critical = {key: g[key] for key in ("vendor", "date", "amount", "currency")}
        if "p04" in case_id:
            gold[case_id] = {"expected_decisions": ["request_information"], "expected_status": "needs_information", "missing_evidence": ["vendor", "date", "currency"]}
        elif "p05" in case_id:
            gold[case_id] = {"expected_decisions": ["reject"], "expected_status": "rejected", "critical_fields": critical, "reason_required": True, "required_flags": ["over_limit"]}
        elif "p06" in case_id:
            gold[case_id] = {"expected_decisions": ["reject"], "expected_status": "rejected", "critical_fields": critical, "reason_required": True, "required_flags": ["duplicate"]}
        else:
            gold[case_id] = {"expected_decisions": ["approve"], "expected_status": "approved", "critical_fields": critical}

    allocations = {
        "wf1": [("manual", 1), ("agent_assisted", 2), ("agent_assisted", 3), ("manual", 4), ("manual", 5), ("agent_assisted", 6), ("manual", 7), ("agent_assisted", 8), ("agent_assisted", 9), ("manual", 10), ("agent_assisted", 11), ("manual", 12)],
        "wf2": [("manual", 1), ("agent_assisted", 2), ("agent_assisted", 3), ("manual", 4), ("manual", 5), ("agent_assisted", 6), ("manual", 7), ("agent_assisted", 8), ("agent_assisted", 9), ("manual", 10), ("agent_assisted", 11), ("manual", 12)],
        "wf3": [("manual", 1), ("agent_assisted", 2), ("agent_assisted", 3), ("manual", 4), ("manual", 5), ("agent_assisted", 6), ("manual", 7), ("agent_assisted", 8), ("agent_assisted", 9), ("manual", 10), ("agent_assisted", 11), ("manual", 12)],
    }
    formal_specs = []
    for workflow, rows in allocations.items():
        for condition, index in rows:
            pair = (index + 1) // 2
            variant = "A" if index % 2 else "B"
            family = "ordinary" if pair <= 2 else "underspecified_degraded" if pair <= 4 else "complex_safety"
            formal_specs.append({"case_id": f"{workflow}-v51-p{pair:02d}-{variant.lower()}", "workflow": workflow, "pair_id": f"{workflow}-v51-p{pair:02d}", "variant": variant, "condition": condition, "scenario_family": family, "pilot": False})
    random.Random(20260821).shuffle(formal_specs)
    for order, spec in enumerate(formal_specs, 1):
        spec["presentation_order"] = order
    pilots = []
    for order, (workflow, condition) in enumerate((("wf1", "manual"), ("wf1", "agent_assisted"), ("wf2", "manual"), ("wf2", "agent_assisted"), ("wf3", "manual"), ("wf3", "agent_assisted")), 1):
        condition_id = "manual" if condition == "manual" else "agent"
        pilots.append({"case_id": f"pilot-{workflow}-{condition_id}-v51", "workflow": workflow, "pair_id": f"pilot-{workflow}-v51", "variant": "A" if condition == "manual" else "B", "condition": condition, "scenario_family": "pilot", "pilot": True, "presentation_order": order})

    manifest = {
        "schema_version": "5.0", "title": "Controlled Single-Reviewer Evaluation V5.1: Manual vs Agent-Assisted",
        "seed": 20260821, "draft_mode": "frozen_actual_agent_replay",
        "text_model": "openai/gpt-oss-120b", "vision_model": "qwen/qwen3.6-27b",
        "reviewers": 1, "formal_case_count": 36, "pilot_case_count": 6,
        "protocol_status": "pre_freeze_implementation", "cases": [*pilots, *formal_specs],
        "frozen_at": None,
    }
    assert set(sources) == set(gold) == {row["case_id"] for row in manifest["cases"]}
    _write(DATASETS / "human_v5_sources.json", {"schema_version": "5.1", "synthetic_only": True, "cases": sources})
    _write(DATASETS / "human_v5_gold.json", {"schema_version": "5.1", "server_only": True, "cases": gold})
    _write(DATASETS / "human_v5_manifest.json", manifest)
    (CACHE_DIR / "human_v5_agent_outputs.jsonl").write_text("", encoding="utf-8")
    print(json.dumps({"status": "built_pre_freeze", "cases": len(sources), "archive": str(ARCHIVE.relative_to(ROOT)), "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}, indent=2))


if __name__ == "__main__":
    build()
