"""Freeze actual GPT-OSS outputs for Automated Evaluation V3.3.

The synthetic realised inputs are fixed before this script runs. It calls the same
production ``llm_extract`` path as WF1/WF2, checkpoints every response, never reads gold,
and seals only when both text caches and the committed Qwen receipt cache are complete.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..agent.extract import llm_extract
from ..agent.prompts import PROMPT_MAP, SYSTEM_PROMPT
from ..config import LLM_MODEL, VISION_MODEL
from .realiser import load_sched_cases, load_thread_cases


ROOT = Path(__file__).resolve().parents[2]
DATASETS = ROOT / "data/eval_datasets"
CACHE_DIR = ROOT / "data/eval_cache"
MANIFEST = DATASETS / "automated_v33_manifest.json"
TRIAGE_DATASET = DATASETS / "triage_realised.jsonl"
SCHEDULING_DATASET = DATASETS / "scheduling_realised.jsonl"
TRIAGE_CACHE = CACHE_DIR / "triage_openai-gpt-oss-120b_realised_v33.jsonl"
SCHEDULING_CACHE = CACHE_DIR / "scheduling_openai-gpt-oss-120b_realised_v33.jsonl"
RECEIPT_CACHE = CACHE_DIR / "receipts_qwen3.6-27b_synthetic_v2.jsonl"


def _sha(value: str | bytes) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _file_sha(path: Path) -> str:
    return _sha(path.read_bytes())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _invoke(workflow: str, text: str, *, retry_technical: int) -> dict[str, Any]:
    technical_attempts = 0
    quota_attempts = 0
    while technical_attempts <= retry_technical:
        try:
            output = llm_extract(workflow, text, model=LLM_MODEL)
            if "error" not in output:
                return output
            technical_attempts += 1
            if technical_attempts > retry_technical:
                raise RuntimeError(f"technical extraction failure: {output}")
        except Exception as exc:  # noqa: BLE001 - provider exception types vary
            message = str(exc)
            if "429" not in message or quota_attempts == 9:
                raise
            quota_attempts += 1
            match = re.search(r"try again in (?:(\d+)m)?([0-9.]+)s", message)
            wait = (
                min(int(match.group(1) or 0) * 60 + float(match.group(2)) + 2, 900)
                if match else 20.0
            )
            print(f"429 quota response; retrying in {wait:.0f}s", flush=True)
            time.sleep(wait)
            continue
    raise RuntimeError("technical extraction retries exhausted")


def _freeze_one(
    *, workflow: str, texts: list[str], cache_path: Path, retry_technical: int
) -> dict[str, int]:
    rows = _read_jsonl(cache_path)
    if len({row.get("i") for row in rows}) != len(rows):
        raise RuntimeError(f"duplicate indexes in {cache_path}")
    existing = {int(row["i"]): row for row in rows}
    counts = {"existing": 0, "written": 0}
    rendered_prompt = PROMPT_MAP[workflow]
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("a", encoding="utf-8") as handle:
        for index, text in enumerate(texts):
            source_sha = _sha(text)
            if index in existing:
                row = existing[index]
                if row.get("source_sha256") != source_sha or row.get("model") != LLM_MODEL:
                    raise RuntimeError(f"frozen row mismatch: {workflow}[{index}]")
                counts["existing"] += 1
                continue
            extraction = _invoke(workflow, text, retry_technical=retry_technical)
            prompt = rendered_prompt.format(input=text, source="chat")
            row = {
                "schema_version": "3.3",
                "i": index,
                "workflow": workflow,
                "model": LLM_MODEL,
                "source_sha256": source_sha,
                "prompt_sha256": _sha(SYSTEM_PROMPT + "\n" + prompt),
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "x": extraction,
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            counts["written"] += 1
            print(f"{workflow}: {index + 1}/{len(texts)}", flush=True)
    return counts


def freeze(*, workflows: set[str], retry_technical: int = 1) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if "triage" in workflows:
        result["triage"] = _freeze_one(
            workflow="triage",
            texts=[case.raw_text for case in load_thread_cases(str(TRIAGE_DATASET))],
            cache_path=TRIAGE_CACHE,
            retry_technical=retry_technical,
        )
    if "scheduling" in workflows:
        result["scheduling"] = _freeze_one(
            workflow="scheduling",
            texts=[case.input_text for case in load_sched_cases(str(SCHEDULING_DATASET))],
            cache_path=SCHEDULING_CACHE,
            retry_technical=retry_technical,
        )
    return result


def seal() -> dict[str, Any]:
    if MANIFEST.exists():
        raise RuntimeError(f"refusing to overwrite sealed protocol: {MANIFEST}")
    if LLM_MODEL != "openai/gpt-oss-120b" or VISION_MODEL != "qwen/qwen3.6-27b":
        raise RuntimeError("configured models do not match the V3.3 protocol")
    expected = {"triage": 45, "scheduling": 70, "receipts": 108}
    paths = {
        "triage": TRIAGE_CACHE,
        "scheduling": SCHEDULING_CACHE,
        "receipts": RECEIPT_CACHE,
    }
    counts = {name: len(_read_jsonl(path)) for name, path in paths.items()}
    if counts != expected:
        raise RuntimeError(f"cannot seal V3.3: expected {expected}, found {counts}")
    text_sources = {
        "triage": [case.raw_text for case in load_thread_cases(str(TRIAGE_DATASET))],
        "scheduling": [
            case.input_text for case in load_sched_cases(str(SCHEDULING_DATASET))
        ],
    }
    for workflow, sources in text_sources.items():
        rows = _read_jsonl(paths[workflow])
        by_index = {row.get("i"): row for row in rows}
        if set(by_index) != set(range(len(sources))):
            raise RuntimeError(f"{workflow} cache indexes are incomplete or duplicated")
        for index, source in enumerate(sources):
            row = by_index[index]
            prompt = PROMPT_MAP[workflow].format(input=source, source="chat")
            if (
                row.get("schema_version") != "3.3"
                or row.get("model") != LLM_MODEL
                or row.get("source_sha256") != _sha(source)
                or row.get("prompt_sha256") != _sha(SYSTEM_PROMPT + "\n" + prompt)
                or "error" in row.get("x", {})
            ):
                raise RuntimeError(f"invalid frozen row: {workflow}[{index}]")
    receipt_rows = _read_jsonl(RECEIPT_CACHE)
    receipt_ids = [row.get("image") for row in receipt_rows]
    manifest_ids = [
        json.loads(line)["image"]
        for line in (ROOT / "data/receipts/synthetic_v2/manifest.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    if len(set(receipt_ids)) != len(receipt_ids) or set(receipt_ids) != set(manifest_ids):
        raise RuntimeError("receipt cache IDs do not exactly match the receipt manifest")
    payload = {
        "schema_version": "3.3",
        "title": "Automated Matched Workflow Evaluation V3.3",
        "synthetic_only": True,
        "mock_backends_only": True,
        "protocol_status": "frozen_pre_run",
        "text_model": LLM_MODEL,
        "vision_model": VISION_MODEL,
        "unique_case_counts": expected,
        "paired_execution_count": 2 * sum(expected.values()),
        "policy_contract": {"meals_limit_gbp": 50, "over_limit": "hard_reject"},
        "oracle_correction_in_primary": False,
        "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset_sha256": {
            "triage": _file_sha(TRIAGE_DATASET),
            "scheduling": _file_sha(SCHEDULING_DATASET),
            "receipts": _file_sha(ROOT / "data/receipts/synthetic_v2/manifest.jsonl"),
        },
        "cache_sha256": {name: _file_sha(path) for name, path in paths.items()},
    }
    MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow", action="append", choices=["triage", "scheduling"])
    parser.add_argument("--retry-technical", type=int, default=1, choices=[0, 1])
    parser.add_argument("--seal", action="store_true")
    args = parser.parse_args()
    workflows = set(args.workflow or ["triage", "scheduling"])
    result: dict[str, Any] = {
        "freeze": freeze(workflows=workflows, retry_technical=args.retry_technical)
    }
    if args.seal:
        result["seal"] = seal()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
