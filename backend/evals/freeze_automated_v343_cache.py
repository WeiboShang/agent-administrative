"""Freeze the one changed WF2 GPT-OSS output required by V3.4.3.

The other 69 outputs are copied byte-for-byte at the extraction level from the
immutable V3.3 cache.  This script reads source text only; gold and metadata never
enter model execution.
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
from ..config import LLM_MODEL

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "data/eval_datasets/scheduling_v343.jsonl"
SOURCE_CACHE = (
    ROOT / "data/eval_cache/scheduling_openai-gpt-oss-120b_realised_v33.jsonl"
)
OUTPUT = ROOT / "data/eval_cache/scheduling_openai-gpt-oss-120b_v343.jsonl"
REPAIRED_INDEX = 30


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _rows(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _invoke(text: str, retry_technical: int) -> dict[str, Any]:
    technical_attempts = 0
    quota_attempts = 0
    while technical_attempts <= retry_technical:
        try:
            output = llm_extract("scheduling", text, model=LLM_MODEL)
            if "error" not in output:
                return output
            technical_attempts += 1
            if technical_attempts > retry_technical:
                raise RuntimeError(f"technical extraction failure: {output}")
        except Exception as exc:  # noqa: BLE001 - provider exceptions vary
            message = str(exc)
            if "429" not in message or quota_attempts == 9:
                raise
            quota_attempts += 1
            match = re.search(r"try again in (?:(\d+)m)?([0-9.]+)s", message)
            wait = (
                min(int(match.group(1) or 0) * 60 + float(match.group(2)) + 2, 900)
                if match
                else 20.0
            )
            print(f"429 quota response; retrying in {wait:.0f}s", flush=True)
            time.sleep(wait)
    raise RuntimeError("technical extraction retries exhausted")


def freeze(*, retry_technical: int = 1) -> dict[str, int]:
    if OUTPUT.exists():
        raise RuntimeError(f"refusing to overwrite V3.4.3 cache: {OUTPUT}")
    dataset = _rows(DATASET)
    old_rows = _rows(SOURCE_CACHE)
    old_by_index = {int(row["i"]): row for row in old_rows}
    if len(dataset) != 70 or set(old_by_index) != set(range(70)):
        raise RuntimeError("incomplete WF2 dataset or source cache")
    new_rows: list[dict[str, Any]] = []
    for index, source in enumerate(dataset):
        text = source["input_text"]
        old = old_by_index[index]
        if index == REPAIRED_INDEX:
            extraction = _invoke(text, retry_technical)
            generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            provenance = {"generation": "fresh_source_repair"}
        else:
            if old.get("source_sha256") != _sha(text):
                raise RuntimeError(f"unchanged WF2 source/cache mismatch at {index}")
            extraction = old["x"]
            generated_at = old["generated_at"]
            provenance = {
                "generation": "reused_immutable_v33",
                "original_schema_version": old.get("schema_version"),
            }
        prompt = PROMPT_MAP["scheduling"].format(input=text, source="chat")
        new_rows.append(
            {
                "schema_version": "3.4.3",
                "i": index,
                "workflow": "scheduling",
                "model": LLM_MODEL,
                "source_sha256": _sha(text),
                "prompt_sha256": _sha(SYSTEM_PROMPT + "\n" + prompt),
                "generated_at": generated_at,
                "provenance": provenance,
                "x": extraction,
            }
        )
    OUTPUT.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in new_rows),
        encoding="utf-8",
    )
    return {"reused": 69, "fresh": 1, "total": len(new_rows)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--retry-technical", type=int, default=1, choices=[0, 1])
    args = parser.parse_args()
    print(json.dumps(freeze(retry_technical=args.retry_technical), indent=2))
