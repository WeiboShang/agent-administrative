"""Run M2 (task success) on the cached extractions — zero quota.

    python -m backend.evals.run_task_success

Both workflows are replayed from the raw model outputs already checkpointed in
data/eval_cache/, so this costs no API calls and scores exactly the extractions the
published M1 numbers were computed from — M1 and M2 therefore describe the same run,
which is what makes the contrast between them meaningful.
"""
import json
import os
import sys

from . import results_store
from .realiser import load_sched_cases
from .receipt_score import load_manifest
from .task_success import evaluate_expense_task, evaluate_scheduling_task, format_report

CACHE = "data/eval_cache"
SCHED_CACHE = os.path.join(CACHE, "scheduling_llama-3.3-70b-versatile_realised.jsonl")
SCHED_CASES = "data/eval_datasets/scheduling_realised.jsonl"
RECEIPT_CACHE = os.path.join(CACHE, "receipts_qwen3.6-27b_synthetic_v2.jsonl")
RECEIPT_MANIFEST = "data/receipts/synthetic_v2/manifest.jsonl"
SCHED_MODEL = "llama-3.3-70b-versatile"
RECEIPT_MODEL = "qwen/qwen3.6-27b"


def _load_indexed(path: str) -> dict[int, dict]:
    """run_full_eval checkpoints as {"i": index, "x": extraction}."""
    with open(path, encoding="utf-8") as f:
        return {e["i"]: e["x"] for line in f if line.strip() for e in [json.loads(line)]}


def _load_by_image(path: str) -> dict[str, dict]:
    """run_receipt_eval checkpoints as {"image": name, "extraction": {...}}."""
    with open(path, encoding="utf-8") as f:
        return {e["image"]: e["extraction"] for line in f if line.strip()
                for e in [json.loads(line)]}


def main() -> None:
    missing = [p for p in (SCHED_CACHE, SCHED_CASES, RECEIPT_CACHE, RECEIPT_MANIFEST)
               if not os.path.exists(p)]
    if missing:
        sys.exit(f"missing input(s): {missing}")

    # ── WF2 ──
    cases = load_sched_cases(SCHED_CASES)
    cached = _load_indexed(SCHED_CACHE)
    order = {id(c): i for i, c in enumerate(cases)}
    covered = [c for c in cases if order[id(c)] in cached]
    sched = evaluate_scheduling_task(covered, lambda c: cached[order[id(c)]])
    print(format_report(sched, f"WF2 scheduling · {SCHED_MODEL} · realised"), "\n")
    results_store.save_result("task_success_wf2", sched, model=SCHED_MODEL,
                              params={"dataset": "realised", "n": len(covered),
                                      "source": "cached extractions", "runner": "cli"})

    # ── WF3 ──
    entries = load_manifest(RECEIPT_MANIFEST)
    by_img = _load_by_image(RECEIPT_CACHE)
    entries = [e for e in entries if e["image"] in by_img]
    expense = evaluate_expense_task(entries, lambda e: by_img[e["image"]])
    print(format_report(expense, f"WF3 expense · {RECEIPT_MODEL} · synthetic_v2"))
    results_store.save_result("task_success_wf3", expense, model=RECEIPT_MODEL,
                              params={"dataset": "synthetic_v2", "n": len(entries),
                                      "source": "cached extractions", "runner": "cli"})

    print("\npersisted → data/eval_results/task_success_wf{2,3}.jsonl")


if __name__ == "__main__":  # pragma: no cover
    main()
