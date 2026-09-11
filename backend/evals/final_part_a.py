"""Stable access to the final Part A evidence package.

The final evaluation evidence deliberately has two protocol versions: WF1/WF3 are
authoritative in the sealed V3.4.3 cross-workflow run, while WF2 is authoritative in the
stricter V3.5 follow-up. ``Part A Final`` is a presentation and API alias for that boundary;
it does not rewrite either immutable result or pretend that all workflows share one version.
"""

from __future__ import annotations

import json
from typing import Any

from .outcome_adapters_v34 import build_paired_suite as build_v343_paired_suite
from .outcome_adapters_v35 import build_wf2_v35_paired_cases
from .outcomes_v3 import EvalCase, score_suite
from .results_store import formal_v343_entries, formal_v35_entries
from .review_metrics_v3 import evaluate_review_metrics

PACKAGE_LABEL = "Part A Final"
EVIDENCE_BOUNDARY = {"wf1": "v3.4.3", "wf2": "v3.5", "wf3": "v3.4.3"}


def _select_cases(
    v343_cases: list[dict[str, Any]], v35_cases: list[dict[str, Any]]
) -> list[EvalCase]:
    """Apply the declared workflow/version boundary without modifying stored evidence."""
    selected = [case for case in v343_cases if case.get("workflow") in {"wf1", "wf3"}]
    selected.extend(case for case in v35_cases if case.get("workflow") == "wf2")
    return [EvalCase.model_validate(case) for case in selected]


def load_formal_cases() -> tuple[list[EvalCase], dict[str, Any]]:
    """Load the two immutable formal rows that constitute Part A Final."""
    v343_entries = formal_v343_entries()
    v35_entries = formal_v35_entries()
    if not v343_entries or not v35_entries:
        missing = []
        if not v343_entries:
            missing.append("WF1/WF3 V3.4.3")
        if not v35_entries:
            missing.append("WF2 V3.5")
        raise LookupError(f"missing formal evidence: {', '.join(missing)}")

    v343 = v343_entries[-1]
    v35 = v35_entries[-1]
    cases = _select_cases(v343["result"]["cases"], v35["result"]["cases"])
    provenance = {
        "wf1_wf3": {
            "version": "v3.4.3",
            "result_status": v343["result_status"],
            "sha256": v343["sha256"],
        },
        "wf2": {
            "version": "v3.5",
            "result_status": v35["result_status"],
            "sha256": v35["sha256"],
        },
    }
    return cases, provenance


def build_verification_cases() -> list[EvalCase]:
    """Replay the final boundary offline without persisting a new formal result."""
    v343 = build_v343_paired_suite(result_status="v3_4_3_verification")
    v35 = build_wf2_v35_paired_cases(result_status="v3_5_verification")
    return [case for case in v343 if case.workflow in {"wf1", "wf3"}] + v35


def render(
    cases: list[EvalCase], *, provenance: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Render the common UI/report shape plus an explicit mixed-version boundary."""
    suite = score_suite(cases)
    result = suite.model_dump(mode="json")
    result.update(evaluate_review_metrics(cases, suite.cases))
    result.update(
        {
            "package_label": PACKAGE_LABEL,
            "evidence_boundary": EVIDENCE_BOUNDARY,
            "formal_provenance": provenance,
            "case_context": [
                {
                    "case_id": case.case_id,
                    "workflow": case.workflow,
                    "condition": case.condition,
                    "scenario_tier": case.scenario_tier,
                    "evaluation_version": case.evaluation_version,
                    "gold_final_state": case.gold_final_state.model_dump(mode="json"),
                    "model_draft": case.model_draft,
                    "deterministic_checks": case.deterministic_checks,
                    "review_action": case.review_action,
                    "reviewer_type": case.reviewer_type,
                    "draft_outcome": case.draft_outcome,
                }
                for case in cases
            ],
        }
    )
    return result


def latest_formal_scores() -> dict[str, Any]:
    cases, provenance = load_formal_cases()
    return render(cases, provenance=provenance)


def verification_summary() -> dict[str, Any]:
    result = render(build_verification_cases())
    return {
        "package_label": result["package_label"],
        "evidence_boundary": result["evidence_boundary"],
        "summary": result["summary"],
        "by_workflow_condition": result["by_workflow_condition"],
        "persisted": False,
    }


if __name__ == "__main__":
    print(json.dumps(verification_summary(), ensure_ascii=False, indent=2))
