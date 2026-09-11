"""Validate the faithfulness judge (docs/evaluation.md §4) — the promise the spec makes.

Three steps, run in order:

    python -m backend.evals.run_judge_validation judge [n]   # costs quota (batched)
    #   → judges the same summaries with BOTH cross-family judges, reports their agreement,
    #     and writes data/eval_datasets/judge_labelling.jsonl for you to annotate
    #   ... you then fill in "human_supported": true/false in that file ...
    python -m backend.evals.run_judge_validation score        # pure code, re-runnable

Why two judges: Gemini (Google) and gpt-oss-120b (OpenAI) are both a different family from
the Llama generator, so both are legitimate. Their agreement is free evidence at any n, and
where they DISAGREE is the shortlist worth hand-labelling first — those items are where a
single judge's verdict is doing all the work.

Quota shape (measured 2026-07-27): Gemini free tier is 20 requests/day but 250K tokens/min,
so batching is what makes a usable n affordable. gpt-oss on Groq allows ~1000/day, so the
second judge is effectively free.
"""
import json
import os
import sys

from ..agent.extract import llm_extract
from ..config import LLM_MODEL
from ..evals.triage_data import POSITIONS, make_position_case
from .triage_score import llm_triage_extract
from . import results_store
from .faithfulness import (
    agreement_report,
    run_judges,
    score_human_labels,
    to_labelling_rows,
)

LABEL_PATH = "data/eval_datasets/judge_labelling.jsonl"
BATCH = 1        # batching relaxes the judge (faithfulness.BATCH_PROMPT) — never for published numbers
GEMINI = "gemini-2.5-flash"
GPT_OSS = "openai/gpt-oss-120b"


PAIRS_CACHE = "data/eval_cache/judge_pairs_n{n}.jsonl"


def _pairs(n: int) -> list[tuple[str, str]]:
    """The same (source, output) pairs the summary eval judges — reuse, don't re-invent.

    Checkpointed, like every other paid step in this harness: generating the summaries costs
    generator quota, and the judge step is the part that needs re-running (different judges,
    batched vs not, a second labelling pass). Without this the *inputs* were re-bought every
    time — which is how one afternoon's experiments exhausted the llama daily token budget.
    """
    path = PAIRS_CACHE.format(n=n)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        if len(rows) == n:
            print(f"reusing cached pairs ← {path}", flush=True)
            return [(r["source"], r["output"]) for r in rows]

    cases = [make_position_case(25, POSITIONS[i % len(POSITIONS)], seed=7000 + i)
             for i in range(n)]
    pairs = []
    for c in cases:
        e = llm_triage_extract(c, lambda wt, txt: llm_extract(wt, txt, None))
        pairs.append((c.raw_text,
                      (e.get("summary") or "") + "\n" + "\n".join(e.get("key_points") or [])))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for s, o in pairs:
            f.write(json.dumps({"source": s, "output": o}, ensure_ascii=False) + "\n")
    print(f"cached pairs → {path}", flush=True)
    return pairs


def _judges() -> dict:
    from .judges import make_gemini_judge, make_groq_judge
    js = {}
    if os.environ.get("GOOGLE_API_KEY"):
        js[GEMINI] = make_gemini_judge()
    else:
        print("! GOOGLE_API_KEY unset — skipping the Gemini judge", flush=True)
    js[GPT_OSS] = make_groq_judge(GPT_OSS)
    return js


def cmd_judge(n: int) -> None:
    pairs = _pairs(n)
    judges = _judges()
    print(f"judging {len(pairs)} pairs with {len(judges)} judge(s), batch={BATCH} "
          f"→ ~{-(-len(pairs) // BATCH)} requests each\n", flush=True)

    # judge ONCE; both the comparison and the labelling export read these same results
    def _dropped(name: str, err: Exception) -> None:
        kind = "daily quota exhausted" if "RESOURCE_EXHAUSTED" in str(err) else type(err).__name__
        print(f"! {name} dropped ({kind}) — continuing with the remaining judge(s)", flush=True)

    per_judge = run_judges(pairs, judges, batch_size=BATCH, on_error=_dropped)
    if not per_judge:
        sys.exit("every judge failed — nothing to report")
    report = agreement_report(per_judge, len(pairs))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    results_store.save_result("judge_validation", report, model=LLM_MODEL,
                              params={"n": len(pairs), "batch_size": BATCH,
                                      "judges": sorted(judges), "runner": "cli"})

    rows = to_labelling_rows(pairs, per_judge)
    os.makedirs(os.path.dirname(LABEL_PATH), exist_ok=True)
    with open(LABEL_PATH, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    disagreed = sorted({i for a in report["agreement"].values() for i in a["disagreed_on"]})
    print(f"\nwrote {len(rows)} rows → {LABEL_PATH}")
    print('Label each row\'s "human_supported": true if the OUTPUT contains a claim the '
          "SOURCE does not support, false otherwise.")
    if disagreed:
        print(f"Start with the rows the judges disagreed on: {disagreed}")


def cmd_score() -> None:
    if not os.path.exists(LABEL_PATH):
        sys.exit(f"{LABEL_PATH} not found — run the `judge` step first")
    with open(LABEL_PATH, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    names = sorted({k[len("judge_"):] for r in rows for k in r if k.startswith("judge_")})
    out = score_human_labels(rows, names)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    if out.get("n_labelled"):
        results_store.save_result("judge_kappa", out, model=LLM_MODEL,
                                  params={"n_labelled": out["n_labelled"],
                                          "judges": names, "runner": "cli"})
        print("\npersisted → data/eval_results/judge_kappa.jsonl")
        for name in names:
            k = out.get(name, {}).get("cohens_kappa")
            if k is not None and k < 0.6:
                print(f"! {name}: κ={k} is below the 0.6 the spec asks for — report its "
                      "faithfulness numbers as provisional (evaluation.md §4)")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "score"
    if cmd == "judge":
        cmd_judge(int(sys.argv[2]) if len(sys.argv) > 2 else 20)
    elif cmd == "score":
        cmd_score()
    else:
        sys.exit(f"unknown command: {cmd} (use: judge [n] | score)")


if __name__ == "__main__":  # pragma: no cover
    main()
