"""External-validity check: run the WF3 vision extractor on REAL receipts (CORD).

CORD (naver-clova-ix/cord-v2) is ~1000 real, in-the-wild Indonesian receipts with
structured labels. Only the TOTAL maps cleanly to our schema, so this measures
**amount-extraction accuracy on real photos** — an external-validity signal for the vision
step (complements the synthetic per-tier M1). Needs `datasets` + GROQ_API_KEY.

Amounts are IDR integers written with '.'/',' thousands separators; both sides are
normalised to an integer before comparison. A small sample of the real images is saved to
`data/receipts/cord_sample/` so they can be inspected.

Per-receipt outputs are checkpointed to ``data/eval_cache/cord_{model}.jsonl`` (streaming
order is deterministic, so reruns skip already-scored receipts — quota cut-offs lose
nothing, and the cache is the frozen raw output for cross-model comparison). The
aggregate is persisted to ``data/eval_results/cord.jsonl``.

Usage: python -m backend.evals.external_cord [n] [model]
"""
import io
import json
import os
import re
import sys
import time

from ..agent.vision_extract import extract_receipt
from ..config import VISION_MODEL
from . import results_store

SAMPLE_DIR = "data/receipts/cord_sample"
CACHE_DIR = "data/eval_cache"


def _norm(v: object) -> int | None:
    """Normalise a money value (number or separator-formatted string) to an integer."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(round(v))
    if isinstance(v, str):
        m = re.search(r"\d+", re.sub(r"[.,\s]", "", v))
        return int(m.group()) if m else None
    return None


def _extract_retry(image_bytes: bytes, label: str, model: str | None = None) -> dict:
    last: Exception | None = None
    for attempt in range(5):
        try:
            return extract_receipt(image_bytes, mime="image/png", model=model)
        except Exception as e:  # noqa: BLE001 — rate limit / transient provider error
            last = e
            wait = min(90, 15 * (attempt + 1))
            print(f"  [{label}] attempt {attempt + 1} failed ({type(e).__name__}); "
                  f"waiting {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"extraction kept failing on {label}: {last}")


def run(n: int = 15, model: str | None = None) -> None:
    from datasets import load_dataset

    effective = model or VISION_MODEL
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)
    slug = effective.split("/")[-1]
    cache_path = os.path.join(CACHE_DIR, f"cord_{slug}.jsonl")
    cache: dict[int, dict] = {}
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                cache[row["i"]] = row

    ds = load_dataset("naver-clova-ix/cord-v2", split="test", streaming=True)

    correct = total = 0
    print(f"CORD external eval — {effective} on {n} real receipts (amount / total):\n",
          flush=True)
    for ex in ds:
        if total >= n:
            break
        gold = _norm(json.loads(ex["ground_truth"])["gt_parse"].get("total", {}).get("total_price"))
        if gold is None:
            continue
        if total in cache:
            row = cache[total]
            got = row["got"]
        else:
            buf = io.BytesIO()
            ex["image"].save(buf, "PNG")
            ex["image"].save(os.path.join(SAMPLE_DIR, f"cord_{total}.png"))
            raw = _extract_retry(buf.getvalue(), f"cord_{total}", model=model)
            got = _norm(raw.get("amount"))
            with open(cache_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"i": total, "gold": gold, "got": got, "raw": raw},
                                   ensure_ascii=False) + "\n")
        ok = got == gold
        correct += ok
        total += 1
        print(f"[{total:2}] gold={gold:>9}  model={str(got):>9}  {'OK' if ok else 'X'}",
              flush=True)

    if total:
        acc = round(correct / total, 3)
        print(f"\namount accuracy on real receipts: {correct}/{total} = {acc:.2f}")
        print(f"(sample images saved to {SAMPLE_DIR}/; raw outputs → {cache_path})")
        results_store.save_result("cord", {"n": total, "correct": correct,
                                           "amount_accuracy": acc},
                                  model=effective, params={"n": n, "runner": "cli"})
        print("aggregate persisted → data/eval_results/cord.jsonl")


if __name__ == "__main__":  # pragma: no cover
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 15,
        sys.argv[2] if len(sys.argv) > 2 else None)
