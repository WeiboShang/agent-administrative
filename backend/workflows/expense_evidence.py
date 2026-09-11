"""WF3 evidence, revision and verification primitives.

The receipt bytes and first extraction are immutable. Human edits create versions; policy
and verification states are derived again at every transition.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..agent.image_hash import dhash, hamming

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = PROJECT_ROOT / "data" / "receipt_evidence"
RECEIPT_ARCHIVE_DIR = PROJECT_ROOT / "data" / "receipts"
CRITICAL_FIELDS = ("vendor", "date", "amount", "currency")
LEGACY_PHASH_TOLERANCE = 8
LEGACY_RECOVERY_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalise_vendor(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def persist_receipt(data: bytes, *, mime_type: str, filename: str | None) -> dict[str, Any]:
    sha256 = hashlib.sha256(data).hexdigest()
    receipt_id = f"rcpt-{sha256[:16]}"
    suffix = Path(filename or "").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".pdf"}:
        suffix = ".png" if mime_type.startswith("image/") else ".bin"
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE_DIR / f"{receipt_id}{suffix}"
    if not path.exists():
        path.write_bytes(data)
    return {
        "receipt_id": receipt_id,
        "receipt_ref": str(path),
        "receipt_sha256": sha256,
        "receipt_mime_type": mime_type,
        "receipt_byte_size": len(data),
        "receipt_uploaded_at": utc_now(),
        "image_phash": f"{int(dhash(data)):016x}",
    }


def _claim_key(fields: dict[str, Any]) -> tuple[str, str, float, str] | None:
    try:
        amount = round(float(fields.get("amount")), 2)
    except (TypeError, ValueError):
        return None
    vendor = normalise_vendor(fields.get("vendor"))
    date = str(fields.get("date") or "")
    currency = str(fields.get("currency") or "GBP").upper()
    return (vendor, date, amount, currency) if vendor and date else None


def _archived_receipts() -> dict[tuple[str, str, float, str], list[Path]]:
    """Index the synthetic receipt archive by the fields that define an exact claim.

    Multiple matches are retained so callers can refuse ambiguous recovery rather than
    attaching the wrong image.
    """
    index: dict[tuple[str, str, float, str], list[Path]] = {}
    if not RECEIPT_ARCHIVE_DIR.is_dir():
        return index
    for manifest in RECEIPT_ARCHIVE_DIR.rglob("manifest.jsonl"):
        for line in manifest.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                key = _claim_key(row.get("gold") or {})
                image = manifest.parent / str(row.get("image") or "")
            except (json.JSONDecodeError, OSError, TypeError):
                continue
            if key is not None and image.is_file():
                index.setdefault(key, []).append(image)
    return index


def backfill_legacy_receipts(store: Any) -> dict[str, int]:
    """Recover pre-evidence claims from the local synthetic receipt archive.

    Recovery is deliberately conservative: claim fields must identify one archive image,
    and an existing perceptual hash must agree within a small tolerance. The tolerance is
    eight bits because the legacy React path serialised the 64-bit hash as a JavaScript
    number and could lose low-bit precision. No model output is invented; the original
    submitted values are preserved and marked for review.
    """
    recovered = ambiguous = unmatched = 0
    records = [record for record in store.list("submissions", record_type="expense_claim")
               if not record.data.get("receipt_ref")
               and record.data.get("receipt_recovery_version") != LEGACY_RECOVERY_VERSION]
    if not records:
        return {"recovered": 0, "ambiguous": 0, "unmatched": 0}
    archive = _archived_receipts()
    for record in records:
        candidates = archive.get(_claim_key(record.data), [])
        legacy_hash = record.data.get("image_phash")
        if isinstance(legacy_hash, int) and not isinstance(legacy_hash, bool):
            candidates = [path for path in candidates
                          if hamming(legacy_hash, dhash(path.read_bytes()))
                          <= LEGACY_PHASH_TOLERANCE]
        if len(candidates) != 1:
            ambiguous += int(len(candidates) > 1)
            unmatched += int(len(candidates) == 0)
            store.update(record.id, data={
                **record.data,
                "receipt_recovery_version": LEGACY_RECOVERY_VERSION,
                "receipt_recovery_status": "ambiguous" if candidates else "unavailable",
            })
            continue

        source = candidates[0]
        mime = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".pdf": "application/pdf",
        }.get(source.suffix.lower(), "application/octet-stream")
        evidence = verify_receipt_evidence(
            persist_receipt(source.read_bytes(), mime_type=mime, filename=source.name)
        )
        submitted = {key: record.data.get(key) for key in (
            "employee_name", "department", "vendor", "date", "amount", "currency",
            "payment_method", "category", "business_purpose", "line_items", "tax",
        ) if key in record.data}
        states = {
            field: {"state": "review_required",
                    "reasons": ["legacy_model_snapshot_unavailable"]}
            for field in CRITICAL_FIELDS
        }
        store.update(record.id, data={
            **record.data,
            **evidence,
            "submitted_snapshot": submitted,
            "verification_states": states,
            "evidence_origin": "legacy_synthetic_archive_backfill",
            "receipt_recovery_version": LEGACY_RECOVERY_VERSION,
            "receipt_recovery_status": "recovered",
        })
        recovered += 1
    return {"recovered": recovered, "ambiguous": ambiguous, "unmatched": unmatched}


def verify_receipt_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Rebuild integrity metadata from the persisted bytes; never trust the browser echo."""
    path = Path(str(evidence.get("receipt_ref") or "")).resolve()
    root = EVIDENCE_DIR.resolve()
    if root not in path.parents or not path.is_file():
        raise ValueError("invalid receipt evidence reference")
    data = path.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    receipt_id = f"rcpt-{sha256[:16]}"
    if evidence.get("receipt_id") != receipt_id or evidence.get("receipt_sha256") != sha256:
        raise ValueError("receipt evidence integrity check failed")
    return {
        "receipt_id": receipt_id,
        "receipt_ref": str(path),
        "receipt_sha256": sha256,
        "receipt_mime_type": str(evidence.get("receipt_mime_type") or "application/octet-stream"),
        "receipt_byte_size": len(data),
        "receipt_uploaded_at": str(evidence.get("receipt_uploaded_at") or utc_now()),
        "image_phash": f"{int(dhash(data)):016x}",
    }


def immutable_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    """JSON round-trip prevents later nested mutations from changing a snapshot."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def revision(*, version: int, actor: str, fields: dict[str, Any],
             changed_fields: list[str] | None, reason: str,
             timestamp: str | None = None) -> dict[str, Any]:
    return {
        "version": version,
        "actor": actor,
        "timestamp": timestamp or utc_now(),
        "reason": reason,
        "changed_fields": list(changed_fields or []),
        "fields": immutable_snapshot(fields),
    }


def verification_states(extraction: dict[str, Any], submitted: dict[str, Any], *,
                        second_read: dict[str, Any] | None = None,
                        missing: list[str] | None = None,
                        policy_flags: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Derive user-facing states from evidence, never from model confidence."""
    missing_set = set(missing or [])
    flagged = {str(flag.get("field") or "") for flag in policy_flags or []}
    states: dict[str, Any] = {}
    for field in CRITICAL_FIELDS:
        reasons: list[str] = []
        first = extraction.get(field)
        current = submitted.get(field)
        independent = (second_read or {}).get(field)
        if field in missing_set or current in (None, ""):
            state = "unresolved"
            reasons.append("required_value_missing")
        else:
            if first != current:
                reasons.append("employee_changed_model_value")
            if second_read is not None and independent not in (None, "") and independent != current:
                reasons.append("independent_read_disagrees")
            if field in flagged:
                reasons.append("deterministic_check_flagged")
            state = "review_required" if reasons else "verified"
        states[field] = {"state": state, "reasons": reasons}
    return states


def evidence_payload(data: dict[str, Any]) -> dict[str, Any]:
    return {key: data.get(key) for key in (
        "receipt_id", "receipt_ref", "receipt_sha256", "receipt_mime_type",
        "receipt_byte_size", "receipt_uploaded_at", "image_phash",
        "extraction_snapshot", "submitted_snapshot", "verification_states",
        "revisions", "audit_events",
    )}
