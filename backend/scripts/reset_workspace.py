"""Reset the live workspace back to the seeded demo world.

    python -m backend.scripts.reset_workspace [--yes]

The workspace (`config.RECORD_STORE_PATH`) is persistent, so everything you booked,
submitted and triaged is still there next time the server starts. This wipes it and re-seeds
the fixtures — the pristine state to demo or screenshot from.

Destructive, so it prints what it is about to delete and asks first (`--yes` skips the
prompt). Stop the server before running it: the seeded store is created at import time, so a
running process holds the old contents in its connection.
"""

import sys
from datetime import date

from ..backends.records import STORES, RecordStore
from ..config import RECORD_STORE_PATH
from ..fixtures import org
from ..fixtures.live_demo import seed_live_demo_activity


def main() -> None:
    store = RecordStore(RECORD_STORE_PATH)
    counts = {s: len(store.list(s)) for s in STORES}
    total = sum(counts.values())

    print(f"workspace: {RECORD_STORE_PATH}")
    for s, n in counts.items():
        print(f"  {s:<12} {n:>4} records")

    if total == 0:
        print("already empty — seeding the fixtures.")
    elif "--yes" not in sys.argv:
        if (
            input(f"delete all {total} records and re-seed? [y/N] ").strip().lower()
            != "y"
        ):
            print("aborted — nothing changed.")
            return

    store.reset()
    today = date.today()
    org.seed_from_org(store, today=today)
    seed_live_demo_activity(store, today=today)
    print(f"reset · re-seeded {sum(len(store.list(s)) for s in STORES)} records.")


if __name__ == "__main__":  # pragma: no cover
    main()
