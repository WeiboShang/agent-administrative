"""WF3 vision extraction — receipt image → structured fields (Llama 4 Scout via Groq).

The one multimodal step (CLAUDE.md §4.5): the LLM reads what is *printed on* the receipt;
all validation/policy is downstream CODE (workflows/expense.py). The Groq client is built
**lazily**, so the pure `_parse_receipt_json` / `receipt_to_fields` helpers import and test
without a key; only `extract_receipt` (the live call) needs `GROQ_API_KEY` + an image.
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any, Optional

from .normalise import clean, clean_number

VISION_SYSTEM = (
    "You are a receipt-reading assistant. Read ONLY what is printed on the receipt image. "
    "Do not guess business context. Respond with valid JSON only."
)

RECEIPT_PROMPT = """Extract the fields from this receipt image.

Respond with JSON only:
{
  "vendor": "<merchant name or null>",
  "date": "<YYYY-MM-DD or null>",
  "amount": <total as a number or null>,
  "currency": "<e.g. GBP or null>",
  "tax": <number or null>,
  "line_items": [{"desc": "<text>", "amount": <number>}],
  "category_guess": "<one of: meals, travel, accommodation, supplies, software, entertainment, training, other>",
  "payment_method": "<card, cash, contactless, bank_transfer, or null>",
  "field_confidence": {"vendor": 0.0, "date": 0.0, "amount": 0.0, "category_guess": 0.0}
}
Category hints (use the vendor + line items): supermarkets / restaurants / cafés -> meals;
hotels / B&Bs -> accommodation; taxi / rail / airline / fuel -> travel; software or SaaS
vendors -> software; stationery / electronics stores -> supplies.
Payment hints: VISA / MASTERCARD / AMEX / CREDIT / DEBIT / a card-terminal line (e.g. EDC)
-> card; CONTACTLESS -> contactless; a line saying CASH -> cash.
If the image is not a receipt, return {"vendor": null, "amount": null, "not_a_receipt": true}."""

_CATEGORIES = {"meals", "travel", "accommodation", "supplies", "software",
               "entertainment", "training", "other"}
_CATEGORY_ALIASES = {
    "meal": "meals", "food": "meals", "dining": "meals", "restaurant": "meals",
    "transport": "travel", "transportation": "travel", "transit": "travel",
    "lodging": "accommodation", "hotel": "accommodation",
    "office supplies": "supplies", "stationery": "supplies",
    "saas": "software", "subscription": "software",
    "client entertainment": "entertainment", "hospitality": "entertainment",
    "education": "training", "course": "training",
    "misc": "other", "miscellaneous": "other", "uncategorised": "other",
    "uncategorized": "other",
}

# Coarse, category-based business_purpose suggestion (a receipt never states the purpose).
# Deliberately generic so the human still has to refine it — M5 edit-distance reveals
# whether they refine or rubber-stamp (docs/wf3_expense_design.md §D).
_PURPOSE_BY_CATEGORY = {
    "meals": "Business meal", "travel": "Business travel",
    "accommodation": "Business accommodation", "supplies": "Office supplies",
    "software": "Software / tools", "entertainment": "Client entertainment",
    "training": "Training / development",
}

PAYMENT_METHODS = ("card", "cash", "contactless", "bank_transfer", "other")
_PAYMENT_ALIASES = {"visa": "card", "mastercard": "card", "amex": "card",
                    "credit": "card", "debit": "card", "edc": "card"}


def _norm_payment(v: Any) -> Optional[str]:
    """Normalise the model's payment-method guess onto the allowed set (or None)."""
    if not v:
        return None
    s = str(v).strip().lower()
    if s in PAYMENT_METHODS:
        return s
    if "contactless" in s:
        return "contactless"
    if "cash" in s:
        return "cash"
    for alias, canon in _PAYMENT_ALIASES.items():
        if alias in s:
            return canon
    return None

_clients: dict[str, Any] = {}  # lazy per-model Groq clients (model = RQ2 eval variable)


def _parse_receipt_json(text: str) -> dict[str, Any]:
    # reasoning models (qwen3.6) emit a <think>…</think> block before the JSON —
    # strip it first so a brace inside the reasoning can't hijack the match
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {"error": "no JSON in response", "raw": (text or "")[:500]}
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return {"error": "invalid JSON", "raw": text[:500]}


def receipt_to_fields(vision: dict[str, Any], *, employee_name: str,
                      business_purpose: Optional[str] = None) -> dict[str, Any]:
    """Map a vision extraction onto the ``expense_claim`` form fields.

    Only fields the receipt can supply are filled. ``employee_name`` comes from context;
    ``business_purpose`` is left absent unless supplied, so it surfaces as a
    required-missing field the human must fill (docs/wf3_expense_design.md §D).

    Every value is passed through ``normalise.clean`` first: on a degraded receipt the
    model answers "null"/"N/A"/"" rather than a JSON null (seen live on real CORD
    receipts), and an unreadable field must surface as **missing for the human to fill**,
    never be stored as a vendor literally named "null".
    """
    category = clean(vision.get("category_guess"))
    if isinstance(category, str):
        category = _CATEGORY_ALIASES.get(category.strip().casefold(), category.strip().casefold())
    category = category if category in _CATEGORIES else None
    fields: dict[str, Any] = {
        "employee_name": employee_name,
        "vendor": clean(vision.get("vendor")),
        "date": clean(vision.get("date")),
        "amount": clean_number(vision.get("amount")),
        "currency": clean(vision.get("currency")) or "GBP",
        "category": category,
        "payment_method": _norm_payment(vision.get("payment_method")),
    }
    # Pre-fill a coarse, category-based business_purpose the human should refine.
    fields["business_purpose"] = (
        business_purpose or _PURPOSE_BY_CATEGORY.get(category, "Business expense")
    )
    # Carry the model's own line items + tax through as *evidence* (not required fields the
    # human must fill): the arithmetic self-consistency check (policy.check_arithmetic,
    # docs/wf3_expense_design.md §L.1) proves the numbers add up. Kept out of the registry's
    # required set, so they never surface as missing.
    fields["line_items"] = _clean_line_items(vision.get("line_items"))
    fields["tax"] = clean_number(vision.get("tax"))
    return fields


def _clean_line_items(raw: Any) -> list[dict[str, Any]]:
    """Normalise the vision line_items into ``[{desc, amount}]`` with numeric amounts.

    A degraded receipt yields malformed entries (a bare string, a stringy "null" amount);
    those are dropped rather than trusted, the same posture as ``normalise.clean`` elsewhere.
    """
    items: list[dict[str, Any]] = []
    for it in raw or []:
        if not isinstance(it, dict):
            continue
        amt = clean_number(it.get("amount"))
        if amt is None:
            continue
        items.append({"desc": clean(it.get("desc")), "amount": amt})
    return items


def _encode_image(image: str | bytes | Path) -> str:
    if isinstance(image, bytes):
        data = image
    elif isinstance(image, (str, Path)) and Path(image).exists():
        data = Path(image).read_bytes()
    else:
        raise ValueError("image must be raw bytes or an existing file path")
    return base64.b64encode(data).decode()


def _get_client(model: Optional[str] = None):
    from langchain_groq import ChatGroq

    from ..config import GROQ_API_KEY, VISION_MODEL
    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is required for live receipt extraction; "
            "offline tests and frozen evaluation replay do not require it."
        )
    name = model or VISION_MODEL
    if name not in _clients:
        _clients[name] = ChatGroq(model=name, api_key=GROQ_API_KEY, temperature=0)
    return _clients[name]


def extract_receipt(image: str | bytes | Path, *, mime: str = "image/png",
                    model: Optional[str] = None) -> dict[str, Any]:
    """Call the vision model on a receipt image; returns the parsed extraction dict.

    ``model`` overrides ``config.VISION_MODEL`` (RQ2: model is an eval variable —
    lets the eval harness run e.g. qwen3.6 while production stays on the default)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    b64 = _encode_image(image)
    message = HumanMessage(content=[
        {"type": "text", "text": RECEIPT_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ])
    response = _get_client(model).invoke([SystemMessage(content=VISION_SYSTEM), message])
    return _parse_receipt_json(response.content)


CRITICAL_RECEIPT_PROMPT = """Independently read only these critical receipt fields.
Do not use business context and do not infer unreadable values. Respond with JSON only:
{"vendor": "<merchant or null>", "date": "<YYYY-MM-DD or null>",
 "amount": <total number or null>, "currency": "<ISO currency or null>"}
"""

# A four-field transcription does not require chain-of-thought.  Pinning the live-call
# settings makes the independent read cheap enough to freeze in one protocol while also
# making its inference configuration part of the evaluation provenance.
CRITICAL_RECEIPT_INFERENCE = {
    "reasoning_effort": "none",
    "max_completion_tokens": 256,
}


def extract_receipt_critical(
    image: str | bytes | Path, *, mime: str = "image/png",
    model: Optional[str] = None,
    inference_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Separate, narrow second read used only to verify high-impact fields.

    The production/default path deliberately supplies no inference overrides, matching
    the frozen V3.4.2 all-image cache.  Experimental freezers may pass an explicit,
    provenance-recorded configuration without changing the production contract.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    b64 = _encode_image(image)
    message = HumanMessage(content=[
        {"type": "text", "text": CRITICAL_RECEIPT_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ])
    client = _get_client(model)
    if inference_config:
        client = client.bind(**inference_config)
    response = client.invoke([SystemMessage(content=VISION_SYSTEM), message])
    parsed = _parse_receipt_json(response.content)
    return {key: parsed.get(key) for key in ("vendor", "date", "amount", "currency")}
