"""Validate and seal the immutable dataset/cache manifest for V3.4.3."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..agent.prompts import PROMPT_MAP, SYSTEM_PROMPT
from ..agent.vision_extract import CRITICAL_RECEIPT_PROMPT, VISION_SYSTEM
from ..config import LLM_MODEL, VISION_MODEL
from ..workflows.scheduling import resolve_relative_date
from .provenance_v34 import file_sha256, source_version

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data/eval_datasets/automated_v343_manifest.json"
TRIAGE_DATASET = ROOT / "data/eval_datasets/triage_v34.jsonl"
SCHEDULING_DATASET = ROOT / "data/eval_datasets/scheduling_v343.jsonl"
SCHEDULING_SOURCE = ROOT / "data/eval_datasets/scheduling_v341.jsonl"
RECEIPT_DATASET = ROOT / "data/receipts/synthetic_v2/manifest.jsonl"
RECEIPT_DIR = ROOT / "data/receipts/synthetic_v2"
TRIAGE_CACHE = ROOT / "data/eval_cache/triage_openai-gpt-oss-120b_v34.jsonl"
SCHEDULING_CACHE = ROOT / "data/eval_cache/scheduling_openai-gpt-oss-120b_v343.jsonl"
RECEIPT_CACHE = ROOT / "data/eval_cache/receipts_qwen3.6-27b_synthetic_v2.jsonl"
RECEIPT_CRITICAL_CACHE = (
    ROOT / "data/eval_cache/receipts_qwen3.6-27b_critical_v342.jsonl"
)
REPAIRED_INDEX = 30


def _rows(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_wf2_source_and_gold(
    rows: list[dict[str, Any]], prior: list[dict[str, Any]]
) -> None:
    if len(rows) != 70 or len(prior) != 70:
        raise RuntimeError("V3.4.3 WF2 dataset is incomplete")
    changed = []
    for index, (current, old) in enumerate(zip(rows, prior)):
        if current["gold"] != old["gold"]:
            raise RuntimeError(f"V3.4.3 WF2 gold changed at row {index}")
        old_meta = dict(old["meta"])
        current_meta = dict(current["meta"])
        repair = current_meta.pop("source_alignment_repair", None)
        if current_meta != old_meta:
            raise RuntimeError(f"V3.4.3 WF2 metadata changed at row {index}")
        if current["input_text"] != old["input_text"]:
            changed.append(index)
            if repair != "completed_truncated_topic":
                raise RuntimeError("WF2 source repair lacks explicit provenance")
        elif repair is not None:
            raise RuntimeError(f"unexpected WF2 source repair marker at row {index}")
    if changed != [REPAIRED_INDEX]:
        raise RuntimeError(f"expected only WF2 row 30 to change, found {changed}")
    repaired = rows[REPAIRED_INDEX]
    if "sprint review" not in repaired["input_text"].lower():
        raise RuntimeError("WF2 repaired source still omits the gold topic")


def _validate_temporal_contract(rows: list[dict[str, Any]]) -> None:
    for index, row in enumerate(rows):
        meta, gold = row["meta"], row["gold"]
        if gold.get("intent") == "none" or not meta.get("date_phrase"):
            continue
        expected = resolve_relative_date(
            meta["date_phrase"], datetime.fromisoformat(meta["now"])
        )
        if gold.get("date") != expected:
            raise RuntimeError(f"WF2 V3.4.3 temporal gold mismatch at row {index}")
        if meta.get("pre_book") and meta["pre_book"].get("date") != expected:
            raise RuntimeError(f"WF2 V3.4.3 pre-book mismatch at row {index}")


def _validate_text_cache(
    rows: list[dict[str, Any]], sources: list[str], workflow: str
) -> None:
    by_index = {row.get("i"): row for row in rows}
    if set(by_index) != set(range(len(sources))):
        raise RuntimeError(f"V3.4.3 {workflow} cache indexes are incomplete")
    for index, source in enumerate(sources):
        cached = by_index[index]
        prompt = PROMPT_MAP[workflow].format(input=source, source="chat")
        if (
            cached.get("model") != LLM_MODEL
            or cached.get("source_sha256") != _sha_text(source)
            or cached.get("prompt_sha256") != _sha_text(SYSTEM_PROMPT + "\n" + prompt)
            or "error" in cached.get("x", {})
        ):
            raise RuntimeError(f"invalid V3.4.3 frozen {workflow} row {index}")


def _validate_critical_cache(
    rows: list[dict[str, Any]], receipts: list[dict[str, Any]]
) -> None:
    images = [row["image"] for row in receipts]
    if [row.get("image") for row in rows] != images or len(set(images)) != len(images):
        raise RuntimeError("V3.4.3 WF3 critical cache/manifest mismatch")
    prompt_sha = _sha_text(VISION_SYSTEM + "\n" + CRITICAL_RECEIPT_PROMPT)
    for row in rows:
        image = row["image"]
        image_sha = hashlib.sha256((RECEIPT_DIR / image).read_bytes()).hexdigest()
        if (
            row.get("schema_version") != "3.4.2"
            or row.get("model") != VISION_MODEL
            or row.get("prompt_sha256") != prompt_sha
            or row.get("image_sha256") != image_sha
            or not isinstance(row.get("critical_read"), dict)
        ):
            raise RuntimeError(f"invalid frozen WF3 critical row: {image}")


def seal() -> dict[str, Any]:
    if MANIFEST.exists():
        raise RuntimeError(f"refusing to overwrite V3.4.3 manifest: {MANIFEST}")
    if LLM_MODEL != "openai/gpt-oss-120b" or VISION_MODEL != "qwen/qwen3.6-27b":
        raise RuntimeError("configured models do not match V3.4.3")
    triage = _rows(TRIAGE_DATASET)
    scheduling = _rows(SCHEDULING_DATASET)
    prior_scheduling = _rows(SCHEDULING_SOURCE)
    receipts = _rows(RECEIPT_DATASET)
    caches = {
        "triage": _rows(TRIAGE_CACHE),
        "scheduling": _rows(SCHEDULING_CACHE),
        "receipts_primary": _rows(RECEIPT_CACHE),
        "receipts_critical": _rows(RECEIPT_CRITICAL_CACHE),
    }
    expected = {"triage": 45, "scheduling": 70, "receipts": 108}
    actual = {
        "triage": len(triage),
        "scheduling": len(scheduling),
        "receipts": len(receipts),
    }
    if actual != expected or any(
        len(caches[name]) != expected[workflow]
        for name, workflow in (
            ("triage", "triage"),
            ("scheduling", "scheduling"),
            ("receipts_primary", "receipts"),
            ("receipts_critical", "receipts"),
        )
    ):
        raise RuntimeError("incomplete V3.4.3 datasets or caches")
    _validate_wf2_source_and_gold(scheduling, prior_scheduling)
    _validate_temporal_contract(scheduling)
    _validate_text_cache(
        caches["triage"], [row["model_input"] for row in triage], "triage"
    )
    _validate_text_cache(
        caches["scheduling"], [row["input_text"] for row in scheduling], "scheduling"
    )
    if {row["image"] for row in caches["receipts_primary"]} != {
        row["image"] for row in receipts
    }:
        raise RuntimeError("V3.4.3 primary receipt cache/manifest mismatch")
    _validate_critical_cache(caches["receipts_critical"], receipts)
    payload = {
        "schema_version": "3.4.3",
        "title": "Automated Matched Workflow Evaluation V3.4.3",
        "protocol_status": "sealed_pre_run",
        "synthetic_only": True,
        "mock_backends_only": True,
        "text_model": LLM_MODEL,
        "vision_model": VISION_MODEL,
        "wf2_repair": {
            "changed_source_indexes": [REPAIRED_INDEX],
            "changed_gold_indexes": [],
            "fresh_model_outputs": [REPAIRED_INDEX],
            "reused_model_outputs": 69,
            "task_defining_fields": [
                "date",
                "start_if_explicit",
                "duration_minutes",
                "participants",
                "mode",
            ],
        },
        "wf3_critical_read_protocol": {
            "coverage": "all_108_receipts",
            "fields": ["vendor", "date", "amount", "currency"],
            "reasoning": "provider_default",
            "gold_or_meta_available_to_model": False,
            "prompt_sha256": _sha_text(VISION_SYSTEM + "\n" + CRITICAL_RECEIPT_PROMPT),
        },
        "unique_case_counts": expected,
        "paired_execution_count": 2 * sum(expected.values()),
        "oracle_labels_used_during_execution": False,
        "source_version": source_version(),
        "sealed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset_sha256": {
            "triage": file_sha256(TRIAGE_DATASET),
            "scheduling": file_sha256(SCHEDULING_DATASET),
            "receipts": file_sha256(RECEIPT_DATASET),
        },
        "cache_sha256": {
            "triage": file_sha256(TRIAGE_CACHE),
            "scheduling": file_sha256(SCHEDULING_CACHE),
            "receipts_primary": file_sha256(RECEIPT_CACHE),
            "receipts_critical": file_sha256(RECEIPT_CRITICAL_CACHE),
        },
    }
    MANIFEST.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


if __name__ == "__main__":
    print(json.dumps(seal(), ensure_ascii=False, indent=2))
