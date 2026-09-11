"""Full WF2 evaluation with the real LLM extractor. Requires GROQ_API_KEY.

    python -m backend.evals.run_scheduling_eval [n_per_tier]

Generates the synthetic test set, has the agent's LLM read each ``input_text`` (NOT the
gold), runs the deterministic validator, and reports per-tier metrics (docs/evaluation.md
§8): slot-extraction accuracy (the LLM's job) + date resolution / missing-field detection /
conflict detection / abstention. This is the offline harness with one function swapped, so
the numbers are directly comparable to the gold-as-extraction baseline.
"""
import sys

from ..agent.extract import llm_extract
from .scheduling_data import Case, make_dataset
from .scheduling_score import evaluate, format_report


def scheduling_extract(case: Case) -> dict:
    """The agent's LLM reads the message text — the real RQ2 condition."""
    return llm_extract("scheduling", case.input_text)


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    cases = make_dataset(n_per_tier=n)
    report = evaluate(cases, extract_fn=scheduling_extract)
    print(f"WF2 eval — LLM extractor (Llama-3.3-70B via Groq), {n}/tier:\n")
    print(format_report(report))


if __name__ == "__main__":
    main()
