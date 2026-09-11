"""Frozen pre-evidence WF3 lifecycle used only by evaluation baselines.

Production routes use the evidence-first lifecycle in ``workflows.expense``. Keeping this
small baseline adapter under ``evals`` preserves published matched comparisons without
leaving the superseded submit/approve contract reachable from the application.
"""
from typing import Any, Optional

from .. import money
from ..backends.records import RecordStore
from ..workflows import policy
from ..workflows.expense import _flag_json, validate_and_complete_expense


def submit_expense_baseline(fields: dict[str, Any], store: RecordStore, *,
                            submitted_by: str) -> dict[str, Any]:
    draft = validate_and_complete_expense(fields, store)
    if draft.missing_required:
        return {"status": "blocked_missing_required", "missing": draft.missing_required}
    flags = [_flag_json(flag) for flag in draft.flags]
    record = store.create("submissions", "expense_claim", {
        **draft.fields,
        "submitted_by": submitted_by,
        "policy_flags": flags,
        **money.convert(draft.fields.get("amount") or 0.0, draft.fields.get("currency")),
    }, status="submitted")
    return {"status": "submitted", "record_id": record.id, "flags": flags}


def decide_expense_baseline(record_id: str, store: RecordStore, *, decision: str,
                            reviewed_by: str, reason: Optional[str] = None) -> dict[str, Any]:
    record = store.get(record_id)
    if record is None or record.status != "submitted":
        return {"status": "not_pending"}
    if record.data.get("submitted_by") == reviewed_by:
        return {"status": "self_approval_blocked"}
    if decision == "approve":
        flags = validate_and_complete_expense(record.data, store).flags
        if policy.has_hard(flags):
            return {"status": "blocked_policy",
                    "flags": [_flag_json(flag) for flag in flags if flag.severity == "hard"]}
        overridden = [_flag_json(flag) for flag in flags if flag.severity == "soft"]
        store.update(record_id, status="approved", data={
            **record.data, "reviewed_by": reviewed_by, "overridden_flags": overridden,
        })
        return {"status": "approved", "record_id": record_id,
                "overridden_flags": overridden}
    if decision == "reject":
        store.update(record_id, status="rejected", data={
            **record.data, "reviewed_by": reviewed_by, "decision_reason": reason,
        })
        return {"status": "rejected", "record_id": record_id}
    raise ValueError(f"unknown decision: {decision}")
