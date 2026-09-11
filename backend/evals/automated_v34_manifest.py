"""Validate and seal the immutable dataset/cache manifest for V3.4."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..agent.prompts import PROMPT_MAP, SYSTEM_PROMPT
from ..config import LLM_MODEL, VISION_MODEL
from .provenance_v34 import file_sha256, source_version

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data/eval_datasets/automated_v34_manifest.json"
TRIAGE_DATASET = ROOT / "data/eval_datasets/triage_v34.jsonl"
SCHEDULING_DATASET = ROOT / "data/eval_datasets/scheduling_realised.jsonl"
RECEIPT_DATASET = ROOT / "data/receipts/synthetic_v2/manifest.jsonl"
TRIAGE_CACHE = ROOT / "data/eval_cache/triage_openai-gpt-oss-120b_v34.jsonl"
SCHEDULING_CACHE = ROOT / "data/eval_cache/scheduling_openai-gpt-oss-120b_realised_v33.jsonl"
RECEIPT_CACHE = ROOT / "data/eval_cache/receipts_qwen3.6-27b_synthetic_v2.jsonl"


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _sha_text(value: str) -> str:
    import hashlib
    return hashlib.sha256(value.encode()).hexdigest()


def seal(*, overwrite_unsealed: bool = False) -> dict[str, Any]:
    if MANIFEST.exists() and not overwrite_unsealed:
        raise RuntimeError(f"refusing to overwrite V3.4 manifest: {MANIFEST}")
    if LLM_MODEL != "openai/gpt-oss-120b" or VISION_MODEL != "qwen/qwen3.6-27b":
        raise RuntimeError("configured models do not match V3.4")
    triage = _rows(TRIAGE_DATASET)
    triage_cache = _rows(TRIAGE_CACHE)
    scheduling_cache = _rows(SCHEDULING_CACHE)
    receipt_cache = _rows(RECEIPT_CACHE)
    expected = {"triage": 45, "scheduling": 70, "receipts": 108}
    counts = {
        "triage": len(triage_cache), "scheduling": len(scheduling_cache),
        "receipts": len(receipt_cache),
    }
    if counts != expected:
        raise RuntimeError(f"incomplete V3.4 caches: expected {expected}, got {counts}")
    by_index = {row.get("i"): row for row in triage_cache}
    if set(by_index) != set(range(45)):
        raise RuntimeError("V3.4 WF1 cache indexes are incomplete or duplicated")
    for index, source in enumerate(triage):
        row = by_index[index]
        prompt = PROMPT_MAP["triage"].format(input=source["model_input"], source="chat")
        if (
            row.get("schema_version") != "3.4"
            or row.get("model") != LLM_MODEL
            or row.get("case_id") != source["case_id"]
            or row.get("source_sha256") != _sha_text(source["model_input"])
            or row.get("prompt_sha256") != _sha_text(SYSTEM_PROMPT + "\n" + prompt)
            or "error" in row.get("x", {})
        ):
            raise RuntimeError(f"invalid V3.4 frozen WF1 row {index}")
    payload = {
        "schema_version": "3.4",
        "title": "Automated Matched Workflow Evaluation V3.4",
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
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    print(json.dumps(seal(), ensure_ascii=False, indent=2))
