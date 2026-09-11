"""The single LLM-extraction path, shared by the routers and the eval harness.

Runs a workflow's extraction prompt over an input message and returns parsed JSON (or an
``{'error': ...}`` dict on parse failure). The generator model is a parameter (RQ2:
model is an *evaluation variable*) — pass ``model=`` to run the same prompt/pipeline on a
different Groq-hosted model (e.g. ``openai/gpt-oss-120b`` as the cross-family comparison
condition); default is ``config.LLM_MODEL``. Clients are built lazily and cached, so
importing this module needs ``GROQ_API_KEY`` only when a call is actually made.
"""
import json
import re
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from ..config import GROQ_API_KEY, LLM_MODEL
from .prompts import PROMPT_MAP, SYSTEM_PROMPT, feedback_block

_clients: dict[str, ChatGroq] = {}


def _get_llm(model: Optional[str] = None) -> ChatGroq:
    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is required for live LLM extraction; "
            "offline tests and frozen evaluation replay do not require it."
        )
    name = model or LLM_MODEL
    if name not in _clients:
        kwargs: dict = {}
        if name.startswith("openai/gpt-oss"):
            # reasoning models burn thousands of hidden tokens per call; extraction
            # doesn't need deep reasoning and the daily quota does need saving
            kwargs["reasoning_effort"] = "low"
        _clients[name] = ChatGroq(model=name, api_key=GROQ_API_KEY, temperature=0,
                                  **kwargs)
    return _clients[name]


def _parse_json(text: str) -> dict:
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group())
    raise ValueError(f"No JSON object found in LLM response: {text[:200]}")


def llm_extract(workflow_type: str, input_text: str, model: Optional[str] = None, *,
                source: Optional[str] = None,
                negatives: Optional[list[str]] = None) -> dict:
    """Extract structured fields from ``input_text`` using the workflow's prompt.

    ``source`` is the channel the message arrived on ("email" / "chat") — WF1 triage reads
    differently depending on it. Prompts that don't reference ``{source}`` ignore it
    (``str.format`` drops unused kwargs), so this is safe for every workflow.

    ``negatives`` appends previously-dismissed wordings as few-shot negatives (WF1 feedback
    loop). When it is None/empty the prompt is byte-identical to the baseline, so an A/B over
    this argument isolates the feedback effect and nothing else.
    """
    prompt = PROMPT_MAP[workflow_type].format(input=input_text, source=source or "chat")
    if negatives:
        prompt += feedback_block(negatives)
    response = _get_llm(model).invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ])
    try:
        return _parse_json(response.content)
    except (ValueError, json.JSONDecodeError):
        return {"error": "Failed to parse response", "raw": response.content[:500]}
