"""Faithfulness LLM-as-judge for the generative workflows WF1/WF4 (docs/evaluation.md §4).

Decomposes a generated OUTPUT into atomic claims and marks each supported/unsupported
against the SOURCE, yielding ``faithfulness = supported/total`` plus
``has_unsupported_claim`` — the safety-relevant flag the human-approval gate exists to
catch (a draft that invents a commitment the user never authorised).

The judge is a pluggable ``judge_fn(prompt) -> str`` returning the model's raw text. It
MUST be a different, at-least-as-strong model than the generator (Llama generates → Claude
judges) to avoid self-preference bias; validate it against human labels with
``cohens_kappa`` before trusting its scores. Offline tests use a stub judge — this module
imports no model client.
"""
import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

JudgeFn = Callable[[str], str]

FAITHFULNESS_PROMPT = """You are a strict fact-checker. Given a SOURCE message and a
generated OUTPUT, break the OUTPUT into atomic factual claims and decide, for each, whether
it is directly supported by the SOURCE. Do not use outside knowledge.

SOURCE:
{source}

OUTPUT:
{output}

Respond with JSON only, no prose:
{{"claims": [{{"claim": "<one fact>", "supported": true}}], "rationale": "<one sentence>"}}"""

# Batched variant — MEASURED AND REJECTED AS A DEFAULT (2026-07-27, results.md §2.2b).
#
# The motivation was sound: the free-tier constraint is requests per day (Gemini: 20), not
# tokens (250K TPM, ~2% used per judgement), so packing several items into one request should
# have bought ~5x the sample for the same quota. A controlled check on gpt-oss (same 20
# pairs, same judge, batched vs not) says otherwise: unsupported-rate **0.25 batched vs 0.50
# unbatched**, κ=0.30, raw agreement 0.65. Judging items in company makes the judge markedly
# more lenient — it decomposes each output more coarsely.
#
# So batching is opt-in, never the default: a quota saving that silently halves the
# safety-relevant rate is not a saving. Numbers from the two modes are NOT comparable, and
# every published faithfulness figure stays unbatched.
BATCH_PROMPT = """You are a strict fact-checker. For EACH numbered item below, break its
OUTPUT into atomic factual claims and decide, for each claim, whether it is directly
supported by that item's SOURCE. Judge each item independently. Do not use outside knowledge.

{items}

Respond with JSON only, no prose. Return one entry per item, keeping the given ids:
{{"items": [{{"id": 1, "claims": [{{"claim": "<one fact>", "supported": true}}],
"rationale": "<one sentence>"}}]}}"""

_ITEM_TEMPLATE = """--- ITEM {i} ---
SOURCE:
{source}

OUTPUT:
{output}
"""


@dataclass
class FaithfulnessResult:
    faithfulness: float | None  # unavailable for malformed output or no claims
    has_unsupported_claim: bool
    n_claims: int
    claims: list = field(default_factory=list)
    rationale: str = ""
    parse_status: str = "ok"  # ok | empty_claims | parse_error


def _parse(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {"claims": [], "rationale": "parse_error", "parse_status": "parse_error"}
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return {"claims": [], "rationale": "parse_error", "parse_status": "parse_error"}


def judge_faithfulness(source: str, output: str, judge_fn: JudgeFn) -> FaithfulnessResult:
    return _result_from(_parse(judge_fn(FAITHFULNESS_PROMPT.format(source=source,
                                                                   output=output))))


def _result_from(entry: dict) -> FaithfulnessResult:
    claims = [c for c in entry.get("claims", []) if isinstance(c, dict)]
    total = len(claims)
    supported = sum(1 for c in claims if c.get("supported") is True)
    parse_status = str(entry.get("parse_status") or ("ok" if total else "empty_claims"))
    return FaithfulnessResult(
        faithfulness=round(supported / total, 3) if total else None,
        has_unsupported_claim=any(c.get("supported") is not True for c in claims),
        n_claims=total,
        claims=claims,
        rationale=str(entry.get("rationale", "")),
        parse_status=parse_status,
    )


def judge_batch(pairs: list[tuple[str, str]], judge_fn: JudgeFn) -> list[FaithfulnessResult]:
    """Judge several pairs in ONE request; fall back to per-pair on any malformed reply.

    The fallback is not optional. A batch that half-parses would silently drop or misalign
    judgements, and a shifted id would attach one item's claims to another's source — a
    quiet corruption of the very numbers the judge exists to produce. Costing one extra
    request to re-do a bad batch is the cheap side of that trade.
    """
    if not pairs:
        return []
    items = "\n".join(_ITEM_TEMPLATE.format(i=i + 1, source=s, output=o)
                      for i, (s, o) in enumerate(pairs))
    data = _parse(judge_fn(BATCH_PROMPT.format(items=items)))
    entries = data.get("items")
    if isinstance(entries, list) and len(entries) == len(pairs):
        by_id = {e.get("id"): e for e in entries if isinstance(e, dict)}
        if set(by_id) == set(range(1, len(pairs) + 1)):
            return [_result_from(by_id[i + 1]) for i in range(len(pairs))]
    return [judge_faithfulness(s, o, judge_fn) for s, o in pairs]


def judge_all(pairs: list[tuple[str, str]], judge_fn: JudgeFn,
              batch_size: int = 1) -> list[FaithfulnessResult]:
    """Per-pair results for the whole set, ``batch_size`` items per request.

    Defaults to 1 (one request per pair) because batching measurably relaxes the judge —
    see BATCH_PROMPT. Raise it only when a shifted absolute rate is acceptable.
    """
    if batch_size <= 1:
        return [judge_faithfulness(s, o, judge_fn) for s, o in pairs]
    out: list[FaithfulnessResult] = []
    for i in range(0, len(pairs), batch_size):
        out.extend(judge_batch(pairs[i:i + batch_size], judge_fn))
    return out


def aggregate_faithfulness(results: list[FaithfulnessResult]) -> dict:
    """Aggregate scored judgements and expose unavailable cases explicitly."""
    scored = [r for r in results if r.faithfulness is not None]
    return {
        "mean_faithfulness": (
            round(sum(r.faithfulness for r in scored) / len(scored), 3)
            if scored else None),
        "unsupported_rate": (
            round(sum(r.has_unsupported_claim for r in scored) / len(scored), 3)
            if scored else None),
        "n": len(results),
        "n_scored": len(scored),
        "parse_failures": sum(r.parse_status == "parse_error" for r in results),
        "empty_claims": sum(r.parse_status == "empty_claims" for r in results),
    }


def evaluate_faithfulness(pairs: list[tuple[str, str]], judge_fn: JudgeFn,
                          batch_size: int = 1) -> dict:
    """Aggregate faithfulness over ``(source, output)`` pairs (docs/evaluation.md §8).

    One request per pair by default: batching is cheaper but not verdict-preserving
    (BATCH_PROMPT), and these are the published numbers.
    """
    return aggregate_faithfulness(judge_all(pairs, judge_fn, batch_size))


def cohens_kappa(judge_labels: list, human_labels: list) -> float:
    """Cohen's κ for two binary label sequences — judge-vs-human agreement
    (docs/evaluation.md §4: only trust the judge when κ is acceptable, e.g. ≳ 0.6)."""
    n = len(judge_labels)
    if n == 0 or n != len(human_labels):
        raise ValueError("label sequences must be non-empty and equal length")
    a = [1 if x else 0 for x in judge_labels]
    b = [1 if x else 0 for x in human_labels]
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    if pe == 1.0:
        return 1.0
    return round((po - pe) / (1 - pe), 3)


# ── Judge validation (docs/evaluation.md §4) ─────────────────────────────────────────
# "Validate the judge before trusting it" is a promise the spec makes and the numbers rest
# on: every faithfulness figure is only as good as the judge that produced it. Two
# independent checks, neither of which trains or changes the judge:
#   1. judge-vs-HUMAN agreement (Cohen's κ) — the authority. Needs hand labels.
#   2. judge-vs-JUDGE agreement — free, and available at any n. Two cross-family judges
#      agreeing is weak evidence of correctness but strong evidence against one model's
#      idiosyncrasy; disagreement localises exactly which items to hand-label first.

def run_judges(pairs: list[tuple[str, str]], judges: dict[str, JudgeFn],
               batch_size: int = 1,
               on_error: Optional[Callable[[str, Exception], None]] = None,
               ) -> dict[str, list[FaithfulnessResult]]:
    """Judge the same pairs with each judge. Call this ONCE and reuse the results — judging
    is the only step that costs quota, and a caller that both compares and exports must not
    pay for it twice.

    A judge that fails (typically a daily quota cut-off — Gemini's free tier is 20
    requests/day, which one unbatched n=20 run consumes exactly) is **dropped, not fatal**:
    losing the second opinion should not throw away the first judge's completed work.
    """
    out: dict[str, list[FaithfulnessResult]] = {}
    for name, fn in judges.items():
        try:
            out[name] = judge_all(pairs, fn, batch_size)
        except Exception as e:  # noqa: BLE001 — provider errors are the expected case here
            if on_error:
                on_error(name, e)
            else:
                raise
    return out


def agreement_report(per_judge: dict[str, list[FaithfulnessResult]], n: int) -> dict:
    """Report each judge and their pairwise agreement, from already-computed results.

    Agreement is computed on ``has_unsupported_claim`` — the binary, safety-relevant label
    the approval gate actually acts on. Claim-level agreement is not comparable across
    judges because each decomposes the output into its own claims.
    """
    report: dict = {"n": n,
                    "judges": {name: aggregate_faithfulness(rs)
                               for name, rs in per_judge.items()}}
    names = sorted(per_judge)
    agreement = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            la = [r.has_unsupported_claim for r in per_judge[a]]
            lb = [r.has_unsupported_claim for r in per_judge[b]]
            agreement[f"{a} vs {b}"] = {
                "cohens_kappa": cohens_kappa(la, lb),
                "raw_agreement": round(sum(x == y for x, y in zip(la, lb)) / len(la), 3)
                if la else None,
                "disagreed_on": [i for i, (x, y) in enumerate(zip(la, lb)) if x != y],
            }
    report["agreement"] = agreement
    return report


def compare_judges(pairs: list[tuple[str, str]], judges: dict[str, JudgeFn],
                   batch_size: int = 1) -> dict:
    """Convenience: judge once, then report. Use run_judges + agreement_report when you
    also need the per-item results (e.g. to export them for hand-labelling)."""
    return agreement_report(run_judges(pairs, judges, batch_size), len(pairs))


def to_labelling_rows(pairs: list[tuple[str, str]],
                      results: dict[str, list[FaithfulnessResult]]) -> list[dict]:
    """Flatten judged pairs into one row per item for hand-labelling.

    ``human_supported`` is left ``null`` for the annotator to fill with true/false. The
    judges' own labels ARE included: hiding them would be the more rigorous design, but the
    annotator here is the author, who has already read these numbers — pretending otherwise
    would be theatre. State the limitation instead (results.md), and note that the labels
    being visible biases κ *upward*, so a low κ is still trustworthy.
    """
    rows = []
    for i, (source, output) in enumerate(pairs):
        row = {"i": i, "source": source, "output": output, "human_supported": None}
        for name, rs in results.items():
            r = rs[i]
            row[f"judge_{name}"] = r.has_unsupported_claim
            row[f"claims_{name}"] = [
                {"claim": c.get("claim"), "supported": c.get("supported")} for c in r.claims
            ]
        rows.append(row)
    return rows


def score_human_labels(rows: list[dict], judge_names: list[str]) -> dict:
    """κ of each judge against the human labels, over the rows that were labelled.

    ``human_supported`` is the human's answer to the same question the judge answered:
    "does this output contain an unsupported claim?" — true means it does.
    """
    labelled = [r for r in rows if isinstance(r.get("human_supported"), bool)]
    if not labelled:
        return {"n_labelled": 0, "error": "no rows have a boolean human_supported yet"}
    human = [r["human_supported"] for r in labelled]
    out: dict = {"n_labelled": len(labelled), "n_total": len(rows),
                 "human_unsupported_rate": round(sum(human) / len(human), 3)}
    for name in judge_names:
        key = f"judge_{name}"
        if not all(key in r for r in labelled):
            continue
        judged = [bool(r[key]) for r in labelled]
        out[name] = {
            "cohens_kappa": cohens_kappa(judged, human),
            "raw_agreement": round(sum(x == y for x, y in zip(judged, human))
                                   / len(human), 3),
            "judge_unsupported_rate": round(sum(judged) / len(judged), 3),
        }
    return out
