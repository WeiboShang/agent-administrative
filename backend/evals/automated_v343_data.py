"""Build the WF2 V3.4.3 source-aligned dataset.

V3.4.2 row 30 ended mid-sentence (``... go over the``), while its authored gold
title named the omitted topic.  V3.4.3 changes only that source message and records
the repair in metadata; every gold label and every other source case is preserved.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/eval_datasets/scheduling_v341.jsonl"
OUTPUT = ROOT / "data/eval_datasets/scheduling_v343.jsonl"
REPAIRED_INDEX = 30
TRUNCATED_TEXT = (
    "Chen Wei and Alice Tan, could we hop on Zoom for about 45 minutes on "
    "2026-07-03 at 16:00 to go over the"
)
REPAIRED_TEXT = TRUNCATED_TEXT + " sprint review?"


def build_rows() -> list[dict]:
    source = [
        json.loads(line)
        for line in SOURCE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(source) != 70:
        raise RuntimeError(f"expected 70 frozen WF2 rows, got {len(source)}")
    rows = deepcopy(source)
    row = rows[REPAIRED_INDEX]
    if row.get("input_text") != TRUNCATED_TEXT:
        raise RuntimeError("WF2 row 30 no longer matches the audited truncated source")
    if row.get("gold", {}).get("title") != "Sync on the sprint review":
        raise RuntimeError("WF2 row 30 gold topic changed unexpectedly")
    row["input_text"] = REPAIRED_TEXT
    row["meta"]["source_alignment_repair"] = "completed_truncated_topic"
    return rows


def write() -> None:
    if OUTPUT.exists():
        raise RuntimeError(f"refusing to overwrite V3.4.3 dataset: {OUTPUT}")
    OUTPUT.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in build_rows()
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    write()
