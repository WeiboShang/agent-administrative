"""Tests for O4 decision-note generation (offline — injected generator, no LLM/key)."""
from backend.backends.records import RecordStore
from backend.fixtures import org
from backend.workflows.content import draft_decision_note, fact_sheet, store_note

FIELDS = {"employee_name": "Alice Tan", "vendor": "Café Aurora", "date": "2026-06-28",
          "amount": 85.0, "currency": "GBP", "category": "meals",
          "business_purpose": "Client dinner"}
FLAGS = [{"rule": "over_limit", "severity": "soft", "message": "£85 exceeds meals £50/day"}]


def _seeded() -> RecordStore:
    s = RecordStore(":memory:")
    org.seed_from_org(s)
    return s


def test_fact_sheet_contains_facts_flags_and_reason():
    src = fact_sheet(FIELDS, "rejected", reason="No itemised receipt", flags=FLAGS)
    for expect in ("decision: rejected", "Café Aurora", "85", "over_limit",
                   "No itemised receipt"):
        assert expect in src


def test_draft_note_uses_injected_generator_and_returns_source():
    seen = {}

    def fake_generate(text: str) -> dict:
        seen["source"] = text
        return {"subject": "Your expense claim was approved",
                "body": "Your £85.0 claim for Café Aurora (2026-06-28) was approved."}

    note = draft_decision_note(FIELDS, "approved", flags=FLAGS, generate=fake_generate)
    assert note["subject"].startswith("Your expense")
    assert "Café Aurora" in note["body"]
    assert note["source"] == seen["source"]          # judge scores against exactly this
    assert "over_limit" in note["source"]


def test_draft_note_surfaces_generation_failure():
    bad = draft_decision_note(FIELDS, "approved", generate=lambda t: {"error": "boom"})
    assert "error" in bad


def test_store_note_writes_draft_never_sent():
    s = _seeded()
    note = {"subject": "s", "body": "b", "source": "src"}
    rec = store_note(s, claim_id="exp-000001", note=note, decision="approved")
    assert rec.id.startswith("note-")
    assert rec.status == "draft"                      # store_draft semantics
    stored = s.get(rec.id)
    assert stored.data["claim_id"] == "exp-000001"
    assert stored.data["edited"] is False
