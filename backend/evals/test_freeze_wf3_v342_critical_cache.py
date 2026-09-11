from __future__ import annotations

import json

from backend.evals import freeze_wf3_v342_critical_cache as freezer


def test_critical_cache_is_gold_free_checkpointed_and_reusable(
    tmp_path, monkeypatch
) -> None:
    receipt_dir = tmp_path / "receipts"
    receipt_dir.mkdir()
    (receipt_dir / "one.png").write_bytes(b"synthetic-image")
    manifest = receipt_dir / "manifest.jsonl"
    manifest.write_text(
        json.dumps({
            "image": "one.png",
            "gold": {"vendor": "must-not-leak"},
            "meta": {"tier": "clean"},
        }) + "\n",
        encoding="utf-8",
    )
    cache = tmp_path / "critical.jsonl"
    primary_cache = tmp_path / "primary.jsonl"
    primary_cache.write_text(
        json.dumps({
            "image": "one.png",
            "extraction": {"vendor": None, "date": None, "amount": None, "currency": None},
        }) + "\n",
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(freezer, "RECEIPT_DIR", receipt_dir)
    monkeypatch.setattr(freezer, "MANIFEST", manifest)
    monkeypatch.setattr(freezer, "CACHE", cache)
    monkeypatch.setattr(freezer, "PRIMARY_CACHE", primary_cache)
    monkeypatch.setattr(
        freezer,
        "extract_receipt_critical",
        lambda path, **kwargs: calls.append(path.name) or {
            "vendor": "Synthetic Shop", "date": "2026-06-01",
            "amount": 10.0, "currency": "GBP",
        },
    )

    assert freezer.freeze() == {"expected": 1, "reused": 0, "written": 1}
    assert freezer.freeze() == {"expected": 1, "reused": 1, "written": 0}
    assert calls == ["one.png"]
    row = json.loads(cache.read_text(encoding="utf-8"))
    assert "gold" not in row and "meta" not in row
    assert row["critical_read"]["vendor"] == "Synthetic Shop"
    assert row["cache_protocol"] == freezer.CACHE_PROTOCOL
    assert row["inference_config"] == {
        "reasoning_effort": "none", "max_completion_tokens": 256,
    }
    assert row["inference_sha256"]
