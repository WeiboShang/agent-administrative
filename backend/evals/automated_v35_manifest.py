"""Validate and seal the immutable WF2 V3.5 evaluation manifest."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..agent.prompts import PROMPT_MAP, SYSTEM_PROMPT
from ..config import LLM_MODEL
from .automated_v35_data import MANUAL_RELATIVE_DATES
from .provenance_v34 import file_sha256, source_version
from .wf2_v35_oracle import add_minutes, conflict_types

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data/eval_datasets/automated_v35_manifest.json"
SCHEDULING_DATASET = ROOT / "data/eval_datasets/scheduling_v35.jsonl"
SCHEDULING_SOURCE = ROOT / "data/eval_datasets/scheduling_v343.jsonl"
SCHEDULING_CACHE = (
    ROOT / "data/eval_cache/scheduling_openai-gpt-oss-120b_v343.jsonl"
)
MECHANISM_DATASET = ROOT / "data/eval_datasets/wf2_mechanism_v35.jsonl"
TEMPORAL_CONTRACT = ROOT / "data/eval_datasets/wf2_temporal_contract_v35.json"
DATE_AUDIT = ROOT / "data/eval_datasets/wf2_date_contract_audit_v35.json"
SCORER_FILES = [
    ROOT / "backend/evals/outcomes_v3.py",
    ROOT / "backend/evals/outcome_adapters_v35.py",
    ROOT / "backend/evals/wf2_v35_oracle.py",
    ROOT / "backend/evals/wf2_mechanism_v35.py",
]
INDEPENDENCE_FILES = [
    ROOT / "backend/evals/automated_v35_data.py",
    ROOT / "backend/evals/wf2_v35_oracle.py",
]


def _rows(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _bundle_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(ROOT)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _validate_independence() -> None:
    for path in INDEPENDENCE_FILES:
        text = path.read_text(encoding="utf-8")
        if "resolve_relative_date" in text or "recommend_candidates" in text:
            raise RuntimeError(
                f"V3.5 independent gold/oracle references production logic: {path}"
            )
    oracle_text = (ROOT / "backend/evals/wf2_v35_oracle.py").read_text(
        encoding="utf-8"
    )
    if "workflows.scheduling" in oracle_text:
        raise RuntimeError("V3.5 oracle imports production scheduling code")


def _validate_scheduling(rows: list[dict[str, Any]]) -> None:
    source = _rows(SCHEDULING_SOURCE)
    if len(rows) != 70 or len(source) != 70:
        raise RuntimeError("V3.5 WF2-E2E-70 is incomplete")
    allowed_new = {
        "organizer", "location", "accepted_location_values"
    }
    for index, (current, prior) in enumerate(zip(rows, source)):
        if current["input_text"] != prior["input_text"] or current["meta"] != prior["meta"]:
            raise RuntimeError(f"V3.5 changed frozen source/meta at row {index}")
        stripped = {
            key: value
            for key, value in current["gold"].items()
            if key not in allowed_new
        }
        if stripped != prior["gold"]:
            raise RuntimeError(f"V3.5 changed pre-existing gold at row {index}")
        gold, meta = current["gold"], current["meta"]
        phrase = meta.get("date_phrase")
        if phrase in MANUAL_RELATIVE_DATES and gold.get("date"):
            if gold["date"] != MANUAL_RELATIVE_DATES[phrase]:
                raise RuntimeError(f"manual date mismatch at row {index}")
        elif meta.get("date_style") == "explicit" and gold.get("date"):
            if phrase != gold["date"]:
                raise RuntimeError(f"literal explicit date mismatch at row {index}")
        elif meta.get("date_style") == "vague" and gold.get("date") is not None:
            raise RuntimeError(f"vague date is not null at row {index}")
        if gold.get("intent") == "schedule_meeting" and gold.get("date"):
            if gold.get("organizer") != "alice":
                raise RuntimeError(f"missing V3.5 organiser gold at row {index}")
            if gold.get("mode") == "in_person":
                if gold.get("location") != "Orion" or not gold.get(
                    "accepted_location_values"
                ):
                    raise RuntimeError(f"missing V3.5 room gold at row {index}")


def _validate_cache(rows: list[dict[str, Any]], sources: list[dict[str, Any]]) -> None:
    by_index = {row.get("i"): row for row in rows}
    if set(by_index) != set(range(70)):
        raise RuntimeError("V3.5 frozen cache indexes are incomplete")
    for index, source in enumerate(sources):
        cached = by_index[index]
        prompt = PROMPT_MAP["scheduling"].format(
            input=source["input_text"], source="chat"
        )
        if (
            cached.get("model") != LLM_MODEL
            or cached.get("source_sha256") != _sha_text(source["input_text"])
            or cached.get("prompt_sha256")
            != _sha_text(SYSTEM_PROMPT + "\n" + prompt)
            or "error" in cached.get("x", {})
        ):
            raise RuntimeError(f"invalid V3.5 frozen cache row {index}")


def _validate_mechanism(rows: list[dict[str, Any]]) -> None:
    groups = {name: sum(row.get("group") == name for row in rows) for name in ("conflict", "top3")}
    if len(rows) != 20 or groups != {"conflict": 12, "top3": 8}:
        raise RuntimeError(f"invalid WF2-MECH-20 composition: {groups}")
    if len({row.get("case_id") for row in rows}) != 20:
        raise RuntimeError("duplicate WF2 mechanism case IDs")
    for row in rows:
        if row.get("group") != "conflict":
            continue
        spec = row["spec"]
        expected = sorted(row["gold"]["expected_requested_conflicts"])
        actual = conflict_types(
            participants=spec["participants"],
            organizer=row["actor"],
            day=spec["date_window"]["start"],
            start=spec["exact_time"],
            end=add_minutes(spec["exact_time"], spec["duration_minutes"]),
            location=spec.get("location"),
            existing_events=row.get("seed_events") or [],
        )
        if actual != expected:
            raise RuntimeError(
                f"independent mechanism gold mismatch for {row['case_id']}: "
                f"{actual} != {expected}"
            )


def validate() -> dict[str, Any]:
    if LLM_MODEL != "openai/gpt-oss-120b":
        raise RuntimeError("configured text model does not match V3.5 frozen cache")
    _validate_independence()
    scheduling = _rows(SCHEDULING_DATASET)
    cache = _rows(SCHEDULING_CACHE)
    mechanism = _rows(MECHANISM_DATASET)
    _validate_scheduling(scheduling)
    _validate_cache(cache, scheduling)
    _validate_mechanism(mechanism)
    temporal = json.loads(TEMPORAL_CONTRACT.read_text(encoding="utf-8"))
    audit = json.loads(DATE_AUDIT.read_text(encoding="utf-8"))
    if temporal.get("manual_relative_date_table") != MANUAL_RELATIVE_DATES:
        raise RuntimeError("V3.5 temporal contract table changed")
    if len(audit.get("rows") or []) != 15:
        raise RuntimeError("V3.5 date-contract audit must contain 15 rows")
    return {
        "schema_version": "3.5",
        "title": "WF2 Strict Final-State and Mechanism Evaluation V3.5",
        "protocol_status": "sealed_pre_run",
        "synthetic_only": True,
        "mock_backends_only": True,
        "text_model": LLM_MODEL,
        "primary_suite": "WF2-E2E-70",
        "secondary_suite": "WF2-MECH-20",
        "unique_case_counts": {"wf2_e2e": 70, "wf2_mechanism": 20},
        "paired_e2e_execution_count": 140,
        "oracle_labels_used_during_e2e_execution": False,
        "mechanism_headline_eligible": False,
        "source_version": source_version(),
        "dataset_sha256": {
            "scheduling": file_sha256(SCHEDULING_DATASET),
            "mechanism": file_sha256(MECHANISM_DATASET),
            "temporal_contract": file_sha256(TEMPORAL_CONTRACT),
            "date_audit": file_sha256(DATE_AUDIT),
        },
        "cache_sha256": file_sha256(SCHEDULING_CACHE),
        "scorer_sha256": _bundle_hash(SCORER_FILES),
        "gold_independence_sha256": _bundle_hash(INDEPENDENCE_FILES),
        "task_defining_fields": [
            "organizer",
            "participants_exact_set",
            "date",
            "start_or_independent_feasible_set",
            "end",
            "duration_minutes",
            "mode",
            "required_room",
            "booked_status",
            "no_extra_mutation",
        ],
        "excluded_claims": [
            "update_cancel_reuse_effectiveness",
            "recurrence",
            "large_participant_sets",
            "room_capacity_or_equipment",
            "preference_ranking_quality",
            "external_validity",
            "title_or_agenda_semantics",
        ],
    }


def seal() -> dict[str, Any]:
    if MANIFEST.exists():
        raise RuntimeError(f"refusing to overwrite V3.5 manifest: {MANIFEST}")
    payload = validate()
    payload["sealed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    MANIFEST.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


if __name__ == "__main__":
    print(json.dumps(seal(), ensure_ascii=False, indent=2))
