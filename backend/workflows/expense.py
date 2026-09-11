"""WF3 expense claim — deterministic core (docs/wf3_expense_design.md).

The vision LLM extracts receipt fields (part 2); everything here is CODE (CLAUDE.md §4.4):
schema validation via the registry, missing-field detection, the policy engine, and the
write to the submissions store. **Approve is gated** — a hard policy flag or a missing
required field blocks the write even on approve. Budget/quota consumption is derived from
the approved records, so a successful approve *is* the decrement.
"""
from dataclasses import dataclass, field
from typing import Any, Optional

from .. import money
from ..backends.records import RecordStore
from . import policy
from .expense_evidence import immutable_snapshot, revision, utc_now, verification_states
from .form_prefill import validate_and_complete_form


@dataclass
class ExpenseDraft:
    fields: dict[str, Any]
    missing_required: list[str]
    completeness: float
    flags: list[policy.Flag] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _flag_json(f: policy.Flag) -> dict[str, str]:
    return {"rule": f.rule, "severity": f.severity, "message": f.message}


def validate_and_complete_expense(fields: dict[str, Any], store: RecordStore, *,
                                  extracted_amount: Optional[float] = None,
                                  line_items: Optional[list[dict[str, Any]]] = None,
                                  ) -> ExpenseDraft:
    """Validate an extracted expense claim + run the policy engine (the review-time draft).

    ``line_items`` (receipt line descriptions, available at review time only) widen the
    non-reimbursable screen; the flags attached at submit come from the form fields."""
    draft, missing, notes = validate_and_complete_form(
        {"form_type": "expense_claim", "fields": dict(fields)}
    )
    flags = policy.check_expense(draft.fields, store, extracted_amount=extracted_amount,
                                 line_items=line_items)
    return ExpenseDraft(draft.fields, missing, draft.completeness, flags, notes)


def _find_idempotent(store: RecordStore, key: str) -> Optional[str]:
    if not key:
        return None
    return next((record.id for record in store.list("submissions")
                 if record.data.get("idempotency_key") == key
                 or key in (record.data.get("idempotency_keys") or [])), None)


def _idempotency_keys(data: dict[str, Any], key: str) -> list[str]:
    keys = list(data.get("idempotency_keys") or [])
    legacy = data.get("idempotency_key")
    if legacy and legacy not in keys:
        keys.append(legacy)
    if key and key not in keys:
        keys.append(key)
    return keys


def submit_expense_evidence(fields: dict[str, Any], store: RecordStore, *, submitted_by: str,
                            changed_fields: Optional[list[str]] = None,
                            extraction_snapshot: Optional[dict[str, Any]] = None,
                            second_read: Optional[dict[str, Any]] = None,
                            evidence: Optional[dict[str, Any]] = None,
                            idempotency_key: str = "",
                            now: str | None = None) -> dict[str, Any]:
    replay = _find_idempotent(store, idempotency_key)
    if replay:
        return {"status": "idempotent_replay", "record_id": replay}
    extraction = immutable_snapshot(extraction_snapshot or {})
    extracted_amount = extraction.get("amount")
    line_items = fields.get("line_items") or extraction.get("line_items") or []
    draft = validate_and_complete_expense(
        fields, store, extracted_amount=extracted_amount, line_items=line_items
    )
    if draft.missing_required:
        return {"status": "blocked_missing_required", "missing": draft.missing_required}
    flags = [_flag_json(flag) for flag in draft.flags]
    submitted_snapshot = immutable_snapshot(draft.fields)
    at = now or utc_now()
    data = {
        **draft.fields,
        **(evidence or {}),
        **money.convert(draft.fields.get("amount") or 0.0, draft.fields.get("currency")),
        "submitted_by": submitted_by,
        "extraction_snapshot": extraction,
        "critical_second_read": immutable_snapshot(second_read or {}),
        "submitted_snapshot": submitted_snapshot,
        "policy_flags": flags,
        "verification_states": verification_states(
            extraction, submitted_snapshot, second_read=second_read,
            missing=draft.missing_required, policy_flags=flags
        ),
        "version": 1,
        "revisions": [revision(
            version=1, actor=submitted_by, fields=submitted_snapshot,
            changed_fields=changed_fields, reason="employee_submit", timestamp=at
        )],
        "audit_events": [{
            "actor": submitted_by, "action": "submit", "timestamp": at,
            "version": 1, "reason_code": "employee_verified"
        }],
        "idempotency_keys": _idempotency_keys({}, idempotency_key),
        "submitted_at": at,
    }
    record = store.create("submissions", "expense_claim", data, status="submitted")
    return {"status": "submitted", "record_id": record.id, "version": 1, "flags": flags}


def request_expense_information(record_id: str, store: RecordStore, *, reviewed_by: str,
                                expected_version: int, issues: list[str],
                                request_text: str,
                                idempotency_key: str) -> dict[str, Any]:
    replay = _find_idempotent(store, idempotency_key)
    if replay:
        return {"status": "idempotent_replay", "record_id": replay}
    record = store.get(record_id)
    if record is None or record.status not in {"submitted", "resubmitted"}:
        return {"status": "not_pending"}
    if int(record.data.get("version") or 1) != expected_version:
        return {"status": "stale_version", "version": record.data.get("version")}
    if not issues or not request_text.strip():
        return {"status": "issues_and_request_text_required"}
    version = expected_version + 1
    event = {
        "actor": reviewed_by, "action": "request_information", "timestamp": utc_now(),
        "version": version, "reason_code": "evidence_or_field_issue", "issues": issues,
    }
    data = {
        **record.data,
        "version": version,
        "information_request": {"issues": issues, "text": request_text.strip(),
                                "reviewed_by": reviewed_by, "timestamp": event["timestamp"]},
        "audit_events": [*(record.data.get("audit_events") or []), event],
        "idempotency_keys": _idempotency_keys(record.data, idempotency_key),
    }
    updated = store.update_if_version(
        record_id, expected_version=expected_version,
        allowed_statuses={"submitted", "resubmitted"}, data=data,
        status="needs_information",
    )
    if updated is None:
        return {"status": "stale_transition"}
    return {"status": "needs_information", "record_id": record_id, "version": version}


def resubmit_expense(record_id: str, fields: dict[str, Any], store: RecordStore, *,
                     submitted_by: str, expected_version: int,
                     changed_fields: Optional[list[str]] = None,
                     idempotency_key: str) -> dict[str, Any]:
    replay = _find_idempotent(store, idempotency_key)
    if replay:
        return {"status": "idempotent_replay", "record_id": replay}
    record = store.get(record_id)
    if record is None or record.status != "needs_information":
        return {"status": "not_awaiting_information"}
    if record.data.get("submitted_by") != submitted_by:
        return {"status": "employee_mismatch"}
    if int(record.data.get("version") or 1) != expected_version:
        return {"status": "stale_version", "version": record.data.get("version")}
    merged = {**record.data.get("submitted_snapshot", {}), **fields}
    extraction = record.data.get("extraction_snapshot") or {}
    draft = validate_and_complete_expense(
        merged, store, extracted_amount=extraction.get("amount"),
        line_items=merged.get("line_items") or extraction.get("line_items") or [],
    )
    if draft.missing_required:
        return {"status": "blocked_missing_required", "missing": draft.missing_required}
    version = expected_version + 1
    flags = [_flag_json(flag) for flag in draft.flags]
    snapshot = immutable_snapshot(draft.fields)
    data = {
        **record.data,
        **draft.fields,
        "submitted_snapshot": snapshot,
        "policy_flags": flags,
        "verification_states": verification_states(
            extraction, snapshot, second_read=record.data.get("critical_second_read"),
            policy_flags=flags,
        ),
        "version": version,
        "revisions": [*(record.data.get("revisions") or []), revision(
            version=version, actor=submitted_by, fields=snapshot,
            changed_fields=changed_fields, reason="employee_resubmit"
        )],
        "audit_events": [*(record.data.get("audit_events") or []), {
            "actor": submitted_by, "action": "resubmit", "timestamp": utc_now(),
            "version": version, "reason_code": "information_supplied"
        }],
        "resubmitted_at": utc_now(),
        "idempotency_keys": _idempotency_keys(record.data, idempotency_key),
    }
    updated = store.update_if_version(
        record_id, expected_version=expected_version,
        allowed_statuses={"needs_information"}, data=data, status="resubmitted",
    )
    if updated is None:
        return {"status": "stale_transition"}
    return {"status": "resubmitted", "record_id": record_id, "version": version}


def decide_expense_evidence(record_id: str, store: RecordStore, *, decision: str,
                            reviewed_by: str, expected_version: int,
                            reason: Optional[str], acknowledged_flags: list[str],
                            idempotency_key: str,
                            now: str | None = None) -> dict[str, Any]:
    if decision not in {"approve", "reject"}:
        raise ValueError(f"unknown decision: {decision}")
    replay = _find_idempotent(store, idempotency_key)
    if replay:
        return {"status": "idempotent_replay", "record_id": replay}
    record = store.get(record_id)
    if record is None or record.status not in {"submitted", "resubmitted"}:
        return {"status": "not_pending"}
    if int(record.data.get("version") or 1) != expected_version:
        return {"status": "stale_version", "version": record.data.get("version")}
    if record.data.get("submitted_by") == reviewed_by:
        return {"status": "self_approval_blocked"}
    if decision == "reject" and not str(reason or "").strip():
        return {"status": "reason_required"}

    extraction = record.data.get("extraction_snapshot") or {}
    # Migrated records have a submitted snapshot; the record body is the conservative
    # compatibility source if an unrecoverable pre-evidence row reaches this function.
    current = record.data.get("submitted_snapshot") or record.data
    draft = validate_and_complete_expense(
        current, store, extracted_amount=extraction.get("amount"),
        line_items=current.get("line_items") or extraction.get("line_items") or [],
    )
    flags = [_flag_json(flag) for flag in draft.flags]
    if decision == "approve":
        if draft.missing_required:
            return {"status": "blocked_missing_required", "missing": draft.missing_required}
        hard = [flag for flag in flags if flag["severity"] == "hard"]
        if hard:
            return {"status": "blocked_policy", "flags": hard}
        soft_rules = {flag["rule"] for flag in flags if flag["severity"] == "soft"}
        if soft_rules - set(acknowledged_flags):
            return {"status": "override_acknowledgement_required",
                    "missing_acknowledgements": sorted(soft_rules - set(acknowledged_flags))}
        if soft_rules and not str(reason or "").strip():
            return {"status": "override_reason_required"}

    version = expected_version + 1
    status = "approved" if decision == "approve" else "rejected"
    at = now or utc_now()
    data = {
        **record.data,
        "version": version,
        "reviewed_by": reviewed_by,
        "decision_reason": str(reason or "").strip() or None,
        "overridden_flags": [flag for flag in flags if flag["severity"] == "soft"],
        "final_policy_flags": flags,
        "idempotency_keys": _idempotency_keys(record.data, idempotency_key),
        "decided_at": at,
        "audit_events": [*(record.data.get("audit_events") or []), {
            "actor": reviewed_by, "action": status, "timestamp": at,
            "version": version, "reason_code": "human_decision",
            "acknowledged_flags": acknowledged_flags,
        }],
    }
    updated = store.update_if_version(
        record_id, expected_version=expected_version,
        allowed_statuses={"submitted", "resubmitted"}, data=data, status=status,
    )
    if updated is None:
        return {"status": "stale_transition"}
    return {"status": status, "record_id": record_id, "version": version,
            "overridden_flags": data["overridden_flags"]}
