"""Resume the immutable WF3 V3.4.2 all-image critical-read pilot protocol.

This exists only to finish the already-started 53/108 cache with byte-compatible
provenance.  It intentionally uses Qwen's default reasoning mode, matching the original
calls, and never mixes rows from the later selective/non-thinking protocol.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from ..agent.vision_extract import (
    CRITICAL_RECEIPT_PROMPT,
    VISION_SYSTEM,
    _encode_image,
    _get_client,
    _parse_receipt_json,
)
from ..config import VISION_MODEL
from .receipt_score import load_manifest

ROOT = Path(__file__).resolve().parents[2]
RECEIPT_DIR = ROOT / "data/receipts/synthetic_v2"
MANIFEST = RECEIPT_DIR / "manifest.jsonl"
CACHE = ROOT / "data/eval_cache/receipts_qwen3.6-27b_critical_v342.jsonl"


def _sha(raw: bytes | str) -> str:
    value = raw.encode("utf-8") if isinstance(raw, str) else raw
    return hashlib.sha256(value).hexdigest()


def _rows() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in CACHE.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _legacy_critical_read(path: Path) -> dict[str, Any]:
    b64 = _encode_image(path)
    message = HumanMessage(content=[
        {"type": "text", "text": CRITICAL_RECEIPT_PROMPT},
        {"type": "image_url", "image_url": {
            "url": f"data:image/png;base64,{b64}",
        }},
    ])
    # Deliberately no reasoning_effort/max-token override: this is the exact old call.
    response = _get_client(VISION_MODEL).invoke([
        SystemMessage(content=VISION_SYSTEM), message,
    ])
    parsed = _parse_receipt_json(response.content)
    return {key: parsed.get(key) for key in ("vendor", "date", "amount", "currency")}


def resume(*, max_new: int | None = None, pace_seconds: float = 22.0) -> dict[str, int]:
    entries = load_manifest(str(MANIFEST))
    rows = _rows()
    if len(rows) > len(entries):
        raise RuntimeError("critical cache is longer than the receipt manifest")
    if [row.get("image") for row in rows] != [
        entry["image"] for entry in entries[:len(rows)]
    ]:
        raise RuntimeError("critical cache is not a contiguous manifest prefix")
    prompt_sha = _sha(VISION_SYSTEM + "\n" + CRITICAL_RECEIPT_PROMPT)
    for row in rows:
        path = RECEIPT_DIR / row["image"]
        if (
            row.get("model") != VISION_MODEL
            or row.get("prompt_sha256") != prompt_sha
            or row.get("image_sha256") != _sha(path.read_bytes())
        ):
            raise RuntimeError(f"legacy cache provenance mismatch: {row.get('image')}")

    pending = entries[len(rows):]
    if max_new is not None:
        pending = pending[:max(0, max_new)]
    written = 0
    with CACHE.open("a", encoding="utf-8") as handle:
        for offset, entry in enumerate(pending):
            image = entry["image"]
            path = RECEIPT_DIR / image
            output = _legacy_critical_read(path)
            if output.get("error"):
                raise RuntimeError(f"critical read failed for {image}: {output}")
            row = {
                "schema_version": "3.4.2",
                "image": image,
                "model": VISION_MODEL,
                "image_sha256": _sha(path.read_bytes()),
                "prompt_sha256": prompt_sha,
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "critical_read": output,
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            written += 1
            print(
                f"legacy critical read: {len(rows) + written}/{len(entries)} {image}",
                flush=True,
            )
            if offset + 1 < len(pending) and pace_seconds > 0:
                time.sleep(pace_seconds)
    return {"expected": len(entries), "started_at": len(rows), "written": written}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-new", type=int)
    parser.add_argument("--pace-seconds", type=float, default=22.0)
    args = parser.parse_args()
    print(json.dumps(
        resume(max_new=args.max_new, pace_seconds=args.pace_seconds),
        ensure_ascii=False,
        indent=2,
    ))
