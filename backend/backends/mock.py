"""Mock backend implementations (CLAUDE.md §3.2/§4.2) — self-contained, no real services.

Only the directory remains as an ABC-backed mock (see base.py); workflow side effects go
through the stateful RecordStore.
"""
from typing import Optional

from ..fixtures import org
from .base import DirectoryBackend, Person


class MockDirectoryBackend(DirectoryBackend):
    """Resolves people against the shared synthetic org fixture."""

    def lookup(self, name_or_id: str) -> Optional[Person]:
        return org.find_person(name_or_id)

    def list_all(self) -> list[Person]:
        return list(org.PEOPLE)


# Module-level singleton — a real directory would be selected here via config switch
mock_directory = MockDirectoryBackend()
