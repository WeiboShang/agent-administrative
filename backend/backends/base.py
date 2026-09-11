"""Backend interfaces (CLAUDE.md §4.2): swap-boundary between workflows and the world.

In the v2 re-scope the workflows' side effects all go through the stateful
:class:`~backend.backends.records.RecordStore` (threads / events / submissions), so the
only remaining ABC here is the directory. The speculative Calendar/Mail/Form/Ticket ABCs
from the pre-re-scope four-workflow design were removed with the LangGraph prototype
(git history / legacy backup has them); a real directory (LDAP, Graph API) would slot in
behind :class:`DirectoryBackend` via config with zero workflow-code changes.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class Person:
    user_id: str
    name: str
    email: str
    role: str
    department: str = ""


class DirectoryBackend(ABC):
    """Resolves people referenced in communications (participants, approvers)."""

    @abstractmethod
    def lookup(self, name_or_id: str) -> Optional[Person]: ...

    @abstractmethod
    def list_all(self) -> list[Person]: ...
