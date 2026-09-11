"""O4 grounded content generation — decision notes (CLAUDE.md §5 "content generation").

Absorbs the scope PDF's email/document-drafting workflow (O4) as a gate *feature*: after
an approve/reject decision, the system drafts the confirmation/rejection note **from the
decided record + its policy flags** (never from the original conversation), the human
edits it, and the draft is only ever **stored** (`store_draft` semantics — nothing is
sent). Grounding in the record makes the draft directly evaluable: the fact sheet passed
to the LLM is the faithfulness source (evals/content_score.py).
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from ..backends.records import Record, RecordStore

FACT_FIELDS = ("employee_name", "vendor", "date", "amount", "currency", "category",
               "business_purpose", "department")


def fact_sheet(fields: dict[str, Any], decision: str, *,
               reason: Optional[str] = None,
               flags: Optional[list[dict[str, Any]]] = None) -> str:
    """Render the decided record as the ONLY source text the generator may use."""
    lines = [f"decision: {decision}"]
    for k in FACT_FIELDS:
        v = fields.get(k)
        if v not in (None, ""):
            lines.append(f"{k}: {v}")
    if reason:
        lines.append(f"decision_reason: {reason}")
    for f in flags or []:
        lines.append(f"policy_flag: {f.get('rule')} — {f.get('message')}")
    return "\n".join(lines)


def draft_decision_note(fields: dict[str, Any], decision: str, *,
                        reason: Optional[str] = None,
                        flags: Optional[list[dict[str, Any]]] = None,
                        generate: Optional[Callable[[str], dict]] = None,
                        model: Optional[str] = None) -> dict[str, Any]:
    """Generate {subject, body} grounded in the record. ``generate`` is injectable for
    offline tests; the default is the shared single LLM path (agent.extract)."""
    source = fact_sheet(fields, decision, reason=reason, flags=flags)
    if generate is None:
        from ..agent.extract import llm_extract

        def generate(text: str) -> dict:
            return llm_extract("decision_note", text, model=model)

    note = generate(source)
    if not isinstance(note, dict) or "error" in note or not note.get("body"):
        return {"error": "generation failed", "raw": note}
    return {"subject": str(note.get("subject") or f"Expense claim {decision}"),
            "body": str(note["body"]), "source": source}


def store_note(store: RecordStore, *, claim_id: str, note: dict[str, Any],
               decision: str) -> Record:
    """Persist the draft (status='draft' — never sent; CLAUDE.md §2/§3)."""
    return store.create("submissions", "decision_note", {
        "claim_id": claim_id, "decision": decision,
        "subject": note["subject"], "body": note["body"],
        "source": note.get("source", ""), "edited": False,
    }, status="draft")
