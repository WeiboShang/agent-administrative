"""Evaluation API — decision audit log (RQ3: M4/M5) + on-demand receipt eval (M1/M3/M6).

`/audit` reads the shared live store (decisions made in the Expenses page). `/receipts`
runs the synthetic receipt eval on a *fresh seeded* store (isolated from live state, so
results are reproducible); it makes live vision calls, run in a threadpool.
"""

import asyncio
import os
from collections import Counter
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import money
from ..agent.extract import llm_extract
from ..agent.vision_extract import extract_receipt
from ..backends.records import RecordStore
from ..evals.receipt_data import write_dataset
from ..evals.receipt_score import evaluate, load_manifest
from ..config import LLM_MODEL, VISION_MODEL
from ..evals import results_store
from ..evals.final_part_a import (
    build_verification_cases as build_final_part_a_cases,
    latest_formal_scores as latest_final_part_a_scores,
    render as render_final_part_a,
)
from ..evals.faithfulness import evaluate_faithfulness
from ..evals.scheduling_data import make_dataset as make_sched_dataset
from ..evals.scheduling_score import evaluate as sched_evaluate
from ..evals.triage_data import POSITIONS, make_position_case, make_position_dataset
from ..evals.triage_data import make_dataset as make_triage_dataset
from ..evals.triage_score import evaluate as triage_evaluate
from ..evals.triage_score import evaluate_position, llm_triage_extract, summary_coverage
from ..fixtures import org
from ._store import store

router = APIRouter(prefix="/api/eval")

_DATASET = "data/receipts/synthetic"

# Last result per eval, hydrated from the on-disk run log so it survives restarts
# (results_store appends every run to data/eval_results/<name>.jsonl).
_LAST: dict[str, dict[str, Any]] = results_store.load_latest()


def _remember(
    name: str,
    result: dict[str, Any],
    *,
    model: Optional[str] = None,
    params: Optional[dict] = None,
    result_status: str = "legacy_pilot",
) -> dict[str, Any]:
    _LAST[name] = results_store.save_result(
        name, result, model=model, params=params, result_status=result_status
    )
    return result


@router.get("/last")
async def last_results() -> dict[str, Any]:
    """Most recent result per eval (persisted across restarts; see results_store)."""
    return _LAST


@router.get("/v3.4.3/formal/latest")
async def latest_v343_formal_outcomes() -> dict[str, Any]:
    """Return V3.4.3 formal scores only; never fall back to older protocols."""
    entries = results_store.formal_v343_entries()
    if not entries:
        raise HTTPException(status_code=404, detail="no formal V3.4.3 outcome run recorded")
    scores = entries[-1].get("result", {}).get("scores")
    if not isinstance(scores, dict):
        raise HTTPException(status_code=500, detail="formal V3.4.3 record has no scores")
    return scores


@router.get("/part-a/final/latest")
async def latest_part_a_final_outcomes() -> dict[str, Any]:
    """Return Part A Final: WF1/WF3 V3.4.3 plus authoritative WF2 V3.5."""
    try:
        return await asyncio.to_thread(latest_final_part_a_scores)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _rate(a: int, b: int) -> float:
    return round(a / b, 2) if b else 0.0


def _to_bars(counter: Counter, money: bool = False) -> list[dict[str, Any]]:
    return [
        {"label": k, "value": round(v, 2) if money else v}
        for k, v in counter.most_common()
    ]


@router.get("/audit")
async def audit() -> dict[str, Any]:
    """HITL-process metrics (RQ3: M4/M5) + spend analytics, from the shared live store.

    In the two-role model a "decision" is an approver's final approve/reject on a submitted
    claim; edit-distance (M5) is captured from the employee's edits at submit time.
    """
    decisions = [
        r
        for r in store.list("submissions", record_type="expense_claim")
        if r.status in ("approved", "rejected")
    ]
    rows: list[dict] = []
    approved = rejected = edited = overrode = purpose_refined = 0
    flagged = flagged_appr = unflagged = unflagged_appr = 0
    corrections: Counter = Counter()
    overrides: Counter = Counter()
    for r in decisions:
        d = r.data
        changed = d.get("changed_fields", [])
        ov_rules = [f["rule"] for f in d.get("overridden_flags", [])]
        is_appr = r.status == "approved"
        rows.append(
            {
                "id": r.id,
                "status": r.status,
                "employee": d.get("employee_name"),
                "reviewed_by": d.get("reviewed_by"),
                "vendor": d.get("vendor"),
                "amount": d.get("amount"),
                # currency + GBP so the table can show the receipt's own figure honestly
                # alongside the comparable value
                "currency": d.get("currency"),
                "amount_gbp": money.gbp_of(d),
                "overridden_flags": ov_rules,
                "changed_fields": changed,
                "reason": d.get("decision_reason"),
            }
        )
        approved += is_appr
        rejected += r.status == "rejected"
        edited += bool(changed)
        overrode += bool(ov_rules)
        purpose_refined += "business_purpose" in changed
        corrections.update(changed)
        overrides.update(ov_rules)
        if d.get("policy_flags"):
            flagged += 1
            flagged_appr += is_appr
        else:
            unflagged += 1
            unflagged_appr += is_appr

    # Spend analytics over ALL approved claims (incl. seeds), by category + charged dept.
    # Summed in GBP: claims can be in any supported currency, so adding raw amounts would
    # mix scales (one approved ¥17,000 receipt ≈ £78 would otherwise add 17,000 to a
    # department whose entire budget is £2,000). Unconvertible claims are *excluded and
    # counted* rather than contributing a wrong-scale bar. Current workflow validation
    # blocks new unknown-currency approvals; this count exposes any historical rows.
    spend_cat: Counter = Counter()
    spend_dep: Counter = Counter()
    unconverted = 0
    for r in store.list("submissions", record_type="expense_claim", status="approved"):
        d = r.data
        amt = money.gbp_of(d)
        if amt is None:
            unconverted += 1
            continue
        spend_cat[d.get("category") or "—"] += amt
        person = org.find_person(d.get("employee_name", ""))
        spend_dep[d.get("department") or (person.department if person else "—")] += amt

    n = len(decisions)
    return {
        "metrics": {
            "total": n,
            "approved": approved,
            "rejected": rejected,
            "edit_rate": _rate(edited, n),
            "override_rate": _rate(overrode, n),
            "purpose_refined_rate": _rate(purpose_refined, n),
            "flag_influence": {
                "with_flag_approve_rate": _rate(flagged_appr, flagged),
                "without_flag_approve_rate": _rate(unflagged_appr, unflagged),
                "n_with_flag": flagged,
                "n_without_flag": unflagged,
            },
        },
        "charts": {
            "corrections_by_field": _to_bars(corrections),
            "overrides_by_rule": _to_bars(overrides),
            "spend_by_category": _to_bars(spend_cat, money=True),
            "spend_by_department": _to_bars(spend_dep, money=True),
        },
        # spend charts are GBP-converted; say so, and admit anything left out
        "spend_currency": "GBP",
        "spend_excluded_unconvertible": unconverted,
        "rows": list(reversed(rows)),
    }


class ReceiptEvalRequest(BaseModel):
    n: int = 2


@router.post("/receipts")
async def receipts(req: ReceiptEvalRequest) -> dict[str, Any]:
    manifest_path = os.path.join(_DATASET, "manifest.jsonl")
    if not os.path.exists(manifest_path):
        write_dataset(_DATASET, n_per_tier=req.n)
    entries = load_manifest(manifest_path)

    def run() -> dict:
        fresh = RecordStore(":memory:")
        org.seed_from_org(fresh)

        def vision(entry: dict) -> dict:
            return extract_receipt(
                os.path.join(_DATASET, entry["image"]), mime="image/png"
            )

        return evaluate(entries, vision, fresh)

    return _remember(
        "receipts",
        await asyncio.to_thread(run),
        model=VISION_MODEL,
        params={"n": req.n},
    )


def _load_frozen(kind: str):
    from ..evals.realiser import DATASETS_DIR, load_sched_cases, load_thread_cases

    path = os.path.join(DATASETS_DIR, f"{kind}_realised.jsonl")
    if not os.path.exists(path):
        raise HTTPException(
            404,
            f"No frozen realised dataset at {path} — "
            "run `python -m backend.evals.realise_datasets` first.",
        )
    return load_sched_cases(path) if kind == "scheduling" else load_thread_cases(path)


class TriageEvalRequest(BaseModel):
    n: int = 3
    model: Optional[str] = None  # RQ2 comparison: e.g. "openai/gpt-oss-120b"
    dataset: str = "template"  # "realised" = frozen LLM-realised file


@router.post("/triage")
async def triage_eval(req: TriageEvalRequest) -> dict[str, Any]:
    cases = (
        _load_frozen("triage")
        if req.dataset == "realised"
        else make_triage_dataset(n_per_tier=req.n)
    )

    def ex(wt: str, txt: str) -> dict:
        return llm_extract(wt, txt, req.model)

    def run() -> dict:
        return triage_evaluate(cases, lambda c: llm_triage_extract(c, ex))

    return _remember(
        "triage",
        await asyncio.to_thread(run),
        model=req.model or LLM_MODEL,
        params={"n": req.n, "dataset": req.dataset},
    )


@router.post("/date_resolution")
async def date_resolution_eval() -> dict[str, Any]:
    """WF2 date resolution against HAND-AUTHORED gold — breaks the generator's circularity.
    Pure code: no model call, no quota, instant."""
    from ..evals.date_resolution import evaluate_date_resolution

    return _remember(
        "date_resolution", evaluate_date_resolution(), model="deterministic"
    )


class PairsEvalRequest(BaseModel):
    n: int = 4  # twins per δ family → 2×n threads each
    model: Optional[str] = None


@router.post("/pairs")
async def pairs_eval(req: PairsEvalRequest) -> dict[str, Any]:
    """Minimal-pair abstention: each case has a twin differing by one controlled δ."""
    from ..evals.triage_data import make_pair_dataset
    from ..evals.triage_score import evaluate_pairs

    pairs = make_pair_dataset(n_per_delta=req.n)

    def ex(wt: str, txt: str) -> dict:
        return llm_extract(wt, txt, req.model)

    def run() -> dict:
        return evaluate_pairs(pairs, lambda c: llm_triage_extract(c, ex))

    return _remember(
        "pairs",
        await asyncio.to_thread(run),
        model=req.model or LLM_MODEL,
        params={"n": req.n},
    )


class RetractionEvalRequest(BaseModel):
    n: int = 4
    model: Optional[str] = None


@router.post("/retraction")
async def retraction_eval(req: RetractionEvalRequest) -> dict[str, Any]:
    """A fully-specified plan that the thread later calls off: does the model abstain, and
    if not, does the deterministic check recover it (without firing on healthy threads)?"""
    from ..evals.triage_data import make_retraction_dataset, make_thread_case
    from ..evals.triage_score import evaluate_retraction

    cases = make_retraction_dataset(n_per_distance=req.n)
    controls = [make_thread_case("meeting", seed=90000 + i) for i in range(req.n)]

    def ex(wt: str, txt: str) -> dict:
        return llm_extract(wt, txt, req.model)

    def run() -> dict:
        return evaluate_retraction(
            cases, lambda c: llm_triage_extract(c, ex), control_cases=controls
        )

    return _remember(
        "retraction",
        await asyncio.to_thread(run),
        model=req.model or LLM_MODEL,
        params={"n": req.n},
    )


class UnderspecifiedEvalRequest(BaseModel):
    n: int = 6
    model: Optional[str] = None


@router.post("/underspecified")
async def underspecified_eval(req: UnderspecifiedEvalRequest) -> dict[str, Any]:
    """A real request with no slot and no attendees: does the model invent the missing parts?"""
    from ..evals.triage_data import make_underspecified_dataset
    from ..evals.triage_score import evaluate_underspecified

    cases = make_underspecified_dataset(n=req.n)

    def ex(wt: str, txt: str) -> dict:
        return llm_extract(wt, txt, req.model)

    def run() -> dict:
        return evaluate_underspecified(cases, lambda c: llm_triage_extract(c, ex))

    return _remember(
        "underspecified",
        await asyncio.to_thread(run),
        model=req.model or LLM_MODEL,
        params={"n": req.n},
    )


class PositionEvalRequest(BaseModel):
    n: int = 2  # cases per (length × position) cell → 3×3×n LLM calls
    model: Optional[str] = None


@router.post("/position")
async def position_eval(req: PositionEvalRequest) -> dict[str, Any]:
    """Needle-in-a-haystack: recall + summary coverage per (thread length × position)."""
    cases = make_position_dataset(n_per_cell=req.n)

    def ex(wt: str, txt: str) -> dict:
        return llm_extract(wt, txt, req.model)

    def run() -> dict:
        return evaluate_position(cases, lambda c: llm_triage_extract(c, ex))

    return _remember(
        "position",
        await asyncio.to_thread(run),
        model=req.model or LLM_MODEL,
        params={"n": req.n},
    )


class SummaryEvalRequest(BaseModel):
    n: int = 4
    judge: str = "gemini"  # judge ≠ generator, cross-family: gemini | claude | groq
    model: Optional[str] = None


def _make_judge(kind: str):
    """Pick the strongest available cross-family judge; returns (judge_fn, name)."""
    from ..evals.judges import make_claude_judge, make_gemini_judge, make_groq_judge

    if kind == "gemini" and os.environ.get("GOOGLE_API_KEY"):
        return make_gemini_judge(), "gemini-2.5-flash"
    if kind == "claude" and os.environ.get("ANTHROPIC_API_KEY"):
        return make_claude_judge(), "claude-opus-4-8"
    return (
        make_groq_judge("openai/gpt-oss-120b"),
        "gpt-oss-120b (fallback — set GOOGLE_API_KEY or ANTHROPIC_API_KEY)",
    )


@router.post("/summary")
async def summary_eval(req: SummaryEvalRequest) -> dict[str, Any]:
    """Summary quality: gold-fact coverage (code) + faithfulness (LLM-as-judge)."""
    cases = [
        make_position_case(25, POSITIONS[i % len(POSITIONS)], seed=7000 + i)
        for i in range(req.n)
    ]

    def run() -> dict:
        extracted = [
            (c, llm_triage_extract(c, lambda wt, txt: llm_extract(wt, txt, req.model)))
            for c in cases
        ]
        covs = [v for c, e in extracted if (v := summary_coverage(c, e)) is not None]
        pairs = [
            (
                c.raw_text,
                (e.get("summary") or "") + "\n" + "\n".join(e.get("key_points") or []),
            )
            for c, e in extracted
        ]
        judge, judge_name = _make_judge(req.judge)
        return {
            "n": len(cases),
            "judge": judge_name,
            "generator": req.model or LLM_MODEL,
            "coverage": round(sum(covs) / len(covs), 3) if covs else None,
            "faithfulness": evaluate_faithfulness(pairs, judge),
        }

    return _remember(
        "summary",
        await asyncio.to_thread(run),
        model=req.model or LLM_MODEL,
        params={"n": req.n, "judge": req.judge},
    )


class ContentEvalRequest(BaseModel):
    n: int = 8
    judge: str = "gemini"
    model: Optional[str] = None


@router.post("/content")
async def content_eval(req: ContentEvalRequest) -> dict[str, Any]:
    """O4 decision-note eval: fact coverage (code) + faithfulness (LLM-as-judge)."""
    from ..evals.content_score import evaluate_content

    def run() -> dict:
        judge, judge_name = _make_judge(req.judge)
        result = evaluate_content(req.n, judge_fn=judge, model=req.model)
        result["judge"] = judge_name
        result["generator"] = req.model or LLM_MODEL
        return result

    return _remember(
        "content",
        await asyncio.to_thread(run),
        model=req.model or LLM_MODEL,
        params={"n": req.n, "judge": req.judge},
    )


class M4Request(BaseModel):
    n: int = 60
    error_rate: float = 0.5


@router.post("/m4")
async def m4_eval(req: M4Request) -> dict[str, Any]:
    """M4 scripted-reviewer simulation (blind / flag-following / ideal). No LLM calls."""
    from ..evals.reviewer_sim import evaluate_m4

    result = evaluate_m4(n=req.n, error_rate=req.error_rate)
    return _remember(
        "m4",
        result,
        model="scripted-reviewers",
        params={"n": req.n, "error_rate": req.error_rate},
    )


class SchedEvalRequest(BaseModel):
    n: int = 4
    model: Optional[str] = None
    dataset: str = "template"  # "realised" = frozen LLM-realised file


@router.post("/scheduling")
async def scheduling_eval(req: SchedEvalRequest) -> dict[str, Any]:
    cases = (
        _load_frozen("scheduling")
        if req.dataset == "realised"
        else make_sched_dataset(n_per_tier=req.n)
    )

    def run() -> dict:
        return {
            "scheduling": sched_evaluate(
                cases, lambda c: llm_extract("scheduling", c.input_text, req.model)
            )
        }

    return _remember(
        "scheduling",
        await asyncio.to_thread(run),
        model=req.model or LLM_MODEL,
        params={"n": req.n, "dataset": req.dataset},
    )


@router.post("/part-a/final/replay")
async def replay_part_a_final_outcomes() -> dict[str, Any]:
    """Offline verification of the final mixed-version evidence boundary."""
    cases = await asyncio.to_thread(build_final_part_a_cases)
    return await asyncio.to_thread(render_final_part_a, cases)
