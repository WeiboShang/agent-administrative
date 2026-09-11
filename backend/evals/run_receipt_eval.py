"""Run the receipt eval with the live vision model (needs GROQ_API_KEY + a dataset).

Usage: python -m backend.evals.run_receipt_eval [dataset_dir] [n_per_tier|"final"] [model]

``model`` overrides ``config.VISION_MODEL`` (RQ2 cross-model comparison, e.g.
``qwen/qwen3.6-27b``); the cache file is per-model, so both models' raw outputs on the
same images coexist.

Renders a synthetic dataset if the dir has no manifest ("final" = the asymmetric
``FINAL_COUNTS``), then scores extraction per difficulty tier (M1 field accuracy,
M6 refusal) and policy detection (M3) against gold.

Every raw extraction is checkpointed to ``data/eval_cache/receipts_{model}_{dataset}.jsonl``
— a crash or quota cut-off loses nothing (reruns skip cached images), and the cache
doubles as the frozen raw outputs for cross-model comparison (e.g. scout vs its
post-deprecation replacement). The aggregate is persisted to
``data/eval_results/receipts.jsonl``.
"""
import json
import os
import sys
import time

from ..agent.vision_extract import extract_receipt
from ..backends.records import RecordStore
from ..config import VISION_MODEL
from ..fixtures import org
from . import results_store
from .receipt_data import FINAL_COUNTS, write_dataset
from .receipt_score import evaluate, format_report, load_manifest

CACHE_DIR = "data/eval_cache"


def _cached_vision(out_dir: str, cache_path: str, model: str | None = None):
    """extract_fn wrapper: checkpoint every extraction; retry on transient failures
    (rate limits) rather than recording garbage; abort if a case keeps failing."""
    cache: dict[str, dict] = {}
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                cache[row["image"]] = row["extraction"]

    def vision(entry: dict) -> dict:
        img = entry["image"]
        if img in cache:
            return cache[img]
        last: Exception | None = None
        for attempt in range(5):
            try:
                ext = extract_receipt(os.path.join(out_dir, img), mime="image/png",
                                      model=model)
                with open(cache_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"image": img, "gold": entry["gold"],
                                        "tier": entry["meta"]["tier"],
                                        "extraction": ext}, ensure_ascii=False) + "\n")
                cache[img] = ext
                return ext
            except Exception as e:  # noqa: BLE001 — rate limit / transient provider error
                last = e
                wait = min(90, 15 * (attempt + 1))
                print(f"  [{img}] attempt {attempt + 1} failed ({type(e).__name__}); "
                      f"waiting {wait}s", flush=True)
                time.sleep(wait)
        raise RuntimeError(f"extraction kept failing on {img}: {last}")

    return vision


def main() -> None:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "data/receipts/synthetic"
    spec = sys.argv[2] if len(sys.argv) > 2 else "3"
    model = sys.argv[3] if len(sys.argv) > 3 else None
    effective = model or VISION_MODEL
    manifest_path = os.path.join(out_dir, "manifest.jsonl")
    if not os.path.exists(manifest_path):
        if spec == "final":
            write_dataset(out_dir, counts=FINAL_COUNTS)
        else:
            write_dataset(out_dir, n_per_tier=int(spec))
    entries = load_manifest(manifest_path)

    store = RecordStore(":memory:")
    org.seed_from_org(store)

    os.makedirs(CACHE_DIR, exist_ok=True)
    slug = effective.split("/")[-1]
    dataset = os.path.basename(os.path.normpath(out_dir))
    cache_path = os.path.join(CACHE_DIR, f"receipts_{slug}_{dataset}.jsonl")
    vision = _cached_vision(out_dir, cache_path, model=model)

    print(f"WF3 receipt eval — {effective}, {len(entries)} images:\n", flush=True)
    result = evaluate(entries, vision, store)
    print(format_report(result))
    results_store.save_result("receipts", result, model=effective,
                              params={"dataset": dataset, "n_images": len(entries),
                                      "runner": "cli"})
    print(f"\nraw extractions cached → {cache_path}")
    print("aggregate persisted     → data/eval_results/receipts.jsonl")


if __name__ == "__main__":  # pragma: no cover
    main()
