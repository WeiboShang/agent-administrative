"""The single RecordStore shared by the inbox / schedule / expense / evaluation routers.

Lives here so every page reads and writes the same workspace (a decision made in Expenses
shows up in the audit log; a meeting booked in Calendar occupies the slot everywhere).

**Persistent by default** (`config.RECORD_STORE_PATH`): the workspace is a real file, so
booked meetings, submitted claims and triaged threads survive a server restart. The fixtures
are seeded only when the store is EMPTY — re-seeding on every start would stack a second copy
of the demo world on top of the user's own work.

Evaluation is unaffected and stays reproducible (CLAUDE.md §3.4): every eval path constructs
its own fresh `RecordStore(":memory:")` and seeds that, so no eval reads or mutates this
store. Set `RECORD_STORE_PATH=:memory:` to get the old reset-on-restart behaviour.
"""
import os
from datetime import date

from ..backends.records import RecordStore
from ..config import RECORD_STORE_PATH
from ..money import backfill_frozen_conversions
from ..fixtures import org
from ..fixtures.live_demo import seed_live_demo_activity
from ..workflows.expense_evidence import backfill_legacy_receipts
from ..workflows.thread_intake import migrate_thread_records

if RECORD_STORE_PATH != ":memory:":
    os.makedirs(os.path.dirname(RECORD_STORE_PATH) or ".", exist_ok=True)

store = RecordStore(RECORD_STORE_PATH)

if store.is_empty():
    # today-relative so the flagship 'next Tuesday' clash is always in the future
    today = date.today()
    org.seed_from_org(store, today=today)
    seed_live_demo_activity(store, today=today)

# Idempotent schema/evidence migrations keep an existing workspace on the same contract as
# newly-created records. They never fabricate business values or execute an action.
migrate_thread_records(store)
backfill_frozen_conversions(store)
backfill_legacy_receipts(store)
