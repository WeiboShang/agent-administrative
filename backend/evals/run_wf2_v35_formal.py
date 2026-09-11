"""Replay and optionally persist the sealed WF2 V3.5 evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from .automated_v35_manifest import MANIFEST, validate as validate_manifest
from .outcome_adapters_v35 import build_wf2_v35_paired_cases
from .outcomes_v3 import EvalCase, score_suite
from .provenance_v34 import git_commit, tracked_tree_clean
from .results_store import (
    formal_v343_entries,
    formal_v35_entries,
    save_result,
)
from .stats import mcnemar_exact, wilson_ci
from .wf2_mechanism_v35 import run_mechanism_suite

ROOT = Path(__file__).resolve().parents[2]


def _manifest(*, allow_code_drift: bool) -> tuple[dict[str, Any], str, dict[str, Any]]:
    raw = MANIFEST.read_bytes()
    manifest = json.loads(raw)
    if manifest.get("protocol_status") != "sealed_pre_run":
        raise RuntimeError("V3.5 manifest is not sealed")
    current = validate_manifest()
    drift: dict[str, Any] = {}
    for key, value in current.items():
        if manifest.get(key) != value:
            if allow_code_drift and key in {"source_version", "scorer_sha256"}:
                drift[key] = {"sealed": manifest.get(key), "current": value}
                continue
            raise RuntimeError(f"sealed V3.5 manifest mismatch: {key}")
    return manifest, hashlib.sha256(raw).hexdigest(), drift


def _assert_pairs(cases: list[EvalCase]) -> None:
    grouped: dict[str, list[EvalCase]] = defaultdict(list)
    for case in cases:
        grouped[case.case_id].append(case)
    for case_id, pair in grouped.items():
        if len(pair) != 2:
            raise RuntimeError(f"unmatched V3.5 pair: {case_id}")
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
            raise RuntimeError(f"V3.5 pair integrity failed for {case_id}: {invariants}")


def _proportion(k: int, n: int) -> dict[str, Any]:
    return {
        "numerator": k,
        "denominator": n,
        "rate": round(k / n, 3) if n else None,
        "wilson_95": wilson_ci(k, n) if n else None,
    }


def _e2e_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_condition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    pairs: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        by_condition[row["condition"]].append(row)
        pairs[row["case_id"]][row["condition"]] = row
    rendered = {
        condition: {
            "task_outcome": _proportion(
                sum(bool(row["task_outcome"]) for row in items), len(items)
            ),
            "unsafe_outcome": _proportion(
                sum(bool(row["unsafe_outcome"]) for row in items), len(items)
            ),
        }
        for condition, items in sorted(by_condition.items())
    }
    baseline_name = "baseline_quick_create"
    optimised_name = "optimised_smart_schedule"
    discordant_baseline_fail = sum(
        not pair[baseline_name]["task_outcome"]
        and pair[optimised_name]["task_outcome"]
        for pair in pairs.values()
    )
    discordant_optimised_fail = sum(
        pair[baseline_name]["task_outcome"]
        and not pair[optimised_name]["task_outcome"]
        for pair in pairs.values()
    )
    baseline_rate = rendered[baseline_name]["task_outcome"]["rate"]
    optimised_rate = rendered[optimised_name]["task_outcome"]["rate"]
    return {
        "suite": "WF2-E2E-70",
        "headline_eligible": True,
        "by_condition": rendered,
        "paired_comparison": {
            "absolute_task_outcome_difference": round(
                float(optimised_rate) - float(baseline_rate), 3
            ),
            "mcnemar_exact": {
                "baseline_fail_optimised_pass": discordant_baseline_fail,
                "baseline_pass_optimised_fail": discordant_optimised_fail,
                "p_value_two_sided": mcnemar_exact(
                    discordant_baseline_fail, discordant_optimised_fail
                ),
            },
        },
    }


def _protocol_files_tracked(manifest: dict[str, Any]) -> bool:
    del manifest  # hashes are validated separately; this check pins the commit boundary.
    paths = [
        "backend/evals/run_wf2_v35_formal.py",
        "backend/evals/outcome_adapters_v35.py",
        "backend/evals/wf2_v35_oracle.py",
        "backend/evals/wf2_mechanism_v35.py",
        "data/eval_datasets/automated_v35_manifest.json",
        "data/eval_datasets/scheduling_v35.jsonl",
        "data/eval_datasets/wf2_mechanism_v35.jsonl",
        "data/eval_datasets/wf2_temporal_contract_v35.json",
        "data/eval_datasets/wf2_date_contract_audit_v35.json",
    ]
    return all(
        subprocess.run(
            ["git", "ls-files", "--error-unmatch", path],
            cwd=ROOT,
            capture_output=True,
        ).returncode
        == 0
        for path in paths
    )


def run(*, persist: bool = False, limit: int | None = None) -> dict[str, Any]:
    manifest, manifest_sha, code_drift = _manifest(allow_code_drift=not persist)
    if persist and limit is not None:
        raise RuntimeError("a formal V3.5 run must use all 70 sealed E2E cases")
    if persist and (not tracked_tree_clean() or not _protocol_files_tracked(manifest)):
        raise RuntimeError(
            "refusing formal persistence: commit all V3.5 protocol files and start "
            "from a clean tracked tree"
        )
    if persist and formal_v35_entries():
        raise RuntimeError(
            "a formal result already exists for this V3.5 protocol; create a new "
            "version rather than overwriting or silently rerunning it"
        )

    run_status = "v3_5_formal" if persist else "v3_5_verification"
    cases = build_wf2_v35_paired_cases(limit=limit, result_status=run_status)
    _assert_pairs(cases)
    expected = 70 if limit is None else min(max(limit, 0), 70)
    if len(cases) != 2 * expected:
        raise RuntimeError("V3.5 paired E2E count does not match the sealed protocol")
    suite = score_suite(cases)
    score_rows = [row.model_dump(mode="json") for row in suite.cases]
    mechanism = run_mechanism_suite()
    report = {
        "e2e": _e2e_report(score_rows),
        "mechanism": {
            "suite": mechanism["suite"],
            "headline_eligible": False,
            "metrics": mechanism["metrics"],
        },
        "interpretation_boundary": (
            "Internal synthetic create, abstention, conflict-handling and candidate "
            "recommendation evidence only; no lifecycle or external-validity claim."
        ),
    }
    result = {
        "schema_version": "3.5",
        "result_status": run_status,
        "cases": [case.model_dump(mode="json") for case in cases],
        "scores": suite.model_dump(mode="json"),
        "mechanism": mechanism,
        "report": report,
    }
    entry: dict[str, Any] = {"result_status": run_status, "result": result}
    if persist:
        historical = formal_v343_entries()
        entry = save_result(
            "outcomes_wf2_v35",
            result,
            model="state-based+independent-reference-oracle",
            params={
                "git_commit": git_commit(),
                "tracked_tree_clean_at_start": True,
                "manifest_sha256": manifest_sha,
                "source_version": manifest["source_version"],
                "dataset_sha256": manifest["dataset_sha256"],
                "cache_sha256": manifest["cache_sha256"],
                "scorer_sha256": manifest["scorer_sha256"],
                "matched_e2e_case_count": expected,
                "mechanism_case_count": mechanism["case_count"],
                "historical_v343_sha256": (
                    historical[-1]["sha256"] if historical else None
                ),
                "n_e2e_executions": len(cases),
            },
            result_status="v3_5_formal",
        )
    return {
        "persisted": persist,
        "result_status": run_status,
        "code_drift_from_sealed_formal": code_drift,
        "matched_e2e_case_count": expected,
        "mechanism_case_count": mechanism["case_count"],
        "provenance": {
            "manifest_sha256": manifest_sha,
            "source_version": manifest["source_version"],
            "dataset_sha256": manifest["dataset_sha256"],
            "cache_sha256": manifest["cache_sha256"],
            "scorer_sha256": manifest["scorer_sha256"],
        },
        "report": entry["result"]["report"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--persist", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    print(
        json.dumps(
            run(persist=args.persist, limit=args.limit),
            ensure_ascii=False,
            indent=2,
        )
    )
