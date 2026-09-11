"""Source sanitisation, provenance hashes and the post-execution scoring boundary."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from ..fixtures import org
from .external_workbench_agent import (
    MAX_EXECUTION_SECONDS,
    MAX_ITERATIONS,
    MODEL,
    PROVIDER,
    REASONING_EFFORT,
    SYSTEM_PROMPT_TEMPLATE,
    TEMPERATURE,
    WORKBENCH_UPSTREAM_COMMIT,
)
from .external_workbench_cases import (
    FORMAL_MANIFEST_PATH,
    FORMAL_SOURCE_PATH,
    ExternalCaseSource,
    _wf1_task,
    _wf2_task,
    _wf3_task,
    canonical_json,
    sha256_json,
    smoke_cases,
)
from .outcome_adapters_v34 import (
    RECEIPT_MANIFEST,
    _fixed_store,
    _wf1_gold,
    _wf3_gold,
)
from .outcome_adapters_v35 import SCHEDULING_V35_DATASET, _strict_gold
from .outcomes_v3 import EvalCase, GoldFinalState, WorkspaceState, score_case
from .realiser import load_sched_cases
from .receipt_score import load_manifest

ROOT = Path(__file__).resolve().parents[2]
TRIAGE_SOURCE = ROOT / "data/eval_datasets/triage_v34.jsonl"
RECEIPT_PRIMARY = ROOT / "data/eval_cache/receipts_qwen3.6-27b_synthetic_v2.jsonl"
RECEIPT_CRITICAL = ROOT / "data/eval_cache/receipts_qwen3.6-27b_critical_v342.jsonl"
PROTOCOL_DOCUMENT = ROOT / "docs/external_workbench_protocol.md"
IMPLEMENTATION_FILES = [
    Path(__file__),
    ROOT / "backend/evals/external_workbench_agent.py",
    ROOT / "backend/evals/external_workbench_cases.py",
    ROOT / "backend/evals/external_workbench_tools.py",
    ROOT / "backend/evals/run_external_workbench.py",
]
FORBIDDEN_AGENT_KEYS = {
    "gold",
    "gold_final_state",
    "expected_task_outcome",
    "expected_unsafe_outcome",
    "expected_decision",
    "expected_approval",
    "expected_rejection",
    "scorer_predicates",
    "scenario_tier",
    "tier",
    "hidden_reference",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def combined_file_hash(paths: list[Path]) -> str:
    rows = [{"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)} for path in paths]
    return sha256_json(rows)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _contains_forbidden_key(value: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            current = f"{path}.{key}"
            if str(key).casefold() in FORBIDDEN_AGENT_KEYS:
                found.append(current)
            found.extend(_contains_forbidden_key(item, current))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_contains_forbidden_key(item, f"{path}[{index}]"))
    return found


def assert_gold_free(value: Any) -> None:
    found = _contains_forbidden_key(value)
    if found:
        raise ValueError(f"evaluation-only keys crossed the agent boundary: {found}")


def _build_wf1_sources() -> list[ExternalCaseSource]:
    sources = []
    for row in _jsonl(TRIAGE_SOURCE):
        messages = list(row["messages"])
        attachments = list(row.get("attachments") or [])
        source = {
            "thread_id": row["thread_id"],
            "messages": messages,
            "attachments": attachments,
        }
        sources.append(
            ExternalCaseSource(
                case_id=str(row["case_id"]),
                workflow="wf1",
                now="2026-06-30T09:00:00",
                task=_wf1_task(messages, attachments),
                source=source,
            )
        )
    return sources


def _build_wf2_sources() -> list[ExternalCaseSource]:
    sources = []
    for index, row in enumerate(load_sched_cases(str(SCHEDULING_V35_DATASET))):
        initial_records = []
        if pre_book := row.meta.get("pre_book"):
            initial_records.append(
                {"store": "events", "type": "event", "status": "booked", "data": pre_book}
            )
        sources.append(
            ExternalCaseSource(
                case_id=f"wf2-{index:04d}",
                workflow="wf2",
                now=str(row.meta["now"]),
                task=_wf2_task(str(row.input_text)),
                source={"request": str(row.input_text)},
                initial_records=initial_records,
            )
        )
    return sources


def _build_wf3_sources() -> list[ExternalCaseSource]:
    primary = {row["image"]: row["extraction"] for row in _jsonl(RECEIPT_PRIMARY)}
    critical = {row["image"]: row["critical_read"] for row in _jsonl(RECEIPT_CRITICAL)}
    sources = []
    for entry in load_manifest(str(RECEIPT_MANIFEST)):
        image = str(entry["image"])
        evidence = {"primary_read": primary[image], "critical_read": critical[image]}
        sources.append(
            ExternalCaseSource(
                case_id=f"wf3-{image}",
                workflow="wf3",
                now="2026-07-01T09:00:00",
                task=_wf3_task(image),
                source={"receipt_evidence": evidence},
            )
        )
    return sources


def build_formal_source_snapshot() -> tuple[list[ExternalCaseSource], dict[str, Any]]:
    """Build a gold-free execution snapshot without reading formal result rows."""
    cases = [*_build_wf1_sources(), *_build_wf2_sources(), *_build_wf3_sources()]
    counts = Counter(case.workflow for case in cases)
    if counts != Counter({"wf1": 45, "wf2": 70, "wf3": 108}):
        raise RuntimeError(f"unexpected formal source counts: {dict(counts)}")
    if len({case.case_id for case in cases}) != 223:
        raise RuntimeError("formal source IDs are not unique")
    for case in cases:
        assert_gold_free(case.to_dict())
    manifest = {
        "schema_version": "external_workbench_protocol_v1",
        "status": "prepared_not_executed",
        "method": "WorkBench-style tool-using external-method baseline",
        "comparison": "case-aligned supplementary method comparison",
        "workbench": {
            "repository": "https://github.com/olly-styles/WorkBench",
            "commit": WORKBENCH_UPSTREAM_COMMIT,
            "source_function": "src/evals/agent.py::run_agent_structured",
            "license": "MIT",
        },
        "configuration": {
            "model": MODEL,
            "provider": PROVIDER,
            "temperature": TEMPERATURE,
            "reasoning_effort": REASONING_EFFORT,
            "max_iterations": MAX_ITERATIONS,
            "max_execution_seconds": MAX_EXECUTION_SECONDS,
            "autonomous_execution": True,
            "formal_concurrency": 1,
        },
        "case_counts": {"wf1": 45, "wf2": 70, "wf3": 108, "all": 223},
        "authoritative_boundaries": {"wf1": "v3.4.3", "wf2": "v3.5", "wf3": "v3.4.3"},
        "source_inputs": {
            str(path.relative_to(ROOT)): sha256_file(path)
            for path in [TRIAGE_SOURCE, SCHEDULING_V35_DATASET, RECEIPT_MANIFEST, RECEIPT_PRIMARY, RECEIPT_CRITICAL]
        },
        "protocol_document_sha256": sha256_file(PROTOCOL_DOCUMENT),
        "system_prompt_template": SYSTEM_PROMPT_TEMPLATE,
        "system_prompt_template_sha256": hashlib.sha256(SYSTEM_PROMPT_TEMPLATE.encode("utf-8")).hexdigest(),
        "implementation_sha256": combined_file_hash(IMPLEMENTATION_FILES),
        "implementation_files": {
            str(path.relative_to(ROOT)): sha256_file(path) for path in IMPLEMENTATION_FILES
        },
        "tool_schema_sha256": tool_schema_hashes(),
        "formal_source_rows_sha256": sha256_json([case.to_dict() for case in cases]),
        "requires_explicit_confirm_formal": True,
        "formal_execution_executed": False,
    }
    return cases, manifest


def write_formal_source_snapshot() -> dict[str, Any]:
    cases, manifest = build_formal_source_snapshot()
    FORMAL_SOURCE_PATH.write_text(
        "".join(canonical_json(case.to_dict()) + "\n" for case in cases),
        encoding="utf-8",
    )
    manifest["formal_source_file"] = str(FORMAL_SOURCE_PATH.relative_to(ROOT))
    manifest["formal_source_file_sha256"] = sha256_file(FORMAL_SOURCE_PATH)
    FORMAL_MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def validate_frozen_manifest(manifest: dict[str, Any]) -> None:
    """Fail closed if any pre-registered execution input changed after freezing."""
    expected = {
        "implementation_sha256": combined_file_hash(IMPLEMENTATION_FILES),
        "protocol_document_sha256": sha256_file(PROTOCOL_DOCUMENT),
        "system_prompt_template_sha256": hashlib.sha256(
            SYSTEM_PROMPT_TEMPLATE.encode("utf-8")
        ).hexdigest(),
        "tool_schema_sha256": tool_schema_hashes(),
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise RuntimeError(f"frozen manifest mismatch for {key}")
    for relative, expected_hash in manifest.get("source_inputs", {}).items():
        if sha256_file(ROOT / relative) != expected_hash:
            raise RuntimeError(f"frozen source input mismatch: {relative}")
    source_file = ROOT / str(manifest["formal_source_file"])
    if sha256_file(source_file) != manifest.get("formal_source_file_sha256"):
        raise RuntimeError("formal source snapshot hash mismatch")


def tool_schema_hashes() -> dict[str, str]:
    representatives = {case.workflow: case for case in smoke_cases()}
    output = {}
    for workflow, case in representatives.items():
        context = case.build_context()
        schemas = [tool.openai_schema() for tool in case.build_tools(context)]
        output[workflow] = sha256_json(schemas)
    return output


def load_formal_gold(case_id: str, initial_state: WorkspaceState) -> GoldFinalState:
    """Load the sealed contract only after external execution has captured final state."""
    if case_id.startswith("wf1-"):
        row = next(row for row in _jsonl(TRIAGE_SOURCE) if row["case_id"] == case_id)
        return _wf1_gold(row, "v3_4_3_formal")
    if case_id.startswith("wf2-"):
        index = int(case_id.split("-")[1])
        row = load_sched_cases(str(SCHEDULING_V35_DATASET))[index]
        gold, _ = _strict_gold(row, initial_state)
        return gold
    if case_id.startswith("wf3-"):
        image = case_id.removeprefix("wf3-")
        entry = next(row for row in load_manifest(str(RECEIPT_MANIFEST)) if row["image"] == image)
        now = datetime(2026, 7, 1, 9, 0)
        gold_store = _fixed_store(now)
        org.seed_from_org(gold_store, today=now.date())
        return _wf3_gold(entry, gold_store, "v3_4_3_formal")
    raise KeyError(case_id)


def score_external_final_state(
    *,
    source: ExternalCaseSource,
    initial_state: WorkspaceState,
    final_state: WorkspaceState,
    gold: GoldFinalState,
    tool_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply the existing scorer; callers supply gold only after agent completion."""
    successful_names = {
        str(call.get("name"))
        for call in tool_calls
        if call.get("observation", {}).get("ok")
    }
    if "approve_expense_claim" in successful_names or "create_calendar_event" in successful_names:
        decision = "approve"
    elif "reject_expense_claim" in successful_names:
        decision = "reject"
    elif successful_names & {"create_meeting_draft", "create_expense_draft"}:
        decision = "route"
    else:
        decision = "no_action"
    case = EvalCase(
        run_id="external-workbench",
        case_id=source.case_id,
        workflow=source.workflow,
        condition="external_workbench_native_tools",
        evaluation_version="v3.5" if source.workflow == "wf2" else "v3.4.3",
        result_status="v3_5_verification" if source.workflow == "wf2" else "v3_4_3_verification",
        initial_state=initial_state,
        gold_final_state=gold,
        model=MODEL,
        prompt_version=hashlib.sha256(SYSTEM_PROMPT_TEMPLATE.encode("utf-8")).hexdigest(),
        deterministic_checks=tool_calls,
        review_action={"decision": decision},
        reviewer_type="none",
        actual_final_state=final_state,
    )
    return score_case(case).model_dump(mode="json")
