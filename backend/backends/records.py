"""In-process record stores backing the three workspace domains (workflow_design.md §2.1).

One SQLite database (in-memory by default) with a single ``records`` table; the three
logical stores — ``threads`` (WF1), ``events`` (WF2), ``submissions`` (WF3) — are
distinguished by the ``store`` column, and each record's domain-specific fields live in a
JSON ``data`` blob (the "unified envelope + JSON fields" pattern).

This is a **real local SQLite tool with synthetic data** (CLAUDE.md §3), not a throwaway
mock: approvals persist here and drive future validations. It is **resettable/seedable**
so evaluation is reproducible (``reset()`` also restarts the id counter). The connection
allows cross-thread use (FastAPI runs handlers in a threadpool) guarded by a lock.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

STORES = ("threads", "events", "submissions")

# Readable id prefixes by record type (falls back to the store name).
_PREFIX = {
    "expense_claim": "exp",
    "schedule_meeting": "evt",
    "event": "evt",
    "thread": "thr",
    "decision_note": "note",
}


@dataclass
class Record:
    id: str
    store: str
    type: str
    status: str
    data: dict[str, Any]
    created_at: str
    updated_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RecordStore:
    """SQLite-backed store for the three domains. Pass ``path`` for a persistent file."""

    def __init__(
        self, path: str = ":memory:", *, now_fn: Callable[[], str] | None = None
    ) -> None:
        self._now = now_fn or _now
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS records (
                    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
                    id         TEXT UNIQUE NOT NULL,
                    store      TEXT NOT NULL,
                    type       TEXT NOT NULL,
                    status     TEXT NOT NULL,
                    data       TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            self._conn.commit()

    def create(self, store: str, record_type: str, data: dict[str, Any],
               status: str) -> Record:
        if store not in STORES:
            raise ValueError(f"unknown store: {store}")
        ts = self._now()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO records (id, store, type, status, data, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                ("__pending__", store, record_type, status, json.dumps(data), ts, ts),
            )
            seq = cur.lastrowid
            rec_id = f"{_PREFIX.get(record_type, store[:3])}-{seq:06d}"
            self._conn.execute("UPDATE records SET id=? WHERE seq=?", (rec_id, seq))
            self._conn.commit()
        return Record(rec_id, store, record_type, status, data, ts, ts)

    def get(self, record_id: str) -> Optional[Record]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM records WHERE id=?", (record_id,)
            ).fetchone()
        return self._to_record(row) if row else None

    def list(self, store: str, *, record_type: Optional[str] = None,
             status: Optional[str] = None) -> list[Record]:
        query = "SELECT * FROM records WHERE store=?"
        params: list[Any] = [store]
        if record_type is not None:
            query += " AND type=?"
            params.append(record_type)
        if status is not None:
            query += " AND status=?"
            params.append(status)
        query += " ORDER BY seq"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._to_record(r) for r in rows]

    def update(self, record_id: str, *, data: Optional[dict[str, Any]] = None,
               status: Optional[str] = None) -> Record:
        rec = self.get(record_id)
        if rec is None:
            raise KeyError(record_id)
        new_data = data if data is not None else rec.data
        new_status = status if status is not None else rec.status
        ts = self._now()
        with self._lock:
            self._conn.execute(
                "UPDATE records SET data=?, status=?, updated_at=? WHERE id=?",
                (json.dumps(new_data), new_status, ts, record_id),
            )
            self._conn.commit()
        return Record(record_id, rec.store, rec.type, new_status, new_data,
                      rec.created_at, ts)

    def update_if_version(self, record_id: str, *, expected_version: int,
                          allowed_statuses: set[str], data: dict[str, Any],
                          status: str) -> Optional[Record]:
        """Atomically compare lifecycle state/version and write the next version."""
        ts = self._now()
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM records WHERE id=?", (record_id,)
            ).fetchone()
            if row is None:
                return None
            current = self._to_record(row)
            if current.status not in allowed_statuses:
                return None
            if int(current.data.get("version") or 1) != expected_version:
                return None
            self._conn.execute(
                "UPDATE records SET data=?, status=?, updated_at=? WHERE id=?",
                (json.dumps(data), status, ts, record_id),
            )
            self._conn.commit()
            return Record(record_id, current.store, current.type, status, data,
                          current.created_at, ts)

    def is_empty(self) -> bool:
        """True when the store holds no records — the signal for "seed the fixtures".

        A file-backed workspace must be seeded on FIRST creation only; re-seeding on every
        start would stack another copy of the fixtures on top of the user's saved work.
        """
        with self._lock:
            return self._conn.execute("SELECT 1 FROM records LIMIT 1").fetchone() is None

    def reset(self) -> None:
        """Clear all records and restart the id counter (for reproducible eval runs)."""
        with self._lock:
            self._conn.execute("DELETE FROM records")
            try:
                self._conn.execute("DELETE FROM sqlite_sequence WHERE name='records'")
            except sqlite3.OperationalError:
                pass  # sqlite_sequence doesn't exist until the first insert
            self._conn.commit()

    @staticmethod
    def _to_record(row: sqlite3.Row) -> Record:
        return Record(row["id"], row["store"], row["type"], row["status"],
                      json.loads(row["data"]), row["created_at"], row["updated_at"])
