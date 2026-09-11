"""Validate and seal the immutable dataset/cache manifest for V3.4.1."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..agent.prompts import PROMPT_MAP, SYSTEM_PROMPT
from ..agent.vision_extract import _CATEGORIES
from ..config import LLM_MODEL, VISION_MODEL
from ..workflows.scheduling import resolve_relative_date
from .provenance_v34 import file_sha256, source_version

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data/eval_datasets/automated_v341_manifest.json"
TRIAGE_DATASET = ROOT / "data/eval_datasets/triage_v34.jsonl"
SCHEDULING_DATASET = ROOT / "data/eval_datasets/scheduling_v341.jsonl"
SCHEDULING_SOURCE = ROOT / "data/eval_datasets/scheduling_realised.jsonl"
RECEIPT_DATASET = ROOT / "data/receipts/synthetic_v2/manifest.jsonl"
TRIAGE_CACHE = ROOT / "data/eval_cache/triage_openai-gpt-oss-120b_v34.jsonl"
SCHEDULING_CACHE = ROOT / "data/eval_cache/scheduling_openai-gpt-oss-120b_realised_v33.jsonl"
RECEIPT_CACHE = ROOT / "data/eval_cache/receipts_qwen3.6-27b_synthetic_v2.jsonl"


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _validate_temporal_contract(rows: list[dict[str, Any]]) -> None:
    for index, row in enumerate(rows):
        meta, gold = row["meta"], row["gold"]
        if gold.get("intent") == "none" or not meta.get("date_phrase"):
            continue
        expected = resolve_relative_date(
            meta["date_phrase"], datetime.fromisoformat(meta["now"])
        )
        if gold.get("date") != expected:
            raise RuntimeError(f"WF2 V5 temporal gold mismatch at row {index}")
        if meta.get("pre_book") and meta["pre_book"].get("date") != expected:
            raise RuntimeError(f"WF2 pre-book temporal mismatch at row {index}")


def seal(*, overwrite_unsealed: bool = False) -> dict[str, Any]:
    if MANIFEST.exists() and not overwrite_unsealed:
        raise RuntimeError(f"refusing to overwrite V3.4.1 manifest: {MANIFEST}")
    if LLM_MODEL != "openai/gpt-oss-120b" or VISION_MODEL != "qwen/qwen3.6-27b":
        raise RuntimeError("configured models do not match V3.4.1")
    triage, scheduling, old_scheduling, receipts = (
        _rows(TRIAGE_DATASET), _rows(SCHEDULING_DATASET),
        _rows(SCHEDULING_SOURCE), _rows(RECEIPT_DATASET),
    )
    caches = {
        "triage": _rows(TRIAGE_CACHE), "scheduling": _rows(SCHEDULING_CACHE),
        "receipts": _rows(RECEIPT_CACHE),
    }
    expected = {"triage": 45, "scheduling": 70, "receipts": 108}
    counts = {name: len(rows) for name, rows in caches.items()}
    if counts != expected or len(triage) != 45 or len(scheduling) != 70 or len(receipts) != 108:
        raise RuntimeError(f"incomplete V3.4.1 inputs: expected {expected}, got {counts}")
    if [row["input_text"] for row in scheduling] != [row["input_text"] for row in old_scheduling]:
        raise RuntimeError("V3.4.1 WF2 source text changed; frozen cache is not reusable")
    _validate_temporal_contract(scheduling)
    if {row.get("i") for row in caches["scheduling"]} != set(range(70)):
        raise RuntimeError("V3.4.1 WF2 cache indexes are incomplete or duplicated")
    if {row["image"] for row in caches["receipts"]} != {row["image"] for row in receipts}:
        raise RuntimeError("V3.4.1 WF3 cache does not match the receipt manifest")
    categories = {
        row["gold"].get("category") for row in receipts
        if row["meta"].get("is_receipt", True)
    }
    if not categories <= _CATEGORIES:
        raise RuntimeError(f"WF3 gold categories are outside the current schema: {categories - _CATEGORIES}")
    triage_by_index = {row.get("i"): row for row in caches["triage"]}
    if set(triage_by_index) != set(range(45)):
        raise RuntimeError("V3.4.1 WF1 cache indexes are incomplete or duplicated")
    for index, source in enumerate(triage):
        cached = triage_by_index[index]
        prompt = PROMPT_MAP["triage"].format(input=source["model_input"], source="chat")
        if (
            cached.get("case_id") != source["case_id"]
            or cached.get("source_sha256") != _sha_text(source["model_input"])
            or cached.get("prompt_sha256") != _sha_text(SYSTEM_PROMPT + "\n" + prompt)
            or "error" in cached.get("x", {})
        ):
            raise RuntimeError(f"invalid V3.4.1 frozen WF1 row {index}")
    payload = {
        "schema_version": "3.4.1",
        "title": "Automated Matched Workflow Evaluation V3.4.1",
        "protocol_status": "sealed_pre_run",
        "synthetic_only": True,
        "mock_backends_only": True,
        "text_model": LLM_MODEL,
        "vision_model": VISION_MODEL,
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
            "receipts": file_sha256(RECEIPT_CACHE),
        },
    }
    MANIFEST.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


if __name__ == "__main__":
    print(json.dumps(seal(), ensure_ascii=False, indent=2))
