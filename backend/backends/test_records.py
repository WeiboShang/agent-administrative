"""Tests for the RecordStore (offline, in-memory SQLite — no LLM)."""
import pytest

from backend.backends.records import RecordStore
from backend.fixtures import org


def _store() -> RecordStore:
    return RecordStore(":memory:")


def test_create_and_get():
    s = _store()
    rec = s.create("submissions", "expense_claim", {"amount": 42.0}, status="draft")
    assert rec.id == "exp-000001"          # type-based prefix
    assert rec.store == "submissions"
    assert rec.status == "draft"
    got = s.get(rec.id)
    assert got is not None and got.data["amount"] == 42.0


def test_id_prefix_by_type():
    s = _store()
    assert s.create("events", "event", {}, status="booked").id.startswith("evt-")
    assert s.create("submissions", "decision_note", {}, status="draft").id.startswith("note-")
    assert s.create("threads", "thread", {}, status="unread").id.startswith("thr-")


def test_list_filters():
    s = _store()
    s.create("submissions", "expense_claim", {}, status="approved")
    s.create("submissions", "expense_claim", {}, status="rejected")
    s.create("submissions", "decision_note", {}, status="approved")
    assert len(s.list("submissions")) == 3
    assert len(s.list("submissions", record_type="expense_claim")) == 2
    assert len(s.list("submissions", status="approved")) == 2
    assert len(s.list("submissions", record_type="expense_claim", status="approved")) == 1


def test_update_changes_data_and_status():
    s = _store()
    rec = s.create("submissions", "expense_claim", {"amount": 42.0}, status="draft")
    upd = s.update(rec.id, data={"amount": 50.0}, status="approved")
    assert upd.status == "approved"
    assert s.get(rec.id).data["amount"] == 50.0


def test_unknown_store_rejected():
    with pytest.raises(ValueError):
        _store().create("nope", "thing", {}, status="x")


def test_reset_clears_and_restarts_ids():
    s = _store()
    s.create("submissions", "expense_claim", {}, status="draft")
    s.reset()
    assert s.list("submissions") == []
    assert s.create("submissions", "expense_claim", {}, status="draft").id == "exp-000001"


def test_seed_from_org_populates_three_stores():
    s = _store()
    org.seed_from_org(s)
    assert len(s.list("events")) == len(org.BUSY_SLOTS)
    assert len(s.list("submissions", record_type="expense_claim")) == len(org.SEED_EXPENSES)
    assert len(s.list("threads")) == len(org.SEED_THREADS)
    # seeded expenses are approved so they consume budget/quota
    assert all(r.status == "approved" for r in s.list("submissions"))


# ── persistence (the live workspace is a file, not reset-on-restart) ──

def test_file_backed_store_survives_a_restart(tmp_path):
    """A record written before "shutdown" is still there in a new connection."""
    path = str(tmp_path / "workspace.db")
    first = RecordStore(path)
    rec = first.create("events", "event", {"title": "Q3 budget review"}, status="booked")

    reopened = RecordStore(path)                      # simulates the server restarting
    got = reopened.get(rec.id)
    assert got is not None and got.data["title"] == "Q3 budget review"
    assert len(reopened.list("events")) == 1


def test_is_empty_guards_reseeding(tmp_path):
    """Seeding is driven by is_empty(), so a restart must not stack a second demo world."""
    path = str(tmp_path / "workspace.db")
    s = RecordStore(path)
    assert s.is_empty()

    org.seed_from_org(s)
    seeded = {st: len(s.list(st)) for st in ("threads", "events", "submissions")}
    assert sum(seeded.values()) > 0

    reopened = RecordStore(path)
    assert not reopened.is_empty()                    # → _store.py skips seeding
    assert {st: len(reopened.list(st)) for st in seeded} == seeded


def test_ids_keep_counting_across_restarts(tmp_path):
    """AUTOINCREMENT must not restart and collide with an id already on disk."""
    path = str(tmp_path / "workspace.db")
    first = RecordStore(path)
    first.create("submissions", "expense_claim", {}, status="draft")
    second = RecordStore(path).create("submissions", "expense_claim", {}, status="draft")
    assert second.id == "exp-000002"


def test_reset_empties_a_file_store(tmp_path):
    """The reset script's contract: wipe, then re-seed from scratch."""
    path = str(tmp_path / "workspace.db")
    s = RecordStore(path)
    org.seed_from_org(s)
    s.reset()
    assert s.is_empty()
    org.seed_from_org(s)
    assert not s.is_empty()
