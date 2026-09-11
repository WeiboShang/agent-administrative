"""Tests for the on-disk eval-run log. Offline."""
from backend.evals import results_store


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(results_store, "RESULTS_DIR", str(tmp_path))
    e1 = results_store.save_result("triage", {"recall": 1.0}, model="m1", params={"n": 3})
    results_store.save_result("triage", {"recall": 0.9}, model="m2", params={"n": 5})
    assert e1["at"] and e1["model"] == "m1"
    assert len(e1["sha256"]) == 64

    runs = results_store.load_all("triage")
    assert [r["model"] for r in runs] == ["m1", "m2"]     # append-only, in order

    latest = results_store.load_latest()
    assert latest["triage"]["result"] == {"recall": 0.9}  # newest entry wins


def test_load_missing_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(results_store, "RESULTS_DIR", str(tmp_path / "nope"))
    assert results_store.load_all("anything") == []
    assert results_store.load_latest() == {}

def test_formal_v3_loader_excludes_legacy_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(results_store, "RESULTS_DIR", str(tmp_path))
    results_store.save_result("outcomes_v3", {"old": True})
    results_store.save_result("outcomes_v3", {"formal": True}, result_status="v3_formal")
    assert [row["result"] for row in results_store.formal_v3_entries()] == [{"formal": True}]


def test_formal_v3_loader_prefers_v33_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(results_store, "RESULTS_DIR", str(tmp_path))
    results_store.save_result("outcomes_v3", {"old": True}, result_status="v3_formal")
    results_store.save_result("outcomes_v3", {"current": True}, result_status="v3_3_formal")
    assert [row["result"] for row in results_store.formal_v3_entries()] == [
        {"current": True}
    ]


def test_formal_v3_loader_excludes_explicitly_superseded_v33_row(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(results_store, "RESULTS_DIR", str(tmp_path))
    first = results_store.save_result(
        "outcomes_v3", {"metadata_bug": True}, result_status="v3_3_formal"
    )
    results_store.save_result(
        "outcomes_v3",
        {"corrected": True},
        params={"supersedes_sha256": first["sha256"]},
        result_status="v3_3_formal",
    )
    assert [row["result"] for row in results_store.formal_v3_entries()] == [
        {"corrected": True}
    ]


def test_formal_v341_loader_never_falls_back_to_v34(tmp_path, monkeypatch):
    monkeypatch.setattr(results_store, "RESULTS_DIR", str(tmp_path))
    results_store.save_result(
        "outcomes_v34", {"historical": True}, result_status="v3_4_formal"
    )
    assert results_store.formal_v341_entries() == []
    results_store.save_result(
        "outcomes_v341", {"current": True}, result_status="v3_4_1_formal"
    )
    assert [row["result"] for row in results_store.formal_v341_entries()] == [
        {"current": True}
    ]


def test_formal_v342_loader_never_falls_back_to_v341(tmp_path, monkeypatch):
    monkeypatch.setattr(results_store, "RESULTS_DIR", str(tmp_path))
    results_store.save_result(
        "outcomes_v341", {"historical": True}, result_status="v3_4_1_formal"
    )
    assert results_store.formal_v342_entries() == []
    results_store.save_result(
        "outcomes_v342", {"current": True}, result_status="v3_4_2_formal"
    )
    assert [row["result"] for row in results_store.formal_v342_entries()] == [
        {"current": True}
    ]


def test_formal_v343_loader_never_falls_back_to_v342(tmp_path, monkeypatch):
    monkeypatch.setattr(results_store, "RESULTS_DIR", str(tmp_path))
    results_store.save_result(
        "outcomes_v342", {"historical": True}, result_status="v3_4_2_formal"
    )
    assert results_store.formal_v343_entries() == []
    results_store.save_result(
        "outcomes_v343", {"current": True}, result_status="v3_4_3_formal"
    )
    assert [row["result"] for row in results_store.formal_v343_entries()] == [
        {"current": True}
    ]
