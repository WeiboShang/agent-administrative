import json
from pathlib import Path

from backend.agent.image_hash import dhash
from backend.backends.records import RecordStore
from backend.workflows import expense_evidence


def test_backfill_recovers_unique_legacy_receipt(monkeypatch, tmp_path: Path):
    archive = tmp_path / "archive" / "foreign_currency"
    cache = tmp_path / "cache"
    archive.mkdir(parents=True)
    image = Path("data/receipts/foreign_currency/foreign_currency_3.png").read_bytes()
    (archive / "receipt.png").write_bytes(image)
    (archive / "manifest.jsonl").write_text(json.dumps({
        "image": "receipt.png",
        "gold": {"vendor": "TechMart Ltd", "date": "2026-06-07",
                 "amount": 75.48, "currency": "EUR"},
    }) + "\n", encoding="utf-8")
    monkeypatch.setattr(expense_evidence, "RECEIPT_ARCHIVE_DIR", tmp_path / "archive")
    monkeypatch.setattr(expense_evidence, "EVIDENCE_DIR", cache)

    store = RecordStore(":memory:")
    actual_hash = dhash(image)
    legacy_js_hash = actual_hash - 184
    record = store.create("submissions", "expense_claim", {
        "employee_name": "Alice Tan", "vendor": "TechMart Ltd", "date": "2026-06-07",
        "amount": 75.48, "currency": "EUR", "category": "meals",
        "image_phash": legacy_js_hash,
    }, status="submitted")

    assert expense_evidence.backfill_legacy_receipts(store)["recovered"] == 1
    recovered = store.get(record.id).data
    assert Path(recovered["receipt_ref"]).is_file()
    assert recovered["submitted_snapshot"]["vendor"] == "TechMart Ltd"
    assert recovered["verification_states"]["vendor"] == {
        "state": "review_required", "reasons": ["legacy_model_snapshot_unavailable"]
    }
    assert recovered["evidence_origin"] == "legacy_synthetic_archive_backfill"

    assert expense_evidence.backfill_legacy_receipts(store)["recovered"] == 0


def test_backfill_refuses_ambiguous_match(monkeypatch, tmp_path: Path):
    archive = tmp_path / "archive" / "set"
    archive.mkdir(parents=True)
    image = Path("data/receipts/foreign_currency/foreign_currency_3.png").read_bytes()
    rows = []
    for name in ("one.png", "two.png"):
        (archive / name).write_bytes(image)
        rows.append(json.dumps({"image": name, "gold": {
            "vendor": "Same Shop", "date": "2026-06-07", "amount": 10, "currency": "GBP",
        }}))
    (archive / "manifest.jsonl").write_text("\n".join(rows), encoding="utf-8")
    monkeypatch.setattr(expense_evidence, "RECEIPT_ARCHIVE_DIR", tmp_path / "archive")
    monkeypatch.setattr(expense_evidence, "EVIDENCE_DIR", tmp_path / "cache")
    store = RecordStore(":memory:")
    record = store.create("submissions", "expense_claim", {
        "vendor": "Same Shop", "date": "2026-06-07", "amount": 10, "currency": "GBP",
    }, status="submitted")

    result = expense_evidence.backfill_legacy_receipts(store)
    assert result["ambiguous"] == 1
    assert store.get(record.id).data.get("receipt_ref") is None
