"""Run the complete frozen, matched Evaluation v3.3 suite without model calls.

The command replays committed datasets and cached model outputs through baseline and
optimised workflow conditions.  It never touches the live workspace or an external API.
Use ``--persist`` only for the formal run that should be appended to
``data/eval_results/outcomes_v3.jsonl``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .outcome_adapters_v3 import build_paired_suite
from .outcomes_v3 import score_suite
from .results_store import save_result
from .review_metrics_v3 import evaluate_review_metrics
from .v3_report import formal_headline_report, paired_case_ids


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "data/eval_datasets/automated_v33_manifest.json"


def _manifest_provenance() -> dict[str, Any]:
    raw = MANIFEST_PATH.read_bytes()
    manifest = json.loads(raw)
    if manifest.get("protocol_status") != "frozen_pre_run":
        raise RuntimeError("Automated V3.3 manifest is not frozen for the formal run")
    return {
        "protocol_version": manifest["schema_version"],
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "text_model": manifest["text_model"],
        "vision_model": manifest["vision_model"],
        "cache_sha256": manifest["cache_sha256"],
        "oracle_correction_in_primary": manifest["oracle_correction_in_primary"],
        "policy_contract": manifest["policy_contract"],
    }


def run(
    *,
    limit_per_workflow: int | None = None,
    persist: bool = False,
    supersedes_sha256: str | None = None,
) -> dict[str, Any]:
    provenance = _manifest_provenance()
    cases = build_paired_suite(
        limit_per_workflow=limit_per_workflow,
        result_status="v3_3_formal",
    )
    suite = score_suite(cases)
    rows = [row.model_dump(mode="json") for row in suite.cases]
    matched = paired_case_ids(rows)
    expected = {
        workflow: len({case.case_id for case in cases if case.workflow == workflow})
        for workflow in ("wf1", "wf2", "wf3")
    }
    if {workflow: len(ids) for workflow, ids in matched.items()} != expected:
        raise RuntimeError("baseline/optimised case IDs are not fully matched")

    scores = suite.model_dump(mode="json")
    scores.update(evaluate_review_metrics(
        cases,
        suite.cases,
        evidence_boundary=(
            "gold-free deterministic transition analysis; not human evidence"
        ),
    ))
    scores["case_context"] = [
        {
            "case_id": case.case_id,
            "workflow": case.workflow,
            "condition": case.condition,
            "scenario_tier": case.scenario_tier,
            "gold_final_state": case.gold_final_state.model_dump(mode="json"),
            "model_draft": case.model_draft,
            "deterministic_checks": case.deterministic_checks,
            "review_action": case.review_action,
            "reviewer_type": case.reviewer_type,
            "draft_outcome": case.draft_outcome,
        }
        for case in cases
    ]
    result = {
        "schema_version": "3.3",
        "result_status": "v3_3_formal",
        "cases": [case.model_dump(mode="json") for case in cases],
        "scores": scores,
    }
    entry = {
        "result_status": "v3_3_formal",
        "result": result,
    }
    if persist:
        params = {
            "run_ids": sorted({case.run_id for case in cases}),
            "n": len(cases),
            "matched_case_counts": expected,
            **provenance,
        }
        if supersedes_sha256:
            params["supersedes_sha256"] = supersedes_sha256
            params["supersession_reason"] = (
                "Correct per-case evaluation_version metadata from v3.2 to v3.3; "
                "model caches and outcome values are unchanged"
            )
        entry = save_result(
            "outcomes_v3",
            result,
            model="state-based",
            params=params,
            result_status="v3_3_formal",
        )
    return {
        "persisted": persist,
        "matched_case_counts": expected,
        "provenance": provenance,
        "headline": formal_headline_report([entry]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit-per-workflow", type=int)
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--supersedes-sha256")
    args = parser.parse_args()
    print(json.dumps(run(
        limit_per_workflow=args.limit_per_workflow,
        persist=args.persist,
        supersedes_sha256=args.supersedes_sha256,
    ), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
