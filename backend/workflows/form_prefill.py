"""WF3 (Form / Request Pre-filling) — deterministic core.

The LLM classifies the form type and extracts field values; everything here is
deterministic (see docs/workflow_design.md): load the form's field schema
from the registry, type-check values, flag missing required fields (never inventing them),
and compute completeness. Invalid required values (a non-date in a date field, a non-number
in a numeric field) are nulled and therefore counted as missing.
"""
from datetime import datetime

from ..agent.normalise import clean
from ..schemas.drafts import FormPrefillDraft
from .forms.registry import FORM_SCHEMAS


def _is_iso_date(v: object) -> bool:
    if not isinstance(v, str):
        return False
    try:
        datetime.strptime(v.strip(), "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _is_number(v: object) -> bool:
    """A usable quantity: finite and **strictly positive**.

    The expense amount is not meaningful at zero or below, and a negative
    amount is actively dangerous: an approved -£5000 claim *increased* the department's
    remaining budget, since consumption is derived by summing approved amounts. Rejected
    here (→ nulled → surfaced as missing) rather than trusted.
    """
    if isinstance(v, bool):
        return False
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return f == f and abs(f) != float("inf") and f > 0      # reject NaN / ±inf / <= 0


def _empty(v: object) -> bool:
    """Absent, blank — or a stringy null the model emitted instead of a JSON null."""
    return v is None or (isinstance(v, str) and clean(v) is None)


def validate_and_complete_form(extraction: dict) -> tuple[FormPrefillDraft, list[str], list[str]]:
    """Turn a raw LLM extraction into a validated ``FormPrefillDraft``.

    Returns ``(draft, missing_required, validation_notes)``. An unrecognised/absent
    ``form_type`` yields a draft with ``form_type=None`` and ``missing_required=['form_type']``.
    """
    notes: list[str] = []
    form_type = extraction.get("form_type")
    confidence = float(extraction.get("classification_confidence")
                       or extraction.get("confidence") or 0.0)

    if form_type not in FORM_SCHEMAS:
        notes.append(f"could not classify form type: {form_type!r}")
        draft = FormPrefillDraft(
            form_type=None, fields={}, missing_required=["form_type"],
            completeness=0.0, classification_confidence=confidence,
        )
        return draft, ["form_type"], notes

    schema = FORM_SCHEMAS[form_type]
    fields = dict(extraction.get("fields") or {})

    for f in schema.date_fields:
        v = fields.get(f)
        if v is not None and not _is_iso_date(v):
            notes.append(f"{f} {v!r} is not a valid YYYY-MM-DD date")
            fields[f] = None
    for f in schema.numeric_fields:
        v = fields.get(f)
        if v is not None and not _is_number(v):
            notes.append(f"{f} {v!r} is not a positive number")
            fields[f] = None

    missing = [f for f in schema.required if _empty(fields.get(f))]
    completeness = round(1 - len(missing) / len(schema.required), 3)
    draft = FormPrefillDraft(
        form_type=form_type, fields=fields, missing_required=missing,
        completeness=completeness, classification_confidence=confidence,
    )
    return draft, missing, notes
