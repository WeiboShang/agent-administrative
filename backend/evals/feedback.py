"""Feedback-conditioned prompting for WF1 — closing the loop on the reviewer's Dismiss.

The gate already records every dismissal; nothing ever read them back. Injecting a few as
few-shot negatives turns the human's decisions from *evaluation data* into a *control
signal*, without changing the architecture: this is prompt-layer conditioning, not
persistent agent memory (docs/workflow_design.md descoped the latter with the LangGraph prototype).
The agent still only proposes and the human still decides — the proposals just get better.

Two conditions are measured, because a single one cannot tell learning from memorising:

  in_family    — negatives drawn from the SAME δ family as the test item. They share a
                 sentence frame with it, so this is an upper bound on what the loop buys.
  cross_family — negatives drawn ONLY from the other δ families. If abstention improves
                 here, the model generalised "this kind of phrasing is not a request";
                 if it improves only in_family, it pattern-matched the frame.

Held-out seeds keep the negatives disjoint from every test case.
"""
from __future__ import annotations

from typing import Any

from .triage_data import PAIR_DELTAS, pair_minus_line

# far outside the seed range make_pair_dataset uses, so a negative is never a test item
NEGATIVE_SEED_BASE = 500_000
MODES = ("none", "in_family", "cross_family")


def negatives_for(delta: str, mode: str, k: int = 4,
                  seed_base: int = NEGATIVE_SEED_BASE) -> list[str]:
    """Held-out dismissed-style wordings to condition the prompt on, for one test δ."""
    if mode not in MODES:
        raise ValueError(f"unknown feedback mode: {mode}")
    if mode == "none":
        return []
    families = [delta] if mode == "in_family" else [d for d in PAIR_DELTAS if d != delta]
    # De-duplicate: the held-out vocabulary is small, so consecutive seeds can render the
    # same sentence. Repeating one example k times is not k examples — it would quietly
    # weaken the condition while the run still claims k.
    out: list[str] = []
    seen: set[str] = set()
    for i in range(k * 12):                       # ample headroom to find k distinct lines
        line = pair_minus_line(families[i % len(families)], seed_base + i * 7)
        if line not in seen:
            seen.add(line)
            out.append(line)
            if len(out) == k:
                break
    return out


def dismissed_spans(store: Any, k: int = 4) -> list[str]:
    """Production path: the wordings this workspace's reviewers actually dismissed.

    Most recent first, de-duplicated. Empty until someone has dismissed something — the loop
    starts cold by design, which is itself the honest behaviour to report.
    """
    spans: list[str] = []
    seen: set[str] = set()
    for rec in reversed(list(store.list("threads"))):
        for action in rec.data.get("detected_actions") or []:
            if action.get("status") != "dismissed":
                continue
            span = (action.get("source_span") or "").strip()
            if span and span.lower() not in seen:
                seen.add(span.lower())
                spans.append(span)
                if len(spans) >= k:
                    return spans
    return spans
