"""Formal-only reporting for Evaluation v3 outcomes.

Historical component files remain readable through ``report.py``.  This module intentionally
reads only explicitly labelled formal v3 records, so legacy M1--M7 values cannot leak into
headline outcome aggregates.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .outcomes_v3 import EvalCase, score_case
from .results_store import formal_v3_entries
from .review_metrics_v3 import evaluate_review_metrics
from .stats import wilson_ci


def _proportion(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    n = len(rows)
    k = sum(bool(row.get(key)) for row in rows)
    if not n:
        return {"numerator": 0, "denominator": 0, "rate": None, "wilson_95": None}
    return {"numerator": k, "denominator": n, "rate": round(k / n, 3),
            "wilson_95": wilson_ci(k, n)}


def _diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, dict[str, list[Any]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for row in rows:
        for name, value in (row.get("diagnostics") or {}).items():
            grouped[row["workflow"]][row["condition"]][row["scenario_tier"]].setdefault(name, []).append(value)
    return {wf: {condition: {tier: dict(values) for tier, values in tiers.items()} for condition, tiers in conditions.items()} for wf, conditions in grouped.items()}


def _review_metrics(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate review value/effort and keep reviewer populations separate."""
    cases = [EvalCase.model_validate(raw) for entry in entries
             for raw in entry.get("result", {}).get("cases", [])]
    scores = [score_case(case) for case in cases]
    boundary = (
        "gold-free deterministic transition analysis; not human evidence"
        if any(entry.get("result_status") in {
            "v3_3_formal", "v3_4_formal", "v3_4_1_formal", "v3_4_2_formal",
            "v3_4_3_formal",
        }
               for entry in entries)
        else "oracle-assisted simulated upper bound; not human evidence"
    )
    by_reviewer_type = {}
    for reviewer_type in sorted({case.reviewer_type for case in cases}):
        selected = [(case, score) for case, score in zip(cases, scores)
                    if case.reviewer_type == reviewer_type]
        by_reviewer_type[reviewer_type] = evaluate_review_metrics(
            [case for case, _ in selected],
            [score for _, score in selected],
            evidence_boundary=boundary,
        )
    return {
        "overall": evaluate_review_metrics(
            cases, scores, evidence_boundary=boundary
        ),
        "by_reviewer_type": by_reviewer_type,
    }


def formal_headline_report(entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Aggregate v3 headline scores by workflow, condition and scenario tier."""
    entries = formal_v3_entries() if entries is None else [
        entry for entry in entries
        if entry.get("result_status") in {
            "v3_formal", "v3_3_formal", "v3_4_formal", "v3_4_1_formal",
            "v3_4_2_formal", "v3_4_3_formal",
        }]
    rows = [score for entry in entries for score in entry.get("result", {}).get("scores", {}).get("cases", [])]
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {
        "workflow": defaultdict(list), "condition": defaultdict(list), "scenario_tier": defaultdict(list),
    }
    for row in rows:
        groups["workflow"][row["workflow"]].append(row)
        groups["condition"][row["condition"]].append(row)
        groups["scenario_tier"][row["scenario_tier"]].append(row)
    def render(group: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        return {name: {"task_outcome": _proportion(items, "task_outcome"),
                       "unsafe_outcome": _proportion(items, "unsafe_outcome")}
                for name, items in sorted(group.items())}
    status = entries[-1].get("result_status") if entries else "v3_3_formal"
    return {"result_status": status, "n_records": len(entries),
            "overall": {"task_outcome": _proportion(rows, "task_outcome"),
                        "unsafe_outcome": _proportion(rows, "unsafe_outcome")},
            "by": {name: render(group) for name, group in groups.items()},
            "diagnostics": _diagnostics(rows),
            "review": _review_metrics(entries)}


def paired_case_ids(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Return case IDs only where every workflow/condition comparison stays matched."""
    by_key: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        by_key[(row["workflow"], row["condition"])].add(row["case_id"])
    by_workflow: dict[str, list[set[str]]] = defaultdict(list)
    for (workflow, _condition), ids in by_key.items():
        by_workflow[workflow].append(ids)
    return {workflow: sorted(set.intersection(*sets)) if sets else []
            for workflow, sets in by_workflow.items()}
