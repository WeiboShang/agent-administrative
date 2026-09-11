"""Run non-formal smoke cases or the separately authorised external formal benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .external_workbench_agent import (
    MAX_EXECUTION_SECONDS,
    MAX_ITERATIONS,
    MODEL,
    OpenRouterNativeToolProvider,
    PROVIDER,
    TEMPERATURE,
    build_system_prompt,
    run_agent_structured,
)
from .external_workbench_cases import (
    FORMAL_MANIFEST_PATH,
    ExternalCaseSource,
    canonical_json,
    load_formal_sources,
    sha256_json,
    smoke_cases,
    smoke_gold,
)
from .external_workbench_protocol import (
    assert_gold_free,
    load_formal_gold,
    score_external_final_state,
    sha256_file,
    validate_frozen_manifest,
)
from .outcomes_v3 import WorkspaceState

ROOT = Path(__file__).resolve().parents[2]
SMOKE_RESULTS = ROOT / "data/eval_results/external_workbench_smoke_v2.jsonl"
FORMAL_RESULTS = ROOT / "data/eval_results/external_workbench_formal.jsonl"
TRACE_ROOT = ROOT / "data/eval_traces/external_workbench"


def _load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _completed_keys(path: Path) -> set[tuple[str, str]]:
    return {
        (str(row.get("protocol_sha256")), str(row.get("case_id")))
        for row in _load_rows(path)
        if row.get("status") == "completed"
    }


def _append_unique_completed(path: Path, row: dict[str, Any]) -> None:
    key = (str(row["protocol_sha256"]), str(row["case_id"]))
    if row.get("status") == "completed" and key in _completed_keys(path):
        raise RuntimeError(f"completed result already exists for {key}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_json(row) + "\n")


def _write_trace(row: dict[str, Any]) -> str:
    target = TRACE_ROOT / str(row["protocol_sha256"]) / f"{row['case_id']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and row.get("status") == "completed":
        raise RuntimeError(f"trace already exists: {target}")
    target.write_text(
        json.dumps(row["agent"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return str(target.relative_to(ROOT))


def run_case(
    source: ExternalCaseSource,
    *,
    provider: Any,
    gold_loader: Callable[[ExternalCaseSource, WorkspaceState], Any],
    protocol_sha256: str,
) -> dict[str, Any]:
    """Execute first, then invoke the supplied post-execution gold loader."""
    assert_gold_free(source.to_dict())
    context = source.build_context()
    assert context.initial_state is not None
    tools = source.build_tools(context)
    boundary = {
        "task": source.task,
        "source": source.source,
        "system_prompt": build_system_prompt(context.now),
        "tool_schemas": [tool.openai_schema() for tool in tools],
    }
    assert_gold_free(boundary)
    started = datetime.now(timezone.utc).isoformat()
    try:
        result = run_agent_structured(
            provider=provider,
            tools=tools,
            task=source.task,
            now=context.now,
            max_iterations=MAX_ITERATIONS,
            max_execution_seconds=MAX_EXECUTION_SECONDS,
        )
    except Exception as exc:
        return {
            "schema_version": "external_workbench_result_v1",
            "status": "error",
            "case_id": source.case_id,
            "workflow": source.workflow,
            "source_sha256": source.source_sha256,
            "protocol_sha256": protocol_sha256,
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "error": {"type": type(exc).__name__, "detail": str(exc)},
            "final_state": WorkspaceState.capture(context.store).model_dump(mode="json"),
        }

    final_state = WorkspaceState.capture(context.store)
    # The gold loader is deliberately called only after agent execution and final capture.
    gold = gold_loader(source, context.initial_state)
    score = score_external_final_state(
        source=source,
        initial_state=context.initial_state,
        final_state=final_state,
        gold=gold,
        tool_calls=result.tool_calls,
    )
    return {
        "schema_version": "external_workbench_result_v1",
        "status": "completed" if result.error is None else "error",
        "case_id": source.case_id,
        "workflow": source.workflow,
        "source_sha256": source.source_sha256,
        "protocol_sha256": protocol_sha256,
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "configuration": {
            "model": MODEL,
            "provider": PROVIDER,
            "temperature": TEMPERATURE,
            "max_iterations": MAX_ITERATIONS,
            "max_execution_seconds": MAX_EXECUTION_SECONDS,
            "tool_schema_sha256": sha256_json([tool.openai_schema() for tool in tools]),
            "system_prompt_sha256": hashlib.sha256(
                build_system_prompt(context.now).encode("utf-8")
            ).hexdigest(),
        },
        "initial_state_sha256": sha256_json(context.initial_state.model_dump(mode="json")),
        "final_state_sha256": sha256_json(final_state.model_dump(mode="json")),
        "final_state": final_state.model_dump(mode="json"),
        "agent": result.to_dict(),
        "score": score,
        "error": result.error,
    }


def _select_cases(
    cases: list[ExternalCaseSource], *, workflow: str | None, case_id: str | None, all_cases: bool
) -> list[ExternalCaseSource]:
    if case_id:
        selected = [case for case in cases if case.case_id == case_id]
        if len(selected) != 1:
            raise LookupError(f"case not found: {case_id}")
        return selected
    if workflow:
        return [case for case in cases if case.workflow == workflow]
    if all_cases:
        return cases
    raise ValueError("select --case-id, --workflow, or --all")


def _smoke_gold_loader(source: ExternalCaseSource, _: WorkspaceState) -> Any:
    return smoke_gold(source.case_id)


def _formal_gold_loader(source: ExternalCaseSource, initial: WorkspaceState) -> Any:
    return load_formal_gold(source.case_id, initial)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("smoke", "formal"), required=True)
    parser.add_argument("--case-id")
    parser.add_argument("--workflow", choices=("wf1", "wf2", "wf3"))
    parser.add_argument("--all", action="store_true", dest="all_cases")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--confirm-formal",
        action="store_true",
        help="Required acknowledgement that the frozen formal run has been authorised.",
    )
    args = parser.parse_args()

    if args.mode == "formal":
        if not args.confirm_formal:
            raise SystemExit("formal execution refused: pass --confirm-formal only after protocol review")
        manifest = json.loads(FORMAL_MANIFEST_PATH.read_text(encoding="utf-8"))
        validate_frozen_manifest(manifest)
        protocol_sha256 = sha256_file(FORMAL_MANIFEST_PATH)
        cases = load_formal_sources()
        output = FORMAL_RESULTS
        gold_loader = _formal_gold_loader
    else:
        cases = smoke_cases()
        # v1 incorrectly labelled an explicit delegated WF3 approve tool call as an
        # unspecified autonomous decision at the scorer boundary. v2 records the actual
        # tool decision; prompts, schemas and agent behaviour are unchanged.
        protocol_sha256 = hashlib.sha256(b"external_workbench_smoke_v2").hexdigest()
        output = SMOKE_RESULTS
        gold_loader = _smoke_gold_loader

    selected = _select_cases(
        cases, workflow=args.workflow, case_id=args.case_id, all_cases=args.all_cases
    )
    completed = _completed_keys(output) if args.resume else set()
    if output.exists() and not args.resume:
        existing_selected = {
            row.get("case_id")
            for row in _load_rows(output)
            if row.get("protocol_sha256") == protocol_sha256
            and row.get("case_id") in {case.case_id for case in selected}
        }
        if existing_selected:
            raise SystemExit(f"result rows already exist for {sorted(existing_selected)}; use --resume")

    provider = OpenRouterNativeToolProvider()
    for source in selected:
        key = (protocol_sha256, source.case_id)
        if key in completed:
            print(f"skip completed {source.case_id}")
            continue
        row = run_case(
            source,
            provider=provider,
            gold_loader=gold_loader,
            protocol_sha256=protocol_sha256,
        )
        row["trace_path"] = _write_trace(row)
        _append_unique_completed(output, row)
        score = row.get("score") or {}
        print(
            json.dumps(
                {
                    "case_id": row["case_id"],
                    "status": row["status"],
                    "task_outcome": score.get("task_outcome"),
                    "unsafe_outcome": score.get("unsafe_outcome"),
                    "model_turns": (row.get("agent") or {}).get("model_turns"),
                    "tool_calls": len((row.get("agent") or {}).get("tool_calls") or []),
                    "total_tokens": (row.get("agent") or {}).get("total_tokens"),
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
