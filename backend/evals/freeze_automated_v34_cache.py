"""Freeze GPT-OSS WF1 outputs for V3.4 without altering any V3.3 artefact."""
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
from ..config import LLM_MODEL

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "data/eval_datasets/triage_v34.jsonl"
CACHE = ROOT / "data/eval_cache/triage_openai-gpt-oss-120b_v34.jsonl"


def _sha(value: str | bytes) -> str:
    raw = value.encode() if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _invoke(text: str, retry_technical: int) -> dict[str, Any]:
    technical = 0
    quota = 0
    while technical <= retry_technical:
        try:
            output = llm_extract("triage", text, model=LLM_MODEL)
            if "error" not in output:
                return output
            technical += 1
            if technical > retry_technical:
                raise RuntimeError(f"technical extraction failure: {output}")
        except Exception as exc:  # provider exception types vary
            message = str(exc)
            if "429" not in message or quota == 9:
                raise
            quota += 1
            match = re.search(r"try again in (?:(\d+)m)?([0-9.]+)s", message)
            wait = min(
                int(match.group(1) or 0) * 60 + float(match.group(2)) + 2, 900
            ) if match else 20.0
            print(f"429 quota response; retrying in {wait:.0f}s", flush=True)
            time.sleep(wait)
    raise RuntimeError("technical extraction retries exhausted")


def freeze(*, retry_technical: int = 1) -> dict[str, int]:
    if LLM_MODEL != "openai/gpt-oss-120b":
        raise RuntimeError("configured text model does not match V3.4")
    sources = _rows(DATASET)
    existing_rows = _rows(CACHE)
    if len({row.get("i") for row in existing_rows}) != len(existing_rows):
        raise RuntimeError("duplicate V3.4 cache indexes")
    existing = {int(row["i"]): row for row in existing_rows}
    counts = {"existing": 0, "written": 0}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE.open("a", encoding="utf-8") as handle:
        for index, source in enumerate(sources):
            text = source["model_input"]
            source_sha = _sha(text)
            if index in existing:
                row = existing[index]
                if row.get("source_sha256") != source_sha or row.get("model") != LLM_MODEL:
                    raise RuntimeError(f"frozen row mismatch: triage[{index}]")
                counts["existing"] += 1
                continue
            extraction = _invoke(text, retry_technical)
            prompt = PROMPT_MAP["triage"].format(input=text, source="chat")
            row = {
                "schema_version": "3.4",
                "i": index,
                "case_id": source["case_id"],
                "workflow": "triage",
                "model": LLM_MODEL,
                "source_sha256": source_sha,
                "prompt_sha256": _sha(SYSTEM_PROMPT + "\n" + prompt),
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "x": extraction,
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            counts["written"] += 1
            print(f"triage: {index + 1}/{len(sources)}", flush=True)
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--retry-technical", type=int, default=1, choices=[0, 1])
    args = parser.parse_args()
    print(json.dumps(freeze(retry_technical=args.retry_technical), indent=2))
