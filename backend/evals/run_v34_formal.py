"""Replay and optionally persist the sealed, matched V3.4 Part A suite."""
from __future__ import annotations

import argparse
import hashlib
import json
from typing import Any

from .automated_v34_manifest import (
    MANIFEST, RECEIPT_CACHE, RECEIPT_DATASET, SCHEDULING_CACHE,
    SCHEDULING_DATASET, TRIAGE_CACHE, TRIAGE_DATASET,
)
from .outcome_adapters_v34 import build_paired_suite
from .outcomes_v3 import EvalCase, score_suite
from .provenance_v34 import file_sha256, git_commit, source_version, tracked_tree_clean
from .results_store import save_result
from .review_metrics_v3 import evaluate_review_metrics
from .v3_report import formal_headline_report, paired_case_ids


def _manifest() -> tuple[dict[str, Any], str]:
    raw = MANIFEST.read_bytes()
    manifest = json.loads(raw)
    if manifest.get("protocol_status") != "sealed_pre_run":
        raise RuntimeError("V3.4 manifest is not sealed")
    current_datasets = {
        "triage": file_sha256(TRIAGE_DATASET),
        "scheduling": file_sha256(SCHEDULING_DATASET),
        "receipts": file_sha256(RECEIPT_DATASET),
    }
    current_caches = {
        "triage": file_sha256(TRIAGE_CACHE),
        "scheduling": file_sha256(SCHEDULING_CACHE),
        "receipts": file_sha256(RECEIPT_CACHE),
    }
    if current_datasets != manifest.get("dataset_sha256"):
        raise RuntimeError("sealed V3.4 dataset hash mismatch")
    if current_caches != manifest.get("cache_sha256"):
        raise RuntimeError("sealed V3.4 cache hash mismatch")
    if source_version() != manifest.get("source_version"):
        raise RuntimeError("sealed V3.4 source hash mismatch")
    return manifest, hashlib.sha256(raw).hexdigest()


def _assert_pairs(cases: list[EvalCase]) -> None:
    grouped: dict[tuple[str, str], list[EvalCase]] = {}
    for case in cases:
        grouped.setdefault((case.workflow, case.case_id), []).append(case)
    for key, pair in grouped.items():
        if len(pair) != 2:
            raise RuntimeError(f"unmatched V3.4 pair: {key}")
        left, right = pair
        invariants = {
            "initial_state": left.initial_state == right.initial_state,
            "gold": left.gold_final_state == right.gold_final_state,
            "frozen_output": left.model_draft == right.model_draft,
            "dataset": left.dataset_version == right.dataset_version,
            "cache": left.prompt_version == right.prompt_version,
            "model": left.model == right.model,
            "source": left.config_version == right.config_version,
        }
        if not all(invariants.values()):
            raise RuntimeError(f"V3.4 pair integrity failed for {key}: {invariants}")


def run(*, persist: bool = False, limit_per_workflow: int | None = None) -> dict[str, Any]:
    manifest, manifest_sha = _manifest()
    if persist and limit_per_workflow is not None:
        raise RuntimeError("a formal V3.4 run must use the complete sealed suite")
    if persist and not tracked_tree_clean():
        raise RuntimeError("refusing formal persistence: tracked working tree is not clean")
    cases = build_paired_suite(
        limit_per_workflow=limit_per_workflow, result_status="v3_4_formal"
    )
    _assert_pairs(cases)
    suite = score_suite(cases)
    rows = [row.model_dump(mode="json") for row in suite.cases]
    matched = paired_case_ids(rows)
    expected = manifest["unique_case_counts"]
    if {workflow: len(ids) for workflow, ids in matched.items()} != {
        "wf1": expected["triage"], "wf2": expected["scheduling"],
        "wf3": expected["receipts"],
    }:
        raise RuntimeError("V3.4 matched case counts do not equal the sealed manifest")
    scores = suite.model_dump(mode="json")
    scores.update(evaluate_review_metrics(
        cases, suite.cases,
        evidence_boundary="gold-free scripted transition analysis; not human evidence",
    ))
    scores["case_context"] = [{
        "case_id": case.case_id, "workflow": case.workflow,
        "condition": case.condition, "scenario_tier": case.scenario_tier,
        "gold_final_state": case.gold_final_state.model_dump(mode="json"),
        "model_draft": case.model_draft,
        "deterministic_checks": case.deterministic_checks,
        "reviewer_type": case.reviewer_type,
    } for case in cases]
    result = {
        "schema_version": "3.4", "result_status": "v3_4_formal",
        "cases": [case.model_dump(mode="json") for case in cases], "scores": scores,
    }
    entry: dict[str, Any] = {"result_status": "v3_4_formal", "result": result}
    if persist:
        entry = save_result(
            "outcomes_v34", result, model="state-based",
            params={
                "git_commit": git_commit(), "tracked_tree_clean_at_start": True,
                "manifest_sha256": manifest_sha,
                "source_version": manifest["source_version"],
                "dataset_sha256": manifest["dataset_sha256"],
                "cache_sha256": manifest["cache_sha256"],
                "matched_case_counts": expected, "n": len(cases),
            },
            result_status="v3_4_formal",
        )
    return {
        "persisted": persist,
        "matched_case_counts": expected,
        "provenance": {
            "manifest_sha256": manifest_sha, "source_version": manifest["source_version"],
            "dataset_sha256": manifest["dataset_sha256"],
            "cache_sha256": manifest["cache_sha256"],
        },
        "headline": formal_headline_report([entry]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--limit-per-workflow", type=int)
    args = parser.parse_args()
    print(json.dumps(run(
        persist=args.persist, limit_per_workflow=args.limit_per_workflow
    ), ensure_ascii=False, indent=2))
