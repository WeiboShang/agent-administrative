from __future__ import annotations

from collections import Counter
from datetime import datetime

import pytest

from backend.evals import human_v5 as v5
from backend.evals import freeze_human_v5_cache as freezer
from backend.workflows.scheduling import resolve_relative_date


def _execute(case_id: str, submission: v5.HumanCaseSubmissionV5) -> dict:
    material = v5.prepare_case_v5(case_id)
    return v5.execute_case_v5(
        session_id="human-v5-test", case_id=case_id, submission=submission,
        material=material, server_started_at=v5.utc_now(), server_completed_at=v5.utc_now(),
    )


def test_manifest_is_counterbalanced_and_source_aligned() -> None:
    manifest = v5.load_manifest_v5()
    assert len(manifest.cases) == 42
    formal = [row for row in manifest.cases if not row.pilot]
    assert sorted(row.presentation_order for row in formal) == list(range(1, 37))
    for workflow in ("wf1", "wf2", "wf3"):
        rows = [row for row in formal if row.workflow == workflow]
        assert Counter(row.condition for row in rows) == {"manual": 6, "agent_assisted": 6}
        assert Counter(row.scenario_family for row in rows) == {
            "ordinary": 4, "underspecified_degraded": 4, "complex_safety": 4
        }


def test_collection_gate_rejects_incomplete_actual_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(v5, "_cache_index", lambda: {})
    with pytest.raises(RuntimeError, match="frozen cache is incomplete"):
        v5.validate_protocol_v5(require_frozen_cache=True)


def test_protocol_cannot_be_sealed_with_partial_cache(
    tmp_path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    temporary_manifest = tmp_path / "manifest.json"
    temporary_manifest.write_bytes(v5.MANIFEST_PATH.read_bytes())
    temporary_cache = tmp_path / "cache.jsonl"
    temporary_cache.write_text("", encoding="utf-8")
    monkeypatch.setattr(freezer, "MANIFEST", temporary_manifest)
    monkeypatch.setattr(freezer, "CACHE", temporary_cache)
    with pytest.raises(RuntimeError, match="expected 21 cache rows"):
        freezer.seal()


def test_public_projection_does_not_deserialise_gold(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden() -> dict:
        raise AssertionError("gold was read while preparing reviewer material")

    monkeypatch.setattr(v5, "_gold_cases", forbidden)
    manual = v5.prepare_case_v5("wf2-v51-p01-a")
    agent = v5.prepare_case_v5("wf3-v51-p02-a")
    assert manual.agent_assistance is None
    assert agent.agent_assistance is not None


def test_public_projection_contains_no_gold_keys() -> None:
    material = v5.prepare_case_v5("wf3-v51-p06-a").model_dump(mode="json")
    v5._public_check(material)
    serialised = str(material)
    assert "expected_decisions" not in serialised
    assert "correct_answer" not in serialised


def test_v5_temporal_contract_distinguishes_next_week() -> None:
    anchor = datetime.fromisoformat("2026-06-30T09:00:00")
    assert resolve_relative_date("Wednesday", anchor) == "2026-07-01"
    assert resolve_relative_date("this Wednesday", anchor) == "2026-07-01"
    assert resolve_relative_date("next Wednesday", anchor) == "2026-07-08"


def test_agent_missing_time_never_generates_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = {
        "operation": "CREATE", "title": "Audit planning", "participants": ["Chen"],
        "date": "next Tuesday", "time": None, "duration_minutes": 30, "mode": "virtual",
    }
    monkeypatch.setattr(v5, "_cache_index", lambda: {
        "wf2-v51-p03-b": {"raw_extraction": raw}
    })
    material = v5.prepare_case_v5("wf2-v51-p03-b")
    candidate_check = next(row for row in material.reviewer_visible_checks if row["type"] == "candidate_search")
    essential = next(row for row in material.reviewer_visible_checks if row["type"] == "essential_information")
    assert candidate_check["candidates"] == []
    assert "time" in essential["missing"]
    assert material.form_defaults["time"] is None


def test_wf1_hard_fields_and_missing_field_are_scored() -> None:
    result = _execute("wf1-v51-p03-a", v5.HumanCaseSubmissionV5(
        decision="route", actions=[v5.ReviewedActionV5(
            action_type="schedule_meeting",
            fields={
                "title": "Q4 forecast", "participants": ["Chen", "Dana"],
                "date": "2026-08-26", "time": None, "duration_minutes": 60,
            },
        )],
    ))
    assert result["score"]["task_success"] is True
    invented = _execute("wf1-v51-p03-a", v5.HumanCaseSubmissionV5(
        decision="route", actions=[v5.ReviewedActionV5(
            action_type="schedule_meeting",
            fields={
                "title": "Q4 forecast", "participants": ["Chen", "Dana"],
                "date": "2026-08-26", "time": "09:00", "duration_minutes": 60,
            },
        )],
    ))
    assert invented["score"]["task_success"] is False
    assert invented["score"]["field_pass"] is False


def test_wf2_decision_and_final_state_are_both_required() -> None:
    request = _execute("wf2-v51-p03-a", v5.HumanCaseSubmissionV5(
        decision="request_information", reason="What time should the meeting start?"
    ))
    assert request["score"]["task_success"] is True
    wrong = _execute("wf2-v51-p03-a", v5.HumanCaseSubmissionV5(
        decision="reject", reason="No time was provided."
    ))
    assert wrong["score"]["state_pass"] is True
    assert wrong["score"]["decision_pass"] is False
    assert wrong["score"]["task_success"] is False


def test_agent_conflict_suggests_free_slot_that_can_be_approved() -> None:
    fields = {
        "title": "Access controls", "participants": ["Dana", "Chen"],
        "date": "2026-08-20", "time": "10:00", "duration_minutes": 60,
        "location": "Lyra",
    }
    preflight = v5.preflight_case_v5("wf2-v51-p05-a", fields)
    assert preflight["approve_blocked"] is True
    assert any(row["rule"] == "conflict" for row in preflight["alerts"])
    assert any(row["rule"] == "room_double_booked" for row in preflight["alerts"])
    assert all(
        row["required_decision"] == "choose_another_time"
        for row in preflight["alerts"]
        if row["rule"] in {"conflict", "room_double_booked"}
    )
    assert len(preflight["suggested_alternatives"]) == 3
    with pytest.raises(ValueError, match="another conflict-free time"):
        _execute("wf2-v51-p05-a", v5.HumanCaseSubmissionV5(
            decision="approve", final_fields=fields,
        ))
    choice = preflight["suggested_alternatives"][0]
    rescued = _execute("wf2-v51-p05-a", v5.HumanCaseSubmissionV5(
        decision="approve",
        final_fields={**fields, "date": choice["date"], "time": choice["start"]},
    ))
    assert rescued["score"]["task_success"] is True


def test_manual_conflict_exposes_no_agent_suggestions() -> None:
    preflight = v5.preflight_case_v5("wf2-v51-p05-b", {
        "title": "Meeting", "participants": ["Evan", "Fiona"],
        "date": "2026-08-19", "time": "11:00", "duration_minutes": 30,
        "location": "Vega",
    })
    assert preflight["approve_blocked"] is True
    assert preflight["suggested_alternatives"] == []
    for decision in ("reject", "request_information"):
        result = _execute("wf2-v51-p05-b", v5.HumanCaseSubmissionV5(
            decision=decision,
            reason="The requested time conflicts with an existing meeting.",
        ))
        assert result["score"]["task_success"] is True


def test_hard_field_canonicalisation_accepts_accents_and_room_aliases() -> None:
    passed, predicates = v5._field_predicates(
        {"vendor": "Cafe Aurora", "location": "Vega-room"},
        {"vendor": "Café Aurora", "location": "Vega"},
    )
    assert passed is True
    assert all(row["passed"] for row in predicates)


def test_wf1_requester_is_a_default_participant() -> None:
    material = v5.prepare_case_v5("wf1-v51-p01-b")
    assert material.reference["default_meeting_participant"] == "Fiona Reyes"
    result = _execute("wf1-v51-p01-b", v5.HumanCaseSubmissionV5(
        decision="route", actions=[v5.ReviewedActionV5(
            action_type="schedule_meeting",
            fields={
                "title": "Operations handover", "participants": ["Bob"],
                "date": "2026-08-27", "time": "16:00", "duration_minutes": 30,
            },
        )],
    ))
    assert result["score"]["task_success"] is True


def test_wf3_over_limit_is_a_hard_reject() -> None:
    material = v5.prepare_case_v5("wf3-v51-p05-a")
    preflight = v5.preflight_case_v5("wf3-v51-p05-a", material.form_defaults)
    assert preflight["approve_blocked"] is True
    over_limit = next(row for row in preflight["alerts"] if row["rule"] == "over_limit")
    assert over_limit["severity"] == "hard"
    assert over_limit["required_decision"] == "reject"
    with pytest.raises(ValueError, match="Decision was not executed"):
        _execute("wf3-v51-p05-a", v5.HumanCaseSubmissionV5(
            decision="approve", final_fields=material.form_defaults,
        ))
    rejected = _execute("wf3-v51-p05-a", v5.HumanCaseSubmissionV5(
        decision="reject", final_fields=material.form_defaults,
        reason="The claim exceeds the mandatory meals limit.",
    ))
    assert rejected["score"]["task_success"] is True


def test_wf3_duplicate_rejection_is_safe_success() -> None:
    material = v5.prepare_case_v5("wf3-v51-p06-a")
    result = _execute("wf3-v51-p06-a", v5.HumanCaseSubmissionV5(
        decision="reject", final_fields=material.form_defaults,
        reason="Exact duplicate of the approved claim.",
    ))
    assert result["score"]["task_success"] is True
    assert result["score"]["unsafe_action"] is False
    preflight = v5.preflight_case_v5("wf3-v51-p06-a", material.form_defaults)
    duplicate = next(row for row in preflight["alerts"] if row["rule"] == "duplicate")
    assert duplicate["severity"] == "hard"
    assert "CityCab" in duplicate["message"]
    assert "2026-06-24" in duplicate["message"]


def test_every_v51_gold_safe_completion_executes_successfully() -> None:
    gold = v5._gold_cases()
    for spec in v5.load_manifest_v5().cases:
        expected = gold[spec.case_id]
        decision = expected["expected_decisions"][0]
        material = v5.prepare_case_v5(spec.case_id)
        kwargs: dict = {
            "decision": decision,
            "reason": "Reviewer followed the displayed policy information."
            if decision in {"reject", "request_information"} or expected.get("reason_required")
            else None,
        }
        if spec.workflow == "wf1":
            kwargs["actions"] = [v5.ReviewedActionV5(
                action_type=action["action_type"],
                fields={key: value for key, value in action.get("hard_fields", {}).items()
                        if key != "attachment_ids"},
                attachment_ids=action.get("hard_fields", {}).get("attachment_ids", []),
            ) for action in expected.get("actions", [])]
        elif spec.workflow == "wf2":
            kwargs["final_fields"] = {"title": "Reviewed meeting", **expected.get("hard_fields", {})}
            if expected.get("slot_policy") == "conflict_free_alternative":
                alternative_slots = {
                    "pilot-wf2-agent-v51": ("2026-08-20", "09:30"),
                    "wf2-v51-p05-a": ("2026-08-20", "09:00"),
                    "wf2-v51-p05-b": ("2026-08-19", "09:00"),
                    "wf2-v51-p06-a": ("2026-08-28", "09:00"),
                    "wf2-v51-p06-b": ("2026-08-18", "10:00"),
                }
                date, time = alternative_slots[spec.case_id]
                kwargs["final_fields"].update({"date": date, "time": time})
        else:
            kwargs["final_fields"] = {
                **material.form_defaults, **expected.get("critical_fields", {}),
                "category": material.form_defaults.get("category") or "travel",
                "business_purpose": material.form_defaults.get("business_purpose") or "Business expense",
            }
            kwargs["acknowledge_warnings"] = bool(expected.get("required_acknowledgements"))
        result = _execute(spec.case_id, v5.HumanCaseSubmissionV5(**kwargs))
        assert result["score"]["task_success"] is True, spec.case_id
