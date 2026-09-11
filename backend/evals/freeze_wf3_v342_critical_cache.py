"""Freeze the independent production critical-field read for WF3 V3.4.2.

The cache contains source/prompt provenance and model output only.  Gold and dataset meta
are deliberately never serialised into the model cache.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from ..agent.vision_extract import (
    CRITICAL_RECEIPT_INFERENCE,
    CRITICAL_RECEIPT_PROMPT,
    VISION_SYSTEM,
    extract_receipt_critical,
)
from ..config import VISION_MODEL
from ..workflows.expense_reconciliation import (
    CRITICAL_READ_SELECTOR_VERSION,
    critical_read_triggers,
)
from .receipt_score import load_manifest


ROOT = Path(__file__).resolve().parents[2]
RECEIPT_DIR = ROOT / "data/receipts/synthetic_v2"
MANIFEST = RECEIPT_DIR / "manifest.jsonl"
PRIMARY_CACHE = ROOT / "data/eval_cache/receipts_qwen3.6-27b_synthetic_v2.jsonl"
CACHE_PROTOCOL = "wf3-critical-v342-nonthinking-1"
CACHE = ROOT / "data/eval_cache/receipts_qwen3.6-27b_critical_v342_nonthinking.jsonl"


def _sha(raw: bytes | str) -> str:
    value = raw.encode("utf-8") if isinstance(raw, str) else raw
    return hashlib.sha256(value).hexdigest()


def _rows() -> list[dict[str, Any]]:
    if not CACHE.is_file():
        return []
    return [json.loads(line) for line in CACHE.read_text(encoding="utf-8").splitlines() if line]


def cache_protocol_provenance() -> dict[str, Any]:
    """Return the exact inference protocol every frozen row must declare."""
    return {
        "cache_protocol": CACHE_PROTOCOL,
        "model": VISION_MODEL,
        "prompt_sha256": _sha(VISION_SYSTEM + "\n" + CRITICAL_RECEIPT_PROMPT),
        "inference_config": CRITICAL_RECEIPT_INFERENCE,
        "inference_sha256": _sha(json.dumps(CRITICAL_RECEIPT_INFERENCE, sort_keys=True)),
        "selector_version": CRITICAL_READ_SELECTOR_VERSION,
        "primary_cache_sha256": _sha(PRIMARY_CACHE.read_bytes()),
    }


def freeze(*, limit: int | None = None) -> dict[str, int]:
    entries = load_manifest(str(MANIFEST))
    primary = {
        row["image"]: row["extraction"]
        for row in (
            json.loads(line) for line in PRIMARY_CACHE.read_text(encoding="utf-8").splitlines()
            if line
        )
    }
    entries = [
        entry for entry in entries
        if critical_read_triggers(primary[entry["image"]], now=date(2026, 7, 1))
    ]
    if limit is not None:
        entries = entries[:limit]
    rows = _rows()
    if len({row.get("image") for row in rows}) != len(rows):
        raise RuntimeError(f"duplicate images in {CACHE}")
    existing = {row["image"]: row for row in rows}
    protocol = cache_protocol_provenance()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    written = reused = 0
    with CACHE.open("a", encoding="utf-8") as handle:
        for index, entry in enumerate(entries):
            image = str(entry["image"])
            path = RECEIPT_DIR / image
            image_sha = _sha(path.read_bytes())
            if image in existing:
                row = existing[image]
                if (
                    row.get("image_sha256") != image_sha
                    or any(row.get(key) != value for key, value in protocol.items())
                ):
                    raise RuntimeError(f"critical cache provenance mismatch: {image}")
                reused += 1
                continue
            output = extract_receipt_critical(
                path, mime="image/png", model=VISION_MODEL,
                inference_config=CRITICAL_RECEIPT_INFERENCE,
            )
            if output.get("error"):
                raise RuntimeError(f"critical read failed for {image}: {output}")
            row = {
                "schema_version": "3.4.2",
                "image": image,
                "image_sha256": image_sha,
                **protocol,
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "critical_read": output,
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            written += 1
            print(f"critical read: {index + 1}/{len(entries)} {image}", flush=True)
    return {"expected": len(entries), "reused": reused, "written": written}


if __name__ == "__main__":
    print(json.dumps(freeze(), ensure_ascii=False, indent=2))
