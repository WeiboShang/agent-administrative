"""Freeze actual Agent outputs for Human Evaluation V5.

Case inputs and allocation are fixed before this script runs.  Text cases call the same
production ``llm_extract`` path used by the application.  Receipt cases import the exact
parsed extraction from the committed Qwen synthetic-receipt cache.  The script never reads
the server-only gold file and never retries a semantically wrong answer; only a technical
parse failure may be retried once.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..agent.extract import llm_extract
from ..agent.prompts import PROMPT_MAP, SYSTEM_PROMPT
from ..config import LLM_MODEL, VISION_MODEL


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data/eval_datasets/human_v5_manifest.json"
SOURCES = ROOT / "data/eval_datasets/human_v5_sources.json"
CACHE = ROOT / "data/eval_cache/human_v5_agent_outputs.jsonl"
RECEIPT_CACHE = ROOT / "data/eval_cache/receipts_qwen3.6-27b_synthetic_v2.jsonl"


def _sha(value: str | bytes) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _receipt_index() -> dict[str, dict[str, Any]]:
    return {row["image"]: row["extraction"] for row in _read_jsonl(RECEIPT_CACHE)}


def freeze(
    *, retry_technical: int = 1, workflows: set[str] | None = None
) -> dict[str, int]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sources = json.loads(SOURCES.read_text(encoding="utf-8"))["cases"]
    existing = {row["case_id"]: row for row in _read_jsonl(CACHE)}
    receipts = _receipt_index()
    counts = {"existing": 0, "written": 0}
    CACHE.parent.mkdir(parents=True, exist_ok=True)

    with CACHE.open("a", encoding="utf-8") as handle:
        for spec in manifest["cases"]:
            case_id = spec["case_id"]
            workflow = spec["workflow"]
            if spec["condition"] != "agent_assisted":
                continue
            if workflows is not None and workflow not in workflows:
                continue
            if case_id in existing:
                counts["existing"] += 1
                continue
            source = sources[case_id]
            if workflow == "wf3":
                image = source["receipt"]["image"]
                if image not in receipts:
                    raise RuntimeError(f"missing committed Qwen cache for {image}")
                extraction = receipts[image]
                model = VISION_MODEL
                prompt_sha = "committed-receipt-extraction-cache"
                cache_origin = str(RECEIPT_CACHE.relative_to(ROOT))
            else:
                prompt_name = "triage" if workflow == "wf1" else "scheduling"
                extraction = {}
                for attempt in range(retry_technical + 1):
                    extraction = llm_extract(
                        prompt_name,
                        source["text"],
                        source=source.get("channel"),
                    )
                    if "error" not in extraction:
                        break
                    if attempt == retry_technical:
                        raise RuntimeError(
                            f"technical extraction failure for {case_id}: {extraction}"
                        )
                model = LLM_MODEL
                rendered = PROMPT_MAP[prompt_name].format(
                    input=source["text"], source=source.get("channel") or "chat"
                )
                prompt_sha = _sha(SYSTEM_PROMPT + "\n" + rendered)
                cache_origin = "live-production-llm_extract"

            record = {
                "schema_version": "5.0",
                "case_id": case_id,
                "workflow": workflow,
                "model": model,
                "source_sha256": _sha(
                    json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                ),
                "prompt_sha256": prompt_sha,
                "cache_origin": cache_origin,
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "raw_extraction": extraction,
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            counts["written"] += 1
    return counts


def seal() -> dict[str, str]:
    """Seal the manifest only after every frozen output matches its public source."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sources = json.loads(SOURCES.read_text(encoding="utf-8"))["cases"]
    rows = _read_jsonl(CACHE)
    cache = {row.get("case_id"): row for row in rows}
    ids = {
        row["case_id"] for row in manifest["cases"]
        if row["condition"] == "agent_assisted"
    }
    if len(cache) != len(rows):
        raise RuntimeError("cannot seal: duplicate case_id in V5 cache")
    if set(cache) != ids:
        raise RuntimeError(f"cannot seal: expected {len(ids)} cache rows, found {len(cache)}")
    for case_id in sorted(ids):
        expected = _sha(json.dumps(
            sources[case_id], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ))
        if cache[case_id].get("source_sha256") != expected:
            raise RuntimeError(f"cannot seal: source hash mismatch for {case_id}")
        workflow = next(
            row["workflow"] for row in manifest["cases"] if row["case_id"] == case_id
        )
        expected_model = (
            manifest["vision_model"] if workflow == "wf3" else manifest["text_model"]
        )
        if cache[case_id].get("model") != expected_model:
            raise RuntimeError(f"cannot seal: model mismatch for {case_id}")
    frozen_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest["protocol_status"] = "frozen_pre_collection"
    manifest["frozen_at"] = frozen_at
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "status": "frozen_pre_collection", "frozen_at": frozen_at,
        "manifest_sha256": _sha(MANIFEST.read_bytes()),
        "cache_sha256": _sha(CACHE.read_bytes()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retry-technical", type=int, default=1, choices=(0, 1))
    parser.add_argument(
        "--workflow", action="append", choices=("wf1", "wf2", "wf3"),
        help="Freeze only the selected workflow(s); may be repeated.",
    )
    parser.add_argument(
        "--seal", action="store_true",
        help="After freezing, seal only if all 21 Agent-Assisted output hashes validate.",
    )
    args = parser.parse_args()
    result: dict[str, Any] = {"freeze": freeze(
        retry_technical=args.retry_technical,
        workflows=set(args.workflow) if args.workflow else None,
    )}
    if args.seal:
        result["seal"] = seal()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
