"""Build the WF2 V3.4.1 dataset under the current V5 temporal contract.

The source text and frozen GPT-OSS outputs are unchanged.  Only source-authored gold
dates and matching pre-booked conflict dates are migrated from the archived V4
``next weekday = nearest future`` convention to the production/Human-V5 convention
``next weekday = following calendar week``.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..workflows.scheduling import resolve_relative_date

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/eval_datasets/scheduling_realised.jsonl"
OUTPUT = ROOT / "data/eval_datasets/scheduling_v341.jsonl"


def build_rows() -> list[dict]:
    rows = [
        json.loads(line)
        for line in SOURCE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != 70:
        raise RuntimeError(f"expected 70 frozen WF2 rows, got {len(rows)}")
    for row in rows:
        meta = row["meta"]
        gold = row["gold"]
        if gold.get("intent") == "none" or not meta.get("date_phrase"):
            continue
        now = datetime.fromisoformat(meta["now"])
        resolved = resolve_relative_date(meta["date_phrase"], now)
        gold["date"] = resolved
        if meta.get("pre_book"):
            meta["pre_book"]["date"] = resolved
    return rows


def write() -> None:
    if OUTPUT.exists():
        raise RuntimeError(f"refusing to overwrite V3.4.1 dataset: {OUTPUT}")
    payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in build_rows()
    )
    OUTPUT.write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    write()
