"""External-validity check for WF1: run triage over QMSum meeting transcripts.

**Scope: read before citing these numbers.** QMSum contains meetings from several domains,
including scenario-acted AMI product meetings and public committee meetings. The sampled
meetings contain **none of WF1's administrative intents**: no leave requests and no
"book us a meeting" asks. This harness therefore cannot measure detection recall because
there is nothing to detect.

What it measures instead is the mirror image, and it is the more useful half for this
project: **does the model invent administrative actions when fed real, messy,
action-dense human speech?** Real meetings are full of action-flavoured language ("we
should", "I'll do X", "let's look at that") without containing a single routable
administrative request. WF1's known weakness is exactly this over-detection (synthetic
`ambiguous` tier: correct refusal 0.40) — this tests it on real data.

Gold is **"no routable action", by dataset construction** rather than by annotation. Every
raw model output is cached so any firing can be inspected: if a transcript really does
contain a request, that is a data finding, not a silent scoring error.

Transcripts are truncated to `MAX_TURNS` speaker turns — WF1 is built for chat threads and
its own position-sensitivity grid tops out at 50 turns, so this keeps the model in the
regime it was designed and evaluated for (a full 8k-token meeting is a different task).

Data: the Apache-2.0 `pszemraj/qmsum-cleaned` mirror is streamed at run time. Raw
transcripts are gitignored. See `THIRD_PARTY_NOTICES.md` for source licences and citations.

Usage: python -m backend.evals.external_ami [n] [model]
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Optional

from ..agent.extract import llm_extract
from ..config import LLM_MODEL
from ..workflows.triage import ROUTABLE, validate_triage
from . import results_store

DATASET = "pszemraj/qmsum-cleaned"      # QMSum is built on AMI; ungated mirror
SAMPLE_DIR = "data/transcripts/ami_sample"
CACHE_DIR = "data/eval_cache"
MAX_TURNS = 50                          # WF1's evaluated regime (position grid tops at 50)


def _transcript(example: dict[str, Any]) -> str:
    """QMSum packs `query\\n<speaker turns>` into `input` — drop the query, keep the meeting."""
    body = str(example.get("input", "")).split("\n", 1)[-1]
    turns = [ln.strip() for ln in body.split("\n") if ln.strip()]
    return "\n".join(turns[:MAX_TURNS])


def _triage_retry(text: str, model: Optional[str], label: str) -> dict:
    last: Exception | None = None
    for attempt in range(5):
        try:
            return validate_triage(llm_extract("triage", text, model, source="chat"))
        except Exception as e:  # noqa: BLE001 — rate limit / transient provider error
            last = e
            wait = min(90, 15 * (attempt + 1))
            print(f"  [{label}] attempt {attempt + 1} failed ({type(e).__name__}); "
                  f"waiting {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"triage kept failing on {label}: {last}")


def run(n: int = 20, model: Optional[str] = None) -> dict[str, Any]:
    from datasets import load_dataset

    effective = model or LLM_MODEL
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)
    slug = effective.split("/")[-1]
    cache_path = os.path.join(CACHE_DIR, f"ami_{slug}.jsonl")
    cache: dict[int, dict] = {}
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                cache[row["i"]] = row

    ds = load_dataset(DATASET, split="train", streaming=True)
    seen: set[str] = set()
    rows: list[dict] = []

    print(f"QMSum external eval — {effective} on {n} meeting transcripts", flush=True)
    print("(gold = no routable action; any detection is a false positive)\n", flush=True)
    for ex in ds:
        if len(rows) >= n:
            break
        text = _transcript(ex)
        key = text[:200]
        if len(text) < 200 or key in seen:      # skip stubs + repeated transcripts
            continue
        seen.add(key)
        i = len(rows)
        if i in cache:
            row = cache[i]
        else:
            with open(os.path.join(SAMPLE_DIR, f"ami_{i}.txt"), "w", encoding="utf-8") as f:
                f.write(text)
            result = _triage_retry(text, model, f"ami_{i}")
            fired = [a["action_type"] for a in result["detected_actions"]
                     if a["action_type"] in ROUTABLE]
            row = {"i": i, "fired": fired, "summary": result.get("summary", ""),
                   "raw": result["detected_actions"]}
            with open(cache_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        rows.append(row)
        mark = "OK  (abstained)" if not row["fired"] else f"X   invented {row['fired']}"
        print(f"[{i + 1:2}] {mark}", flush=True)

    total = len(rows)
    abstained = sum(1 for r in rows if not r["fired"])
    leave = sum(1 for r in rows if "leave_request" in r["fired"])
    meeting = sum(1 for r in rows if "schedule_meeting" in r["fired"])
    result = {
        "n": total,
        "correct_abstention": round(abstained / total, 3) if total else 0.0,
        "spurious_leave_request": leave,
        "spurious_schedule_meeting": meeting,
        "max_turns": MAX_TURNS,
    }
    print(f"\ncorrect abstention on real transcripts: {abstained}/{total} = "
          f"{result['correct_abstention']:.2f}")
    print(f"  invented leave_request:   {leave}")
    print(f"  invented schedule_meeting: {meeting}")
    print(f"(transcripts → {SAMPLE_DIR}/ · raw outputs → {cache_path})")
    results_store.save_result("ami", result, model=effective,
                              params={"n": n, "dataset": DATASET, "max_turns": MAX_TURNS,
                                      "runner": "cli"})
    print("aggregate persisted → data/eval_results/ami.jsonl")
    return result


if __name__ == "__main__":  # pragma: no cover
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 20,
        sys.argv[2] if len(sys.argv) > 2 else None)
