"""Observable, model-independent category gold for the synthetic WF3 receipts.

Receipt category is inferred business context rather than printed text.  The original
generator independently sampled vendor and item category, so a single latent label can
contradict evidence visible on the receipt.  This rubric declares every category supported
by the visible vendor/item evidence without consulting a model output.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


VENDOR_CATEGORIES: dict[str, frozenset[str]] = {
    "café aurora": frozenset({"meals"}),
    "cafe aurora": frozenset({"meals"}),
    "the green kitchen": frozenset({"meals"}),
    "citycab": frozenset({"travel"}),
    "desksupplies co": frozenset({"supplies"}),
    "techmart ltd": frozenset({"software", "supplies"}),
    # A deliberately generic retailer name: either general goods or office supplies is
    # observable, while a more specific item description may narrow it further.
    "brightmart": frozenset({"other", "supplies"}),
}

ITEM_CATEGORY_TERMS: dict[str, tuple[str, ...]] = {
    "meals": ("sandwich", "coffee", "set lunch", "set dinner", "soup", "salad"),
    "travel": ("taxi", "fare", "train", "bus", "parking", "airline", "flight", "fuel"),
    "supplies": ("notebook", "pens", "printer paper", "stapler", "stationery", "electronics"),
    "software": ("license", "cloud storage", "api credits", "saas"),
    "accommodation": ("room", "hotel", "b&b", "city tax"),
    "other": ("misc", "service", "sundry"),
}


@dataclass(frozen=True)
class CategoryGold:
    primary: str
    accepted: tuple[str, ...]
    vendor_evidence: tuple[str, ...]
    item_evidence: tuple[str, ...]


def observable_category_gold(receipt: dict[str, Any]) -> CategoryGold:
    """Return a deterministic semantic gold set based only on visible receipt evidence.

    Purchased line items are stronger evidence than a merchant name.  Vendor evidence is
    used only when the items are absent or generic (``Misc``, ``Service``, ``Sundry``).
    Breakfast is intrinsically ambiguous between a meal and hotel accommodation.  Travel
    and accommodation share a broad travel family, but no other categories are globally
    collapsed.
    """
    vendor = str(receipt.get("vendor") or "").strip().casefold()
    vendor_evidence = set(VENDOR_CATEGORIES.get(vendor, ()))
    item_evidence: set[str] = set()
    for item in receipt.get("line_items") or []:
        description = str(item.get("desc") or "").strip().casefold()
        if "breakfast" in description:
            item_evidence.update({"meals", "accommodation"})
        for category, terms in ITEM_CATEGORY_TERMS.items():
            if any(term in description for term in terms):
                item_evidence.add(category)

    specific_items = item_evidence - {"other"}
    accepted = specific_items or (item_evidence | vendor_evidence)
    if not accepted:
        accepted = {str(receipt.get("category") or "other")}
    if accepted & {"travel", "accommodation"}:
        accepted.update({"travel", "accommodation"})

    original = str(receipt.get("category") or "other")
    primary = original if original in accepted else sorted(accepted)[0]
    return CategoryGold(
        primary=primary,
        accepted=tuple(sorted(accepted)),
        vendor_evidence=tuple(sorted(vendor_evidence)),
        item_evidence=tuple(sorted(item_evidence)),
    )
