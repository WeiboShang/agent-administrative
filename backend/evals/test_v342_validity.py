from __future__ import annotations

import copy
import hashlib
import json
import pytest

from backend.backends.records import RecordStore
from backend.agent.vision_extract import (
    CRITICAL_RECEIPT_PROMPT,
    VISION_SYSTEM,
    receipt_to_fields,
)
from backend.evals import outcome_adapters_v34 as adapters
from backend.evals.outcome_adapters_v34 import (
    RECEIPT_CACHE,
    RECEIPT_MANIFEST,
    _images,
    _wf3_condition,
    _wf3_gold,
    build_paired_suite,
)
from backend.evals.outcomes_v3 import (
    EvalCaseRecorder,
    ExpectedRecord,
    GoldFinalState,
    score_case,
)
from backend.evals.receipt_category_gold import observable_category_gold
from backend.evals.receipt_score import load_manifest


def _entry(image: str) -> dict:
    return next(row for row in load_manifest(str(RECEIPT_MANIFEST)) if row["image"] == image)


def _write_critical_cache(tmp_path, entries: list[dict]):
    path = tmp_path / "critical.jsonl"
    rows = [
        {
            "schema_version": "3.4.2",
            "image": entry["image"],
            "model": adapters.VISION_MODEL,
            "image_sha256": hashlib.sha256(
                (adapters.RECEIPT_IMAGE_DIR / entry["image"]).read_bytes()
            ).hexdigest(),
            "prompt_sha256": hashlib.sha256(
                (VISION_SYSTEM + "\n" + CRITICAL_RECEIPT_PROMPT).encode("utf-8")
            ).hexdigest(),
            "critical_read": _images(RECEIPT_CACHE)[entry["image"]],
        }
        for entry in entries
    ]
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    return path


def test_observable_category_gold_handles_conflicting_receipt_evidence() -> None:
    citycab_hotel = observable_category_gold(_entry("clean_5.png")["gold"])
    assert citycab_hotel.accepted == ("accommodation", "meals", "travel")

    cafe_breakfast = observable_category_gold(_entry("clean_10.png")["gold"])
    assert cafe_breakfast.accepted == ("accommodation", "meals", "travel")

    desk_supplies_travel = observable_category_gold(_entry("skewed_8.png")["gold"])
    assert desk_supplies_travel.accepted == ("accommodation", "travel")


def test_category_wording_aliases_normalise_to_the_production_taxonomy() -> None:
    fields = receipt_to_fields(
        {"vendor": "CityCab", "date": "2026-06-01", "amount": 20,
         "currency": "GBP", "category_guess": "transportation"},
        employee_name="Alice Tan",
    )
    assert fields["category"] == "travel"


def test_v342_policy_filter_does_not_let_semantic_categories_change_outcome() -> None:
    store = RecordStore(":memory:", now_fn=lambda: "2026-07-01T09:00:00+00:00")
    over_limit = _entry("over_limit_0.png")
    expected = _wf3_gold(over_limit, store, "v3_4_2_verification").required_records[0]
    assert expected.status == "rejected"
    assert expected.accepted_data == {"category": ["meals"]}

    ambiguous = copy.deepcopy(_entry("clean_10.png"))
    ambiguous["gold"]["amount"] = 85.0
    ambiguous["gold"]["line_items"] = [
        {"desc": "Breakfast", "amount": 85.0}
    ]
    with pytest.raises(RuntimeError, match="policy-sensitive category ambiguity"):
        _wf3_gold(ambiguous, store, "v3_4_2_verification")


def test_accepted_category_values_are_explicit_not_fuzzy() -> None:
    store = RecordStore(":memory:", now_fn=lambda: "2026-07-01T09:00:00+00:00")
    recorder = EvalCaseRecorder(
        store, run_id="accepted-category", result_status="v3_4_2_verification"
    )
    store.create(
        "submissions", "expense_claim",
        {"vendor": "CityCab", "category": "travel"}, status="approved",
    )
    case = recorder.finish(
        case_id="accepted-category", workflow="wf3", condition="optimised_test",
        gold_final_state=GoldFinalState(required_records=[ExpectedRecord(
            store="submissions", type="expense_claim", status="approved",
            data={"vendor": "CityCab"},
            accepted_data={"category": ["travel", "accommodation"]},
        )]),
        review_action={"decision": "approve"},
    )
    assert score_case(case).task_outcome
    wrong = case.model_copy(deep=True)
    wrong.actual_final_state.submissions[-1].data["category"] = "meals"
    assert not score_case(wrong).task_outcome


def test_v342_gold_relabels_cannot_change_wf3_execution(tmp_path, monkeypatch) -> None:
    entry = _entry("clean_5.png")
    extraction = _images(RECEIPT_CACHE)[entry["image"]]
    monkeypatch.setattr(adapters, "RECEIPT_CRITICAL_CACHE", tmp_path / "critical.jsonl")
    monkeypatch.setattr(adapters, "frozen_cache_bundle_version", lambda paths: "test-cache")
    adapters.RECEIPT_CRITICAL_CACHE.write_text("{}\n", encoding="utf-8")
    original = _wf3_condition(
        0, entry, extraction, optimised=True, result_status="v3_4_2_verification",
        critical_read=extraction,
    )
    relabelled_entry = copy.deepcopy(entry)
    relabelled_entry["gold"]["category"] = "other"
    relabelled_entry["gold"]["line_items"] = [{"desc": "Misc item", "amount": 24.95}]
    relabelled = _wf3_condition(
        0, relabelled_entry, extraction, optimised=True,
        result_status="v3_4_2_verification", critical_read=extraction,
    )
    assert original.actual_final_state == relabelled.actual_final_state
    assert original.gold_final_state != relabelled.gold_final_state


def test_v342_soft_warning_has_audited_override_reason(tmp_path, monkeypatch) -> None:
    entry = _entry("clean_5.png")
    extraction = _images(RECEIPT_CACHE)[entry["image"]]
    monkeypatch.setattr(adapters, "RECEIPT_CRITICAL_CACHE", tmp_path / "critical.jsonl")
    monkeypatch.setattr(adapters, "frozen_cache_bundle_version", lambda paths: "test-cache")
    adapters.RECEIPT_CRITICAL_CACHE.write_text("{}\n", encoding="utf-8")
    case = _wf3_condition(
        0, entry, extraction, optimised=True, result_status="v3_4_2_verification",
        critical_read=extraction,
    )
    check = case.deterministic_checks[0]
    assert check["decision"]["status"] == "approved"


def test_v342_pairs_share_source_output_state_and_semantic_gold(tmp_path, monkeypatch) -> None:
    entries = load_manifest(str(RECEIPT_MANIFEST))[:2]
    critical_cache = _write_critical_cache(tmp_path, entries)
    monkeypatch.setattr(adapters, "RECEIPT_CRITICAL_CACHE", critical_cache)
    monkeypatch.setattr(adapters, "frozen_cache_bundle_version", lambda paths: "test-cache")
    cases = build_paired_suite(
        limit_per_workflow=2, result_status="v3_4_2_verification"
    )
    grouped: dict[tuple[str, str], list] = {}
    for case in cases:
        grouped.setdefault((case.workflow, case.case_id), []).append(case)
    for pair in grouped.values():
        assert len(pair) == 2
        assert pair[0].initial_state == pair[1].initial_state
        assert pair[0].model_draft == pair[1].model_draft
        assert pair[0].gold_final_state == pair[1].gold_final_state


def test_v342_formal_status_uses_v342_contract() -> None:
    cases = build_paired_suite(
        limit_per_workflow=1, result_status="v3_4_2_formal"
    )
    assert {case.evaluation_version for case in cases} == {"v3.4.2"}
    assert {case.result_status for case in cases} == {"v3_4_2_formal"}
