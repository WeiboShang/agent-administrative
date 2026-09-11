"""Structured draft schema for the WF3 expense prefill core.

The scheduling/triage cores of the v2 re-scope work on plain event/action dicts validated
in CODE (see workflows/scheduling.py, workflows/triage.py); the earlier per-workflow draft
classes that mirrored the pre-re-scope four-workflow design were removed with the
LangGraph prototype (git history / legacy backup has them).
"""
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# Values match workflows/forms/registry.py FORM_SCHEMAS so doc and code agree.
FormType = Literal["expense_claim"]


class FormPrefillDraft(BaseModel):
    form_type: Optional[FormType] = None   # None when the request couldn't be classified
    fields: dict[str, Any] = Field(default_factory=dict)
    missing_required: list[str] = Field(default_factory=list)
    completeness: float = 0.0          # 0..1, computed in CODE
    classification_confidence: float = 0.0
