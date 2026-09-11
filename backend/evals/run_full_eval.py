"""Server-independent bulk eval runner with rate-limit backoff — final-number collection.

The HTTP endpoints suit small interactive runs; bulk runs hit per-minute token limits
(TPM) and outlive request timeouts. This runner rides out 429s (sleeps the provider's
suggested wait) and appends the result to data/eval_results/ like the endpoints do.

    python -m backend.evals.run_full_eval scheduling --model openai/gpt-oss-120b --dataset realised
    python -m backend.evals.run_full_eval triage    --n 10
    python -m backend.evals.run_full_eval position  --n 3 --model openai/gpt-oss-120b
"""
import argparse
import json
import re
import time

from .results_store import save_result


def _retrying(fn, max_tries: int = 10):
    def wrapped(*a, **k):
        for t in range(max_tries):
            try:
                return fn(*a, **k)
            except Exception as e:  # noqa: BLE001 — provider errors vary by SDK
                s = str(e)
                if "429" not in s or t == max_tries - 1:
                    raise
                m = re.search(r"try again in (?:(\d+)m)?([0-9.]+)s", s)
                wait = (min(int(m.group(1) or 0) * 60 + float(m.group(2)) + 2, 900)
                        if m else 20.0)
                print(f"    429 — waiting {wait:.0f}s", flush=True)
                time.sleep(wait)
        return None
    return wrapped


CACHE_DIR = "data/eval_cache"


def _checkpointed(cases: list, cache_key: str, call) -> list[dict]:
    """LLM-extract each case with a per-case on-disk checkpoint — a quota cut-off or
    crash never loses paid extractions; rerunning skips everything already cached.
    The cache files double as the raw model outputs for error analysis."""
    import os
    path = os.path.join(CACHE_DIR, cache_key + ".jsonl")
    os.makedirs(CACHE_DIR, exist_ok=True)
    cached: dict[int, dict] = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    e = json.loads(line)
                    cached[e["i"]] = e["x"]
    out: list[dict] = []
    with open(path, "a", encoding="utf-8") as f:
        for i, case in enumerate(cases):
            if i in cached:
                out.append(cached[i])
                continue
            x = call(case)
            f.write(json.dumps({"i": i, "x": x}, ensure_ascii=False) + "\n")
            f.flush()
            out.append(x)
            print(f"    {i + 1}/{len(cases)}", flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow",
                    choices=["scheduling", "triage", "position", "pairs", "retraction",
                             "underspecified"])
    ap.add_argument("--feedback", default="none",
                    choices=["none", "in_family", "cross_family"],
                    help="pairs only: condition the prompt on held-out dismissed wordings")
    ap.add_argument("--k", type=int, default=4, help="how many negatives to inject")
    ap.add_argument("--model", default=None)
    ap.add_argument("--dataset", default="template", choices=["template", "realised"])
    ap.add_argument("--n", type=int, default=10)
    args = ap.parse_args()

    from ..agent.extract import llm_extract
    from ..config import LLM_MODEL
    model = args.model or LLM_MODEL
    ex = _retrying(lambda wt, txt: llm_extract(wt, txt, args.model))
    ex_neg = _retrying(lambda wt, txt, negs: llm_extract(wt, txt, args.model, negatives=negs))
    slug = model.replace("/", "-")
    key = f"{args.workflow}_{slug}_{args.dataset}" + \
          ("" if args.dataset == "realised" else f"_n{args.n}")
    # the feedback condition CHANGES the prompt, so it must partition the cache — otherwise
    # a variant run would silently replay the baseline's cached extractions
    if args.workflow == "pairs" and args.feedback != "none":
        key += f"_fb-{args.feedback}-k{args.k}"

    if args.workflow == "scheduling":
        from .scheduling_data import make_dataset
        from .scheduling_score import evaluate, format_report
        if args.dataset == "realised":
            from .realiser import load_sched_cases
            cases = load_sched_cases("data/eval_datasets/scheduling_realised.jsonl")
        else:
            cases = make_dataset(n_per_tier=args.n)
        print(f"scheduling · {len(cases)} cases · model={model} · dataset={args.dataset}",
              flush=True)
        xs = _checkpointed(cases, key, lambda c: ex("scheduling", c.input_text))
        by_id = {id(c): x for c, x in zip(cases, xs)}
        report = evaluate(cases, lambda c: by_id[id(c)])
        print(format_report(report))
        result = {"scheduling": report}
    elif args.workflow == "triage":
        from .triage_data import make_dataset as make_triage
        from .triage_score import evaluate, llm_triage_extract
        if args.dataset == "realised":
            from .realiser import load_thread_cases
            cases = load_thread_cases("data/eval_datasets/triage_realised.jsonl")
        else:
            cases = make_triage(n_per_tier=args.n)
        print(f"triage · {len(cases)} cases · model={model} · dataset={args.dataset}",
              flush=True)
        xs = _checkpointed(cases, key, lambda c: llm_triage_extract(c, ex))
        by_id = {id(c): x for c, x in zip(cases, xs)}
        result = evaluate(cases, lambda c: by_id[id(c)])
        print(json.dumps(result, indent=1))
    elif args.workflow == "pairs":
        from .triage_data import make_pair_dataset
        from .triage_score import evaluate_pairs, llm_triage_extract
        pairs = make_pair_dataset(n_per_delta=args.n)
        # _checkpointed works on a flat list, so flatten the twins and re-pair by identity
        flat = [c for pair in pairs for c in pair]
        from .feedback import negatives_for
        from ..workflows.triage import validate_triage
        print(f"pairs · {len(pairs)} twins ({len(flat)} threads) · model={model} "
              f"· feedback={args.feedback}", flush=True)

        def call(c):
            negs = negatives_for(c.meta["delta"], args.feedback, k=args.k)
            return validate_triage(ex_neg("triage", c.raw_text, negs))

        xs = _checkpointed(flat, key, call)
        by_id = {id(c): x for c, x in zip(flat, xs)}
        result = evaluate_pairs(pairs, lambda c: by_id[id(c)])
        print(json.dumps(result, indent=1))
    elif args.workflow == "retraction":
        from .triage_data import make_retraction_dataset, make_thread_case
        from .triage_score import evaluate_retraction, llm_triage_extract
        cases = make_retraction_dataset(n_per_distance=args.n)
        # genuine, non-retracted meeting threads — the flag must NOT fire on these
        controls = [make_thread_case("meeting", seed=90000 + i) for i in range(args.n)]
        print(f"retraction · {len(cases)} cases + {len(controls)} controls · model={model}",
              flush=True)
        xs = _checkpointed(cases + controls, key, lambda c: llm_triage_extract(c, ex))
        by_id = {id(c): x for c, x in zip(cases + controls, xs)}
        result = evaluate_retraction(cases, lambda c: by_id[id(c)], control_cases=controls)
        print(json.dumps(result, indent=1))
    elif args.workflow == "underspecified":
        from .triage_data import make_underspecified_dataset
        from .triage_score import evaluate_underspecified, llm_triage_extract
        cases = make_underspecified_dataset(n=args.n)
        print(f"underspecified · {len(cases)} cases · model={model}", flush=True)
        xs = _checkpointed(cases, key, lambda c: llm_triage_extract(c, ex))
        by_id = {id(c): x for c, x in zip(cases, xs)}
        result = evaluate_underspecified(cases, lambda c: by_id[id(c)])
        print(json.dumps(result, indent=1))
    else:
        from .triage_data import make_position_dataset
        from .triage_score import evaluate_position, llm_triage_extract
        cases = make_position_dataset(n_per_cell=args.n)
        print(f"position · {len(cases)} cases · model={model}", flush=True)
        xs = _checkpointed(cases, key, lambda c: llm_triage_extract(c, ex))
        by_id = {id(c): x for c, x in zip(cases, xs)}
        result = evaluate_position(cases, lambda c: by_id[id(c)])
        print(json.dumps(result, indent=1))

    params = {"n": args.n, "dataset": args.dataset, "runner": "cli"}
    name = args.workflow
    if args.workflow == "pairs" and args.feedback != "none":
        params.update({"feedback": args.feedback, "k": args.k})
        name = f"pairs_fb_{args.feedback}"      # keep the baseline's record intact
    save_result(name, result, model=model, params=params)
    print("saved to data/eval_results/")


if __name__ == "__main__":  # pragma: no cover
    main()
