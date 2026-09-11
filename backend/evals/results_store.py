"""Append-only disk log of eval runs — `data/eval_results/<name>.jsonl`.

Every eval endpoint call appends one entry `{at, name, model, params, result}`, so runs
*accumulate* across server restarts and across days (the free-tier token quota forces
final-number collection to be batched). `load_latest` feeds `/api/eval/last` and the
Overview page; `load_all` is for the write-up (aggregate several batches into one table).

The files are small JSON and are meant to be committed because they are the evaluation's
raw numbers.
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

RESULTS_DIR = "data/eval_results"


def save_result(name: str, result: dict, *, model: Optional[str] = None,
                params: Optional[dict] = None,
                result_status: str = "legacy_pilot") -> dict[str, Any]:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "name": name,
             "model": model, "params": params or {}, "result_status": result_status,
             "result": result}
    canonical = json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    entry["sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    with open(os.path.join(RESULTS_DIR, f"{name}.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def load_all(name: str) -> list[dict]:
    path = os.path.join(RESULTS_DIR, f"{name}.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def formal_v3_entries() -> list[dict]:
    """Return formal automated outcomes, preferring V3.3 when available."""
    entries = load_all("outcomes_v3")
    current = [entry for entry in entries if entry.get("result_status") == "v3_3_formal"]
    if current:
        superseded = {
            entry.get("params", {}).get("supersedes_sha256")
            for entry in current
            if entry.get("params", {}).get("supersedes_sha256")
        }
        return [entry for entry in current if entry.get("sha256") not in superseded]
    return [entry for entry in load_all("outcomes_v3")
            if entry.get("result_status") == "v3_formal"]


def formal_v34_entries() -> list[dict]:
    """Return active V3.4 formal rows only; never fall back to another protocol."""
    current = [
        entry for entry in load_all("outcomes_v34")
        if entry.get("result_status") == "v3_4_formal"
    ]
    superseded = {
        entry.get("params", {}).get("supersedes_sha256")
        for entry in current
        if entry.get("params", {}).get("supersedes_sha256")
    }
    return [entry for entry in current if entry.get("sha256") not in superseded]


def formal_v341_entries() -> list[dict]:
    """Return active V3.4.1 rows only; never fall back to older protocols."""
    current = [
        entry for entry in load_all("outcomes_v341")
        if entry.get("result_status") == "v3_4_1_formal"
    ]
    superseded = {
        entry.get("params", {}).get("supersedes_sha256")
        for entry in current
        if entry.get("params", {}).get("supersedes_sha256")
    }
    return [entry for entry in current if entry.get("sha256") not in superseded]


def formal_v342_entries() -> list[dict]:
    """Return active V3.4.2 rows only; never fall back to older protocols."""
    current = [
        entry for entry in load_all("outcomes_v342")
        if entry.get("result_status") == "v3_4_2_formal"
    ]
    superseded = {
        entry.get("params", {}).get("supersedes_sha256")
        for entry in current
        if entry.get("params", {}).get("supersedes_sha256")
    }
    return [entry for entry in current if entry.get("sha256") not in superseded]


def formal_v343_entries() -> list[dict]:
    """Return active V3.4.3 rows only; never fall back to older protocols."""
    current = [
        entry for entry in load_all("outcomes_v343")
        if entry.get("result_status") == "v3_4_3_formal"
    ]
    superseded = {
        entry.get("params", {}).get("supersedes_sha256")
        for entry in current
        if entry.get("params", {}).get("supersedes_sha256")
    }
    return [entry for entry in current if entry.get("sha256") not in superseded]


def formal_v35_entries() -> list[dict]:
    """Return immutable WF2 V3.5 formal rows; this protocol does not replace V3.4.3."""
    return [
        entry
        for entry in load_all("outcomes_wf2_v35")
        if entry.get("result_status") == "v3_5_formal"
    ]


def load_latest() -> dict[str, dict]:
    """Most recent entry per eval name (survives restarts)."""
    out: dict[str, dict] = {}
    if not os.path.isdir(RESULTS_DIR):
        return out
    for fn in sorted(os.listdir(RESULTS_DIR)):
        if fn.endswith(".jsonl"):
            entries = load_all(fn[:-len(".jsonl")])
            if entries:
                out[fn[:-len(".jsonl")]] = entries[-1]
    return out
