"""Idempotently enrich the persistent workspace with live-only synthetic activity."""
from datetime import date

from ..backends.records import RecordStore
from ..config import RECORD_STORE_PATH
from ..fixtures.live_demo import seed_live_demo_activity


def main() -> None:
    store = RecordStore(RECORD_STORE_PATH)
    created = seed_live_demo_activity(store, today=date.today())
    print(
        f"workspace: {RECORD_STORE_PATH}\n"
        f"added {created['events']} booked meetings and "
        f"{created['submissions']} approved expense records"
    )


if __name__ == "__main__":  # pragma: no cover
    main()
