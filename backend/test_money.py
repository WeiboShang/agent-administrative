"""Currency conversion + the two properties that matter (offline — no LLM, no network)."""
import pytest
from backend.testing import ASGITestClient as TestClient

from backend import money
from backend.main import app
from backend.routers._store import store
from backend.workflows import policy
from backend.workflows.expense import decide_expense_evidence, submit_expense_evidence


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def restore_rates():
    """Some tests mutate the FX table; put it back so ordering can't leak."""
    original = dict(money.FX_TO_GBP)
    yield
    money.FX_TO_GBP.clear()
    money.FX_TO_GBP.update(original)


def _submit_claim(fields: dict) -> dict:
    key = f"money:{fields['vendor']}:{fields['date']}:submit"
    return submit_expense_evidence(
        fields, store, submitted_by="alice", extraction_snapshot=fields,
        second_read=fields, idempotency_key=key,
    )


def _approve_claim(record_id: str) -> dict:
    record = store.get(record_id)
    soft = [flag["rule"] for flag in record.data.get("policy_flags", [])
            if flag.get("severity") == "soft"]
    return decide_expense_evidence(
        record_id, store, decision="approve", reviewed_by="chen",
        expected_version=int(record.data.get("version") or 1),
        reason="Verified against receipt" if soft else None,
        acknowledged_flags=soft, idempotency_key=f"money:{record_id}:approve",
    )


# ── conversion basics ──
def test_gbp_is_identity():
    assert money.to_gbp(17.5, "GBP") == 17.5


def test_converts_and_rounds_to_2dp():
    assert money.to_gbp(40.0, "EUR") == round(40.0 * money.FX_TO_GBP["EUR"], 2)


@pytest.mark.parametrize("cur", ["eur", " EUR ", "Eur"])
def test_currency_lookup_is_case_and_space_insensitive(cur):
    assert money.to_gbp(10, cur) == money.to_gbp(10, "EUR")


def test_unknown_currency_returns_none_rather_than_guessing():
    assert money.to_gbp(100, "XYZ") is None
    assert money.rate_for("XYZ") is None


def test_missing_currency_defaults_to_gbp():
    assert money.to_gbp(12.0, None) == 12.0


def test_every_offered_currency_has_a_rate(client):
    """The dropdown must not offer a currency the converter can't handle."""
    offered = client.get("/api/expense/options").json()["currencies"]
    assert offered, "no currencies offered"
    assert [c for c in offered if money.rate_for(c) is None] == []


# ── gbp_of: frozen values only ──
def test_gbp_of_prefers_the_frozen_value_over_recomputing():
    rec = {"amount": 40.0, "currency": "EUR", "amount_gbp": 999.0}
    assert money.gbp_of(rec) == 999.0


def test_gbp_of_does_not_live_revalue_records_missing_a_frozen_value():
    rec = {"amount": 40.0, "currency": "EUR"}
    assert money.gbp_of(rec) is None


def test_conversion_migration_is_idempotent_and_freezes_the_snapshot():
    from backend.backends.records import RecordStore

    local = RecordStore(":memory:")
    record = local.create("submissions", "expense_claim", {
        "amount": 40.0, "currency": "EUR",
    }, status="approved")

    assert money.backfill_frozen_conversions(local) == {"migrated": 1, "unresolved": 0}
    assert money.backfill_frozen_conversions(local) == {"migrated": 0, "unresolved": 0}
    migrated = local.get(record.id).data
    assert migrated["amount_gbp"] == money.to_gbp(40.0, "EUR")
    assert migrated["fx_table_version"] == money.FX_TABLE_VERSION
    assert migrated["fx_schema_version"] == money.FX_SCHEMA_VERSION


def test_gbp_of_returns_none_when_unconvertible():
    assert money.gbp_of({"amount": 40.0, "currency": "XYZ"}) is None
    assert money.gbp_of({"currency": "EUR"}) is None


# ── the property the whole design rests on ──
def test_editing_the_rate_table_does_not_restate_a_submitted_claim(client, restore_rates):
    """IAS 21: a booked transaction is not remeasured when rates move. Concretely — a claim
    already in the ledger, and the budget it consumed, must not change under our feet."""
    fields = {"employee_name": "Alice Tan", "vendor": "Berlin Cafe", "date": "2026-06-26",
              "amount": 40.0, "currency": "EUR", "category": "meals",
              "business_purpose": "team lunch", "department": "Product"}
    sub = _submit_claim(fields)
    _approve_claim(sub["record_id"])

    frozen = store.get(sub["record_id"]).data["amount_gbp"]
    remaining_before = policy.budget_remaining("Product", store)

    money.FX_TO_GBP["EUR"] = 1.50                       # rates move a lot

    assert store.get(sub["record_id"]).data["amount_gbp"] == frozen
    assert policy.budget_remaining("Product", store) == remaining_before


def test_submit_freezes_rate_provenance_onto_the_record(client):
    fields = {"employee_name": "Alice Tan", "vendor": "Tokyo Ramen", "date": "2026-06-25",
        "amount": 17000.0, "currency": "JPY", "category": "travel",
              "business_purpose": "client dinner", "department": "Product"}
    sub = _submit_claim(fields)
    rec = store.get(sub["record_id"]).data

    assert rec["amount"] == 17000.0 and rec["currency"] == "JPY"   # original untouched
    assert rec["amount_gbp"] == money.to_gbp(17000.0, "JPY")
    assert rec["fx_rate"] == money.FX_TO_GBP["JPY"]
    assert rec["fx_rate_date"] == money.FX_RATE_DATE
    assert rec["fx_table_version"] == money.FX_TABLE_VERSION
    assert rec["fx_schema_version"] == money.FX_SCHEMA_VERSION
    assert "idempotency_key" not in rec and rec["idempotency_keys"]


# ── the bug this feature exists to fix ──
def test_spend_charts_sum_in_gbp_not_raw_amounts(client):
    """A ¥17,000 receipt is ~£78. Summing raw would add 17,000 to a department whose whole
    budget is £2,000 — the chart was doing exactly that."""
    def product_spend():
        bars = client.get("/api/eval/audit").json()["charts"]["spend_by_department"]
        return next((b["value"] for b in bars if b["label"] == "Product"), 0.0)

    before = product_spend()
    fields = {"employee_name": "Alice Tan", "vendor": "Tokyo Ramen", "date": "2026-06-24",
              "amount": 17000.0, "currency": "JPY", "category": "travel",
              "business_purpose": "client dinner", "department": "Product"}
    sub = _submit_claim(fields)
    _approve_claim(sub["record_id"])

    added = product_spend() - before
    assert added == pytest.approx(money.to_gbp(17000.0, "JPY"), abs=0.01)
    assert added < 200, "raw amount leaked into a GBP total"


def test_audit_reports_its_currency_and_admits_exclusions(client):
    audit = client.get("/api/eval/audit").json()
    assert audit["spend_currency"] == "GBP"
    assert isinstance(audit["spend_excluded_unconvertible"], int)


def test_audit_rows_carry_currency_so_the_table_can_label_honestly(client):
    rows = client.get("/api/eval/audit").json()["rows"]
    assert rows, "no decision rows to check"
    assert all("currency" in r and "amount_gbp" in r for r in rows)


# ── limits are GBP-denominated: conversion happens before comparison ──
def test_over_limit_fires_on_the_converted_value_not_the_raw_one(client):
    """€78 looks under a £50 cap if you only read the number; converted it is ~£66."""
    fields = {"employee_name": "Alice Tan", "vendor": "Berlin Bistro", "date": "2026-06-27",
              "amount": 78.0, "currency": "EUR", "category": "meals",
              "business_purpose": "client dinner", "department": "Product"}
    sub = _submit_claim(fields)
    assert "over_limit" in [f["rule"] for f in sub["flags"]]
    assert money.to_gbp(78.0, "EUR") > policy.PER_DIEM["meals"]


def test_options_serves_the_rate_table_for_the_live_readout(client):
    o = client.get("/api/expense/options").json()
    assert o["fx_rates"]["GBP"] == 1.0
    assert o["fx_rate_date"] and o["fx_rate_source"]
