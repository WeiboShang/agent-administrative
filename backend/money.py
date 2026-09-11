"""Currency conversion — one home for the FX table and the money helpers.

WF3 accepts receipts in any of the supported currencies, and the CORD external eval uses
real Indonesian receipts. Two rules govern how that is handled, and they pull in opposite
directions on purpose:

**The original amount is never overwritten.** What is printed on the receipt is the source
document — the human's job at the WF3 gate is to verify the form *against the image*, so a
form showing £14.88 for a receipt reading €17.50 would make verification impossible. In
accounting terms this is the *transaction currency* amount.

**GBP is derived, and is what gets summed or compared.** Budgets, quotas and per-category
limits are GBP-denominated (`fixtures/org.py`), so a claim is converted before any
comparison, and reporting aggregates in GBP. This is the *functional currency* amount.

Rates are a **frozen snapshot**, not a live feed: a live feed would make evaluation runs
unreproducible and would put a third-party service in the evaluated core (docs/workflow_design.md).
Conversions are also frozen **onto each record at submit time** (`workflows/expense.py`), so
editing this table never restates a claim that has already been submitted — which is the
IAS 21 treatment (a foreign-currency transaction is recorded at the rate on its date and is
not remeasured afterwards) and keeps published eval numbers stable.
"""
from __future__ import annotations

from typing import Any, Optional

# ── the snapshot ──────────────────────────────────────────────────────────────────────
# Derived from the European Central Bank euro foreign-exchange reference rates published
# 2026-07-17 (https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml). The ECB
# quotes per-EUR, so each rate below is EUR->GBP divided by EUR->currency, i.e. **how many
# GBP one unit of that currency is worth**. Retrieved once and hardcoded; nothing fetches
# at runtime.
FX_RATE_SOURCE = "ECB euro reference rates"
FX_RATE_DATE = "2026-07-17"
FX_TABLE_VERSION = "ecb-2026-07-17"
FX_SCHEMA_VERSION = 1

FX_TO_GBP: dict[str, float] = {
    "GBP": 1.0,
    "USD": 0.744189,
    "EUR": 0.85098,
    "CNY": 0.109802,
    "JPY": 0.00458379,
    "HKD": 0.0949193,
    "AUD": 0.51908,
    "CAD": 0.530702,
    "CHF": 0.922172,
    "SGD": 0.576349,
    "IDR": 0.0000414713,
}

DEFAULT_CURRENCY = "GBP"


def rate_for(currency: Optional[str]) -> Optional[float]:
    """GBP per unit of ``currency``; None when the currency is unknown."""
    return FX_TO_GBP.get((currency or DEFAULT_CURRENCY).strip().upper())


def to_gbp(amount: float, currency: Optional[str]) -> Optional[float]:
    """Convert to GBP, rounded to 2dp. None when the currency has no rate.

    None means *"do not guess"* — the caller surfaces it (an `unknown_currency` policy flag
    for the approver, an excluded row in reporting) rather than silently contributing a
    wrong number to a total.
    """
    rate = rate_for(currency)
    return None if rate is None else round(amount * rate, 2)


def convert(amount: float, currency: Optional[str]) -> dict[str, Any]:
    """The fields to freeze onto a record at submit time.

    ``fx_rate_date`` is the snapshot's date. The table is flat — it holds one day's rates
    with no effective-dating — so this records *which* rates were applied rather than
    selecting between them; a dated table would key on the claim's own date instead.
    """
    return {
        "amount_gbp": to_gbp(amount, currency),
        "fx_rate": rate_for(currency),
        "fx_rate_date": FX_RATE_DATE,
        "fx_table_version": FX_TABLE_VERSION,
        "fx_schema_version": FX_SCHEMA_VERSION,
    }


def gbp_of(record: dict[str, Any]) -> Optional[float]:
    """Return only the GBP value frozen on the record at submission/migration time."""
    stored = record.get("amount_gbp")
    if isinstance(stored, (int, float)) and not isinstance(stored, bool):
        return float(stored)
    return None


def backfill_frozen_conversions(store: Any) -> dict[str, int]:
    """Freeze the configured FX snapshot onto pre-contract expense rows exactly once."""
    migrated = unresolved = 0
    for record in store.list("submissions", record_type="expense_claim"):
        data = record.data
        if data.get("fx_schema_version") == FX_SCHEMA_VERSION:
            continue
        stored = data.get("amount_gbp")
        if isinstance(stored, (int, float)) and not isinstance(stored, bool):
            fields: dict[str, Any] = {}
        else:
            amount = data.get("amount")
            if not isinstance(amount, (int, float)) or isinstance(amount, bool):
                fields = {"amount_gbp": None}
            else:
                fields = convert(float(amount), data.get("currency"))
        unresolved += int(fields.get("amount_gbp", stored) is None)
        store.update(record.id, data={
            **data,
            **fields,
            "fx_schema_version": FX_SCHEMA_VERSION,
        })
        migrated += 1
    return {"migrated": migrated, "unresolved": unresolved}
