"""Is the model's self-reported confidence worth anything? (WF1 triage)

Every detected action carries a ``confidence`` the model wrote itself. Nothing has ever
used it — not the UI, not the router. This asks whether it *could*: do the spurious
detections (an action invented from social chit-chat) carry systematically lower confidence
than the real ones?

  - discriminative (high AUROC) → confidence is a usable gate signal; sweep a threshold and
    report the abstention/recall trade-off.
  - not discriminative → the model is just as sure when it is making things up, so it cannot
    police its own over-detection and an EXTERNAL check is the only filter available. That is
    a direct argument for the human gate (RQ3), and is what the calibration literature
    predicts for verbalized confidence.

Pure code: reads the raw outputs `run_full_eval.py` checkpoints to data/eval_cache/, so it
costs nothing to re-run. Cases are regenerated deterministically from the same seed.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

from ..workflows.triage import ROUTABLE
from .triage_data import ThreadCase


def auroc(pos: list[float], neg: list[float]) -> Optional[float]:
    """Area under the ROC curve via the rank (Mann–Whitney U) identity, ties averaged.

    Returns None unless both classes are present — an AUROC over one class is meaningless,
    and confidence values tie constantly (models emit 0.9 over and over), so tie handling is
    not optional here: ranking ties arbitrarily would manufacture discrimination.
    """
    if not pos or not neg:
        return None
    labelled = [(v, 1) for v in pos] + [(v, 0) for v in neg]
    labelled.sort(key=lambda t: t[0])
    ranks = [0.0] * len(labelled)
    i = 0
    while i < len(labelled):
        j = i
        while j + 1 < len(labelled) and labelled[j + 1][0] == labelled[i][0]:
            j += 1
        avg = (i + j) / 2 + 1                       # 1-based average rank across the tie run
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    rank_sum_pos = sum(r for r, (_, lab) in zip(ranks, labelled) if lab == 1)
    u = rank_sum_pos - len(pos) * (len(pos) + 1) / 2
    return round(u / (len(pos) * len(neg)), 3)


def collect_confidences(cases: list[ThreadCase], extractions: list[dict]) -> dict[str, Any]:
    """Label every emitted routable action against gold and bucket its confidence.

    Unit of analysis is the ACTION, not the thread: a thread can yield one correct and one
    spurious detection, and it is exactly that distinction the confidence should track.
    """
    pos: list[float] = []      # confidence on actions that ARE in gold
    neg: list[float] = []      # confidence on spurious actions
    rows: list[dict[str, Any]] = []
    for case, x in zip(cases, extractions):
        gold = {t for t in case.gold["action_types"] if t in ROUTABLE}
        for a in x.get("detected_actions", []):
            at = a.get("action_type")
            if at not in ROUTABLE:
                continue
            conf = a.get("confidence")
            if not isinstance(conf, (int, float)) or isinstance(conf, bool):
                continue
            correct = at in gold
            (pos if correct else neg).append(float(conf))
            rows.append({"tier": case.meta.get("tier"), "action_type": at,
                         "confidence": float(conf), "correct": correct})

    def mean(v: list[float]) -> Optional[float]:
        return round(sum(v) / len(v), 3) if v else None

    return {
        "n_actions": len(rows),
        "n_correct": len(pos),
        "n_spurious": len(neg),
        "mean_confidence_correct": mean(pos),
        "mean_confidence_spurious": mean(neg),
        "auroc": auroc(pos, neg),
        "rows": rows,
    }


def threshold_sweep(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What a confidence gate would actually buy, at every threshold the data supports.

    An AUROC says the two classes are separable; it does not say a usable operating point
    exists. This reports, for each observed confidence value t (gate = keep actions with
    confidence >= t): the share of TRUE detections retained and the share of SPURIOUS ones
    removed. If the model emits only a couple of distinct values, that shows up here as a
    sweep with only a couple of rows — which is the honest read of such a gate's brittleness.
    """
    pos = [r["confidence"] for r in rows if r["correct"]]
    neg = [r["confidence"] for r in rows if not r["correct"]]
    if not pos or not neg:
        return []
    out = []
    for t in sorted({r["confidence"] for r in rows}):
        kept_true = sum(1 for v in pos if v >= t)
        kept_spurious = sum(1 for v in neg if v >= t)
        out.append({
            "threshold": t,
            "true_retained": round(kept_true / len(pos), 3),
            "spurious_removed": round(1 - kept_spurious / len(neg), 3),
        })
    return out


def load_cache(path: str) -> list[dict]:
    """Read a run_full_eval checkpoint file ({"i": idx, "x": extraction} per line)."""
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"no cached run at {path} — collect one first with:\n"
            f"  python -m backend.evals.run_full_eval triage --n <N>")
    by_i: dict[int, dict] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                e = json.loads(line)
                by_i[e["i"]] = e["x"]
    return [by_i[i] for i in sorted(by_i)]


def main() -> None:  # pragma: no cover — analysis CLI
    """Analyse a cached run — no LLM calls, the extractions are already paid for.

    ``--source pairs``  : minimal-pair twins. Classes differ by a DESIGNED lexical cue, so
                          separability here is an upper bound.
    ``--source triage`` : the standard tier set, whose ``ambiguous`` tier is natural
                          borderline chat — the test of whether a gate fitted on pairs
                          generalises to text that was not built to contrast.
    """
    import argparse

    from .triage_data import make_dataset, make_pair_dataset

    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="pairs", choices=["pairs", "triage"])
    ap.add_argument("--model", default="llama-3.3-70b-versatile")
    ap.add_argument("--n", type=int, default=6)
    args = ap.parse_args()

    slug = args.model.replace("/", "-")
    path = os.path.join("data/eval_cache", f"{args.source}_{slug}_template_n{args.n}.jsonl")
    xs = load_cache(path)
    cases = ([c for pair in make_pair_dataset(n_per_delta=args.n) for c in pair]
             if args.source == "pairs" else make_dataset(n_per_tier=args.n))
    if len(cases) != len(xs):
        raise SystemExit(f"cache has {len(xs)} extractions but the dataset regenerates "
                         f"{len(cases)} cases — n mismatch?")
    out = collect_confidences(cases, xs)
    rows = out.pop("rows")
    out["threshold_sweep"] = threshold_sweep(rows)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":  # pragma: no cover
    main()
