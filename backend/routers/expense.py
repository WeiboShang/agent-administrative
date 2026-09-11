"""WF3 expense API — receipt upload → vision extract → validate → gate → execute.

Backed by the shared persistent RecordStore. Vision calls run in a threadpool so they do
not block the event loop; tests replace the workspace with an isolated in-memory store.
"""
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from ..agent.vision_extract import (
    _CATEGORIES,
    PAYMENT_METHODS,
    extract_receipt,
    extract_receipt_critical,
    receipt_to_fields,
)
from .. import money
from ..config import VISION_MODEL
from ..fixtures import org
from ..reports.expense_excel import export_expense_workbook
from ..workflows import policy
from ..workflows.content import draft_decision_note, store_note
from ..workflows.expense import (
    decide_expense_evidence,
    request_expense_information,
    resubmit_expense,
    submit_expense_evidence,
    validate_and_complete_expense,
)
from ..workflows.expense_reconciliation import (
    critical_read_triggers,
    reconcile_expense_evidence,
)
from ..workflows.expense_evidence import (
    EVIDENCE_DIR,
    evidence_payload,
    persist_receipt,
    verify_receipt_evidence,
)
from ._store import store as _store

router = APIRouter(prefix="/api/expense")


def _flags_json(flags: list[policy.Flag]) -> list[dict[str, str]]:
    return [{"rule": f.rule, "severity": f.severity, "message": f.message} for f in flags]


@router.get("/options")
async def options() -> dict[str, Any]:
    """Dropdown option sets for the review form (fixed vocabularies live in CODE)."""
    return {
        "departments": list(org.BUDGETS.keys()),
        "categories": sorted(_CATEGORIES),
        "payment_methods": list(PAYMENT_METHODS),
        "actors": [{"id": p.user_id, "name": p.name,
                    "is_approver": org.is_expense_approver(p.user_id)} for p in org.PEOPLE],
        # major world currencies (ISO 4217 codes) — every one has a rate in money.FX_TO_GBP
        "currencies": ["GBP", "USD", "EUR", "CNY", "JPY", "HKD", "AUD", "CAD", "CHF", "SGD"],
        # reported so the UI can't drift from the configured model (it displayed a
        # hard-coded "Llama 4 Scout" for a day after that model was retired)
        "vision_model": VISION_MODEL.split("/")[-1],
        # the review form shows the GBP equivalent live as the user types, so it needs the
        # table locally — a round-trip per keystroke to multiply two numbers would be silly.
        # Served from here so no rate is ever hardcoded in JS.
        "fx_rates": money.FX_TO_GBP,
        "fx_rate_date": money.FX_RATE_DATE,
        "fx_rate_source": money.FX_RATE_SOURCE,
    }


@router.get("/ledger")
async def ledger() -> dict[str, Any]:
    records = [{"id": r.id, "status": r.status, **r.data}
               for r in _store.list("submissions", record_type="expense_claim")]
    budgets = {dept: {"total": total, "remaining": policy.budget_remaining(dept, _store)}
               for dept, total in org.BUDGETS.items()}
    approved_gbp = [money.gbp_of(r) for r in records if r.get("status") == "approved"]
    return {"records": records, "budgets": budgets,
            # GBP so the footer total is meaningful across mixed-currency claims
            "approved_total_gbp": round(sum(v for v in approved_gbp if v is not None), 2)}


@router.get("/ledger/export.xlsx")
async def export_ledger() -> Response:
    """Download the submitted/decided expense register as one business-facing sheet."""
    content = export_expense_workbook(
        _store.list("submissions", record_type="expense_claim")
    )
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    return Response(
        content=content,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": (
                f'attachment; filename="wf3_receipts_{stamp}.xlsx"'
            )
        },
    )


class NoteRequest(BaseModel):
    record_id: str
    model: Optional[str] = None


@router.post("/draft_note")
async def draft_note(req: NoteRequest) -> dict[str, Any]:
    """O4 content generation: draft the decision note GROUNDED in the decided record +
    flags (never the original chat). Draft is stored, never sent (store_draft)."""
    rec = _store.get(req.record_id)
    if rec is None or rec.status not in ("approved", "rejected"):
        return {"status": "not_decided"}
    note = await asyncio.to_thread(
        draft_decision_note, rec.data, rec.status,
        reason=rec.data.get("decision_reason"),
        flags=(rec.data.get("overridden_flags") or rec.data.get("policy_flags")),
        model=req.model)
    if "error" in note:
        return {"status": "error", **note}
    saved = store_note(_store, claim_id=rec.id, note=note, decision=rec.status)
    return {"status": "draft", "note_id": saved.id,
            "subject": note["subject"], "body": note["body"]}


class SaveNoteRequest(BaseModel):
    note_id: str
    subject: str
    body: str


@router.post("/save_note")
async def save_note(req: SaveNoteRequest) -> dict[str, Any]:
    """Human-edited version replaces the draft (still status='draft', never sent)."""
    rec = _store.get(req.note_id)
    if rec is None or rec.type != "decision_note":
        return {"status": "not_found"}
    _store.update(req.note_id, data={**rec.data, "subject": req.subject,
                                     "body": req.body, "edited": True})
    return {"status": "saved", "note_id": req.note_id}


@router.get("/notes")
async def notes() -> dict[str, Any]:
    return {"items": [{"id": r.id, "status": r.status, **r.data}
                      for r in _store.list("submissions", record_type="decision_note")]}


@router.post("/evidence/extract")
async def extract_evidence(file: UploadFile = File(...),
                           employee_name: str = Form("Alice Tan")) -> dict[str, Any]:
    data = await file.read()
    mime = file.content_type or "image/png"
    vision = await asyncio.to_thread(extract_receipt, data, mime=mime)
    critical_triggers = critical_read_triggers(vision)
    # V3.4.2 locks one independent critical-field read for every receipt.  Triggers are
    # retained as diagnostics only; they never decide whether evidence is available.
    second_read = await asyncio.to_thread(extract_receipt_critical, data, mime=mime)
    # Persist only after both model reads succeed; failed extraction must not leave an
    # unreferenced cache file behind.
    evidence = persist_receipt(data, mime_type=mime, filename=file.filename)
    fields = receipt_to_fields(vision, employee_name=employee_name)
    fields, reconciliation = reconcile_expense_evidence(
        fields, vision, _store, second_read=second_read
    )
    person = org.find_person(employee_name)
    fields["department"] = person.department if person else None
    fields["image_phash"] = evidence["image_phash"]
    draft = validate_and_complete_expense(
        fields, _store, extracted_amount=vision.get("amount"),
        line_items=vision.get("line_items") or [],
    )
    return {
        "vision": vision,
        "extraction_snapshot": vision,
        "critical_second_read": second_read,
        "critical_read_triggers": list(critical_triggers),
        "evidence": evidence,
        "fields": draft.fields,
        "reconciliation": reconciliation,
        "missing": draft.missing_required,
        "completeness": draft.completeness,
        "flags": _flags_json(draft.flags),
    }


class EvidenceSubmitRequest(BaseModel):
    fields: dict[str, Any]
    extraction_snapshot: dict[str, Any]
    critical_second_read: dict[str, Any]
    evidence: dict[str, Any]
    submitted_by: str = "alice"
    changed_fields: list[str] = Field(default_factory=list)
    idempotency_key: str


@router.post("/evidence/submit")
async def evidence_submit(req: EvidenceSubmitRequest) -> dict[str, Any]:
    try:
        evidence = verify_receipt_evidence(req.evidence)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return submit_expense_evidence(
        req.fields, _store, submitted_by=req.submitted_by,
        changed_fields=req.changed_fields, extraction_snapshot=req.extraction_snapshot,
        second_read=req.critical_second_read, evidence=evidence,
        idempotency_key=req.idempotency_key,
    )


class InformationRequest(BaseModel):
    reviewed_by: str = "chen"
    expected_version: int
    issues: list[str]
    request_text: str
    idempotency_key: str


@router.post("/claims/{record_id}/request-information")
async def request_information(record_id: str, req: InformationRequest) -> dict[str, Any]:
    return request_expense_information(
        record_id, _store, reviewed_by=req.reviewed_by,
        expected_version=req.expected_version, issues=req.issues,
        request_text=req.request_text, idempotency_key=req.idempotency_key,
    )


class ResubmitRequest(BaseModel):
    fields: dict[str, Any]
    submitted_by: str = "alice"
    expected_version: int
    changed_fields: list[str] = Field(default_factory=list)
    idempotency_key: str


@router.post("/claims/{record_id}/resubmit")
async def resubmit(record_id: str, req: ResubmitRequest) -> dict[str, Any]:
    return resubmit_expense(
        record_id, req.fields, _store, submitted_by=req.submitted_by,
        expected_version=req.expected_version, changed_fields=req.changed_fields,
        idempotency_key=req.idempotency_key,
    )


class EvidenceDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    reviewed_by: str = "chen"
    expected_version: int
    reason: Optional[str] = None
    acknowledged_flags: list[str] = Field(default_factory=list)
    idempotency_key: str


@router.post("/claims/{record_id}/decision")
async def evidence_decision(record_id: str, req: EvidenceDecisionRequest) -> dict[str, Any]:
    return decide_expense_evidence(
        record_id, _store, decision=req.decision, reviewed_by=req.reviewed_by,
        expected_version=req.expected_version, reason=req.reason,
        acknowledged_flags=req.acknowledged_flags,
        idempotency_key=req.idempotency_key,
    )


@router.get("/evidence/queue")
async def evidence_queue() -> dict[str, Any]:
    items = []
    for status in ("submitted", "resubmitted", "needs_information"):
        items.extend({
            "id": record.id, "status": record.status, "type": record.type,
            "created_at": record.created_at, "updated_at": record.updated_at, **record.data,
            "evidence": evidence_payload(record.data),
        } for record in _store.list("submissions", status=status))
    return {"items": sorted(items, key=lambda item: item["created_at"], reverse=True)}


@router.get("/routed-drafts")
async def routed_expense_drafts() -> dict[str, Any]:
    """WF1 expense hand-offs awaiting evidence/extraction; no claim is submitted here."""
    statuses = {"needs_evidence", "pending_extraction", "pending_exception_review"}
    return {"items": [
        {"id": record.id, "status": record.status, "type": record.type, **record.data}
        for record in _store.list("submissions", record_type="expense_claim")
        if record.status in statuses
    ]}


@router.get("/claims/{record_id}")
async def claim_detail(record_id: str) -> dict[str, Any]:
    record = _store.get(record_id)
    if record is None or record.type != "expense_claim":
        raise HTTPException(status_code=404, detail="claim not found")
    return {"id": record.id, "status": record.status, **record.data,
            "evidence": evidence_payload(record.data)}


@router.get("/claims/{record_id}/receipt")
async def claim_receipt(record_id: str) -> FileResponse:
    record = _store.get(record_id)
    if record is None or not record.data.get("receipt_ref"):
        raise HTTPException(status_code=404, detail="receipt not found")
    path = Path(str(record.data["receipt_ref"])).resolve()
    if EVIDENCE_DIR.resolve() not in path.parents or not path.exists():
        raise HTTPException(status_code=404, detail="receipt not found")
    return FileResponse(path, media_type=record.data.get("receipt_mime_type"))
