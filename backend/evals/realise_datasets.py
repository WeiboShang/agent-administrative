"""Freeze LLM-realised eval datasets (resumable; final numbers use the frozen files).

    python -m backend.evals.realise_datasets [n_per_tier_wf2] [n_per_tier_wf1] [realiser]

realiser: "kimi" (default — Kimi K2 on Groq, generous quota) or "gemini" (free tier is
only ~20 req/day). Cases are written INCREMENTALLY and the run RESUMES from the existing
file line-count, so a quota cut-off costs nothing — rerun the command when quota returns.
"""
import json
import os
import sys
from collections import Counter
from dataclasses import asdict

from .realiser import (
    DATASETS_DIR,
    make_gemini_realiser,
    make_groq_realiser,
    realise_sched_case,
    realise_thread_case,
)
from .scheduling_data import make_dataset as make_sched
from .triage_data import make_dataset as make_triage


def _resume_freeze(cases: list, path: str, realise_one) -> bool:
    """Append-realise ``cases[k:]`` where k = lines already in ``path``. Returns True
    when the file is complete."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    done = 0
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            done = sum(1 for line in f if line.strip())
    if done >= len(cases):
        print(f"  {path}: already complete ({done})")
        return True
    print(f"  {path}: resuming at {done}/{len(cases)}")
    with open(path, "a", encoding="utf-8") as f:
        for i in range(done, len(cases)):
            try:
                r = realise_one(cases[i])
            except Exception as e:                      # quota/API failure → stop cleanly
                print(f"  STOPPED at {i}/{len(cases)}: {type(e).__name__}: "
                      f"{str(e)[:120]} — rerun to resume.")
                return False
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
            f.flush()
    print(f"  {path}: complete ({len(cases)})")
    return True


def _stats(path: str) -> None:
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    stats = Counter((r["meta"]["tier"], r["meta"].get("realised", False)) for r in rows)
    for tier in dict.fromkeys(r["meta"]["tier"] for r in rows):
        print(f"    {tier:<18} realised {stats[(tier, True)]:>3} · "
              f"fallback {stats[(tier, False)]:>3}")


def main() -> None:
    n_wf2 = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    n_wf1 = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    which = sys.argv[3] if len(sys.argv) > 3 else "kimi"
    fn = make_gemini_realiser() if which == "gemini" else make_groq_realiser()
    print(f"realiser: {which}")

    p2 = os.path.join(DATASETS_DIR, "scheduling_realised.jsonl")
    ok2 = _resume_freeze(make_sched(n_per_tier=n_wf2), p2,
                         lambda c: realise_sched_case(c, fn))
    if ok2:
        _stats(p2)

    p1 = os.path.join(DATASETS_DIR, "triage_realised.jsonl")
    ok1 = _resume_freeze(make_triage(n_per_tier=n_wf1), p1,
                         lambda c: realise_thread_case(c, fn))
    if ok1:
        _stats(p1)


if __name__ == "__main__":  # pragma: no cover
    main()
