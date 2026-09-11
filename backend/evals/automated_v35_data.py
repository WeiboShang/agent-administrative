"""Freeze the stricter WF2 V3.5 dataset and temporal audit artifacts.

The temporal expectations below are literal, author-reviewed values.  This builder never
imports the production resolver; evaluation-time gold is read directly from the frozen
JSONL dataset.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/eval_datasets/scheduling_v343.jsonl"
HISTORICAL_SOURCE = ROOT / "data/eval_datasets/scheduling_realised.jsonl"
OUTPUT = ROOT / "data/eval_datasets/scheduling_v35.jsonl"
TEMPORAL_CONTRACT = ROOT / "data/eval_datasets/wf2_temporal_contract_v35.json"
DATE_AUDIT = ROOT / "data/eval_datasets/wf2_date_contract_audit_v35.json"

# Written from the documented "following calendar week" convention at the frozen
# reference time 2026-06-30T09:00:00 (Tuesday), not computed by the system under test.
MANUAL_RELATIVE_DATES = {
    "next Monday": "2026-07-06",
    "next Tuesday": "2026-07-07",
    "next Wednesday": "2026-07-08",
    "next Thursday": "2026-07-09",
    "next Friday": "2026-07-10",
}

# The 15 rows whose old nearest-future gold differed by exactly seven days.  The three
# missing-time rows did not fail V3.3 because that adapter stopped for human selection;
# they became visible when V3.4 introduced deterministic source-only selection.
DATE_CHANGE_INDEXES = (2, 3, 9, 11, 12, 15, 40, 41, 42, 43, 44, 45, 47, 48, 51)
V33_FAILED_INDEXES = (2, 3, 9, 40, 41, 42, 43, 44, 45, 47, 48, 51)
V34_SOURCE_ONLY_INDEXES = (11, 12, 15)


def _rows(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def build_rows() -> list[dict]:
    rows = deepcopy(_rows(SOURCE))
    if len(rows) != 70:
        raise RuntimeError(f"expected 70 frozen V3.4.3 WF2 rows, got {len(rows)}")
    for index, row in enumerate(rows):
        gold, meta = row["gold"], row["meta"]
        phrase = meta.get("date_phrase")
        if gold.get("intent") == "schedule_meeting":
            gold["organizer"] = "alice"
            if gold.get("mode") == "in_person" and gold.get("date"):
                if "orion" not in row["input_text"].casefold():
                    raise RuntimeError(
                        f"in-person WF2 row {index} lacks an authored Orion request"
                    )
                gold["location"] = "Orion"
                gold["accepted_location_values"] = ["Orion", "Orion room"]
            else:
                gold["location"] = None
                gold["accepted_location_values"] = []
        else:
            gold["organizer"] = None
            gold["location"] = None
            gold["accepted_location_values"] = []

        if phrase in MANUAL_RELATIVE_DATES and gold.get("date"):
            expected = MANUAL_RELATIVE_DATES[phrase]
            if gold["date"] != expected:
                raise RuntimeError(
                    f"manual temporal contract mismatch at row {index}: "
                    f"{gold['date']} != {expected}"
                )
        elif meta.get("date_style") == "explicit" and gold.get("date"):
            if phrase != gold["date"]:
                raise RuntimeError(f"explicit date mismatch at row {index}")
        elif meta.get("date_style") == "vague" and gold.get("date") is not None:
            raise RuntimeError(f"vague date must remain unresolved at row {index}")
    return rows


def build_temporal_contract(rows: list[dict]) -> dict:
    return {
        "schema_version": "3.5",
        "contract_id": "wf2-following-calendar-week-v1",
        "reference_now": "2026-06-30T09:00:00",
        "next_weekday_rule": (
            "'next <weekday>' denotes that weekday in the following calendar week"
        ),
        "gold_authoring": "literal author-reviewed ISO dates; no production resolver",
        "manual_relative_date_table": MANUAL_RELATIVE_DATES,
        "case_expected_dates": {
            f"wf2-{index:04d}": row["gold"].get("date")
            for index, row in enumerate(rows)
        },
    }


def build_date_audit(rows: list[dict]) -> dict:
    old_rows = _rows(HISTORICAL_SOURCE)
    if len(old_rows) != 70:
        raise RuntimeError("historical WF2 dataset is incomplete")
    audit = []
    for index in DATE_CHANGE_INDEXES:
        old, current = old_rows[index], rows[index]
        phrase = current["meta"].get("date_phrase")
        if phrase not in MANUAL_RELATIVE_DATES:
            raise RuntimeError(f"date audit row {index} is not a manual relative case")
        old_date = old["gold"].get("date")
        corrected_date = current["gold"].get("date")
        if not old_date or not corrected_date:
            raise RuntimeError(f"date audit row {index} lacks literal dates")
        if index in V34_SOURCE_ONLY_INDEXES:
            reason = (
                "V3.4 source-only execution selected a deterministic slot on the "
                "following-week date, exposing a mismatch hidden by V3.3's "
                "candidate-selection stop."
            )
        elif index == 51:
            reason = (
                "The request resolved to the following week while the old pre-book stayed "
                "on the nearest weekday, so V3.3 incorrectly booked instead of abstaining."
            )
        else:
            reason = (
                "The system used the following-calendar-week reading while V3.3 gold used "
                "the nearest-future weekday."
            )
        audit.append(
            {
                "case_id": f"wf2-{index:04d}",
                "scenario_tier": current["meta"]["tier"],
                "date_phrase": phrase,
                "reference_now": current["meta"]["now"],
                "v3_3_gold_date": old_date,
                "corrected_v3_5_gold_date": corrected_date,
                "system_interpreted_date": corrected_date,
                "v3_3_task_outcome_failed": index in V33_FAILED_INDEXES,
                "first_exposed_by_v3_4_source_only_execution": (
                    index in V34_SOURCE_ONLY_INDEXES
                ),
                "attribution": "evaluation_contract_correction",
                "reason": reason,
            }
        )
    return {
        "schema_version": "3.5",
        "historical_result": "V3.3 WF2 optimised 58/70",
        "current_historical_result": "V3.4.3 WF2 optimised 70/70",
        "interpretation": (
            "The score change is an evaluation-contract correction, not a model-capability "
            "improvement. Twelve V3.3 failures and three additional V3.4 source-only "
            "failures belong to the same 15-case temporal mismatch."
        ),
        "rows": audit,
    }


def write() -> None:
    targets = (OUTPUT, TEMPORAL_CONTRACT, DATE_AUDIT)
    existing = [str(path) for path in targets if path.exists()]
    if existing:
        raise RuntimeError(f"refusing to overwrite frozen V3.5 artifacts: {existing}")
    rows = build_rows()
    OUTPUT.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
        encoding="utf-8",
    )
    TEMPORAL_CONTRACT.write_text(
        json.dumps(build_temporal_contract(rows), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    DATE_AUDIT.write_text(
        json.dumps(build_date_audit(rows), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    write()
