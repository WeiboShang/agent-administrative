"""Validate and seal the immutable dataset/cache manifest for V3.4.2."""
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
MANIFEST = ROOT / "data/eval_datasets/automated_v342_manifest.json"
TRIAGE_DATASET = ROOT / "data/eval_datasets/triage_v34.jsonl"
SCHEDULING_DATASET = ROOT / "data/eval_datasets/scheduling_v341.jsonl"
SCHEDULING_SOURCE = ROOT / "data/eval_datasets/scheduling_realised.jsonl"
RECEIPT_DATASET = ROOT / "data/receipts/synthetic_v2/manifest.jsonl"
RECEIPT_DIR = ROOT / "data/receipts/synthetic_v2"
TRIAGE_CACHE = ROOT / "data/eval_cache/triage_openai-gpt-oss-120b_v34.jsonl"
SCHEDULING_CACHE = ROOT / "data/eval_cache/scheduling_openai-gpt-oss-120b_realised_v33.jsonl"
RECEIPT_CACHE = ROOT / "data/eval_cache/receipts_qwen3.6-27b_synthetic_v2.jsonl"
RECEIPT_CRITICAL_CACHE = ROOT / "data/eval_cache/receipts_qwen3.6-27b_critical_v342.jsonl"


def _rows(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _validate_temporal_contract(rows: list[dict[str, Any]]) -> None:
    for index, row in enumerate(rows):
        meta, gold = row["meta"], row["gold"]
        if gold.get("intent") == "none" or not meta.get("date_phrase"):
            continue
        expected = resolve_relative_date(
            meta["date_phrase"], datetime.fromisoformat(meta["now"])
        )
        if gold.get("date") != expected:
            raise RuntimeError(f"WF2 V3.4.2 temporal gold mismatch at row {index}")
        if meta.get("pre_book") and meta["pre_book"].get("date") != expected:
            raise RuntimeError(f"WF2 V3.4.2 pre-book mismatch at row {index}")


def _validate_critical_cache(
    rows: list[dict[str, Any]], receipts: list[dict[str, Any]]
) -> None:
    images = [row["image"] for row in receipts]
    if [row.get("image") for row in rows] != images:
        raise RuntimeError("V3.4.2 critical cache is not the complete manifest order")
    if len(set(images)) != len(images):
        raise RuntimeError("V3.4.2 receipt manifest contains duplicate image names")
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
            raise RuntimeError(f"invalid V3.4.2 critical cache row: {image}")


def seal(*, overwrite_unsealed: bool = False) -> dict[str, Any]:
    if MANIFEST.exists() and not overwrite_unsealed:
        raise RuntimeError(f"refusing to overwrite V3.4.2 manifest: {MANIFEST}")
    if LLM_MODEL != "openai/gpt-oss-120b" or VISION_MODEL != "qwen/qwen3.6-27b":
        raise RuntimeError("configured models do not match V3.4.2")
    triage = _rows(TRIAGE_DATASET)
    scheduling = _rows(SCHEDULING_DATASET)
    old_scheduling = _rows(SCHEDULING_SOURCE)
    receipts = _rows(RECEIPT_DATASET)
    caches = {
        "triage": _rows(TRIAGE_CACHE),
        "scheduling": _rows(SCHEDULING_CACHE),
        "receipts_primary": _rows(RECEIPT_CACHE),
        "receipts_critical": _rows(RECEIPT_CRITICAL_CACHE),
    }
    expected = {"triage": 45, "scheduling": 70, "receipts": 108}
    if (
        len(triage) != expected["triage"]
        or len(scheduling) != expected["scheduling"]
        or len(receipts) != expected["receipts"]
        or len(caches["triage"]) != expected["triage"]
        or len(caches["scheduling"]) != expected["scheduling"]
        or len(caches["receipts_primary"]) != expected["receipts"]
        or len(caches["receipts_critical"]) != expected["receipts"]
    ):
        raise RuntimeError("incomplete V3.4.2 datasets or caches")
    if [row["input_text"] for row in scheduling] != [
        row["input_text"] for row in old_scheduling
    ]:
        raise RuntimeError("V3.4.2 WF2 source text changed from its frozen cache")
    _validate_temporal_contract(scheduling)
    if {row.get("i") for row in caches["scheduling"]} != set(range(70)):
        raise RuntimeError("V3.4.2 WF2 cache indexes are incomplete or duplicated")
    if {row["image"] for row in caches["receipts_primary"]} != {
        row["image"] for row in receipts
    }:
        raise RuntimeError("V3.4.2 primary receipt cache does not match the manifest")
    _validate_critical_cache(caches["receipts_critical"], receipts)
    triage_by_index = {row.get("i"): row for row in caches["triage"]}
    if set(triage_by_index) != set(range(45)):
        raise RuntimeError("V3.4.2 WF1 cache indexes are incomplete or duplicated")
    for index, source in enumerate(triage):
        cached = triage_by_index[index]
        prompt = PROMPT_MAP["triage"].format(input=source["model_input"], source="chat")
        if (
            cached.get("case_id") != source["case_id"]
            or cached.get("source_sha256") != _sha_text(source["model_input"])
            or cached.get("prompt_sha256") != _sha_text(SYSTEM_PROMPT + "\n" + prompt)
            or "error" in cached.get("x", {})
        ):
            raise RuntimeError(f"invalid V3.4.2 frozen WF1 row {index}")
    payload = {
        "schema_version": "3.4.2",
        "title": "Automated Matched Workflow Evaluation V3.4.2",
        "protocol_status": "sealed_pre_run",
        "synthetic_only": True,
        "mock_backends_only": True,
        "text_model": LLM_MODEL,
        "vision_model": VISION_MODEL,
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
