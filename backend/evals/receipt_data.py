"""Synthetic receipt-image generator (docs/workflow_design.md).

Reverse generation extended to vision: sample a gold receipt in CODE → render it as an
IMAGE (Pillow) → (at eval time) the vision model extracts → compare to gold. Because we
render the exact fields, every case is **labelled by construction** — no LLM in the loop,
no drift. Offline: no key, no model.

Difficulty tiers exercise robustness (skewed/low_res/faint/cropped), correct-refusal
(non_receipt), and the policy engine (over_limit hard, duplicate hard — the two policy
rules that survived the 9→4 trim). The `duplicate` case matches the seeded
bob/CityCab/2026-06-22/24.0 record in the org fixture.
"""
import json
import os
import random
from datetime import date, timedelta
from typing import Any, Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

GEN_NOW = date(2026, 7, 1)
GENERATOR_VERSION = "v1"

# NB: `inconsistent` is appended LAST on purpose — write_dataset seeds each case by tier
# index, so adding a tier at the end leaves every existing tier's seeds (and the frozen
# dataset) byte-identical.
TIERS = ("clean", "skewed", "low_res", "faint", "cropped",
         "non_receipt", "over_limit", "duplicate", "foreign_currency", "inconsistent")

# `foreign_currency` receipts are priced so that the claim is comfortably *under* the £50
# meals cap read at face value, but *over* it once converted — the case that only a
# currency-aware policy engine catches. Ranges are chosen against the frozen ECB rates in
# backend/money.py; each also exercises whether the vision model reads the currency field
# at all, which no other tier tests.
_NO_MINOR_UNIT = {"JPY", "IDR"}
_FOREIGN: dict[str, tuple[float, float]] = {
    "EUR": (66.0, 82.0),          # ≈ £56–70
    "USD": (75.0, 94.0),          # ≈ £56–70
    "JPY": (12100.0, 15200.0),    # ≈ £55–70, and no minor unit
}

# Final-collection per-tier counts (asymmetric by design): the five robustness tiers
# need n large enough for informative Wilson CIs; `duplicate` is a single fixed claim
# (must match the seeded record — every seed renders the same receipt) so n>3 would
# just re-score one image; `non_receipt` has 3 text variants; `over_limit` varies only
# in date.
FINAL_COUNTS: dict[str, int] = {
    "clean": 18, "skewed": 18, "low_res": 18, "faint": 18, "cropped": 18,
    "non_receipt": 9, "over_limit": 6, "duplicate": 3, "foreign_currency": 12,
    "inconsistent": 12,
}

_VENDORS = ["Café Aurora", "TechMart Ltd", "CityCab", "BrightMart",
            "The Green Kitchen", "DeskSupplies Co"]
_CATEGORIES = ["meals", "travel", "supplies", "software", "accommodation", "other"]
_ITEM_NAMES = {
    "meals": ["Sandwich", "Coffee", "Set lunch", "Soup", "Salad"],
    "travel": ["Taxi fare", "Train ticket", "Bus pass", "Parking"],
    "supplies": ["Notebook", "Pens x10", "Printer paper", "Stapler"],
    "software": ["License 1mo", "Cloud storage", "API credits"],
    "accommodation": ["Room 1 night", "City tax", "Breakfast"],
    "other": ["Misc item", "Service", "Sundry"],
}
_NON_RECEIPT_TEXT = [
    "Thanks for lunch!\nSee you Monday.",
    "Meeting notes:\n- ship v2\n- email Chen\n- book room",
    "Reminder: standup moved\nto 10am tomorrow.",
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                      # very old Pillow
        return ImageFont.load_default()


def _tw(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> float:
    return draw.textlength(text, font=font)


def _center(draw, w, y, text, font) -> None:
    draw.text(((w - _tw(draw, text, font)) / 2, y), text, font=font, fill="black")


def _right(draw, x_right, y, text, font) -> None:
    draw.text((x_right - _tw(draw, text, font), y), text, font=font, fill="black")


def _recent_date(rng: random.Random) -> str:
    return (GEN_NOW - timedelta(days=rng.randint(1, 40))).isoformat()


def _items_for(category: str, rng: random.Random) -> list[dict[str, Any]]:
    names = _ITEM_NAMES.get(category, _ITEM_NAMES["other"])
    n = rng.choice([1, 2, 3])
    return [{"desc": rng.choice(names), "amount": round(rng.uniform(2, 15), 2)}
            for _ in range(n)]


def _render_receipt(gold: dict[str, Any]) -> Image.Image:
    w, pad = 384, 20
    f_h, f_b, f_s, f_t = _font(28), _font(16), _font(13), _font(20)
    items = gold["line_items"]
    height = 160 + len(items) * 26 + 120
    img = Image.new("RGB", (w, height), "white")
    d = ImageDraw.Draw(img)
    y = 24
    _center(d, w, y, gold["vendor"], f_h)
    y += 44
    _center(d, w, y, "123 High Street, Manchester", f_s)
    y += 18
    _center(d, w, y, "VAT 123 4567 89", f_s)
    y += 28
    d.text((pad, y), "Date: " + gold["date"], font=f_b, fill="black")
    y += 28
    d.text((pad, y), "-" * 40, font=f_s, fill="black")
    y += 16
    # currencies without a minor unit are printed whole, as a real receipt would
    dp = 0 if gold["currency"] in _NO_MINOR_UNIT else 2
    for it in items:
        d.text((pad, y), str(it["desc"])[:26], font=f_b, fill="black")
        _right(d, w - pad, y, f"{it['amount']:.{dp}f}", f_b)
        y += 26
    d.text((pad, y), "-" * 40, font=f_s, fill="black")
    y += 14
    d.text((pad, y), "TOTAL", font=f_t, fill="black")
    _right(d, w - pad, y, f"{gold['currency']} {gold['amount']:.{dp}f}", f_t)
    y += 42
    _center(d, w, y, "THANK YOU", f_b)
    return img


def _render_non_receipt(rng: random.Random) -> Image.Image:
    img = Image.new("RGB", (384, 200), "white")
    d = ImageDraw.Draw(img)
    d.multiline_text((24, 50), rng.choice(_NON_RECEIPT_TEXT), font=_font(18),
                     fill="black", spacing=8)
    return img


def _degrade(img: Image.Image, tier: str, rng: random.Random) -> Image.Image:
    w, h = img.size
    if tier == "skewed":
        return img.rotate(rng.uniform(6, 12), expand=True, fillcolor="white")
    if tier == "low_res":
        small = img.resize((max(1, w // 3), max(1, h // 3)))
        return small.resize((w, h)).filter(ImageFilter.GaussianBlur(1.2))
    if tier == "faint":
        return Image.blend(img, Image.new("RGB", img.size, "white"), 0.55)
    if tier == "cropped":
        return img.crop((0, 0, w, int(h * 0.7)))      # cuts off the total
    return img


def make_receipt_case(tier: str, seed: int) -> tuple[Image.Image, dict, dict]:
    """Return ``(image, gold, meta)`` for one case (deterministic in ``seed``)."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier: {tier}")
    rng = random.Random(seed)
    meta = {"tier": tier, "is_receipt": True, "expected_flags": [],
            "now": GEN_NOW.isoformat(), "generator_version": GENERATOR_VERSION}

    if tier == "non_receipt":
        meta["is_receipt"] = False
        gold = {"vendor": None, "date": None, "amount": None, "currency": "GBP",
                "category": None, "line_items": []}
        return _render_non_receipt(rng), gold, meta

    if tier == "duplicate":                # matches the seeded approved claim
        vendor, category, dt = "CityCab", "travel", "2026-06-22"
        items = [{"desc": "City fare", "amount": 24.0}]
        meta["expected_flags"] = ["duplicate"]
    elif tier == "over_limit":             # meals £85 > £50/day
        vendor, category, dt = "Café Aurora", "meals", _recent_date(rng)
        items = [{"desc": "Set dinner x2", "amount": 78.0}, {"desc": "Service", "amount": 7.0}]
        meta["expected_flags"] = ["over_limit"]
    elif tier == "foreign_currency":
        cur = rng.choice(list(_FOREIGN))
        lo, hi = _FOREIGN[cur]
        total = round(rng.uniform(lo, hi), 0 if cur == "JPY" else 2)
        vendor, category, dt = rng.choice(_VENDORS), "meals", _recent_date(rng)
        items = [{"desc": "Set dinner", "amount": total}]
        meta["expected_flags"] = ["over_limit"]   # only once converted to GBP
        gold = {"vendor": vendor, "date": dt, "amount": total, "currency": cur,
                "category": category, "line_items": items}
        return _degrade(_render_receipt(gold), tier, rng), gold, meta
    elif tier == "inconsistent":
        # Reasoning-consistency tier (docs §L.2/§L.3): a clean, readable receipt whose printed
        # TOTAL does NOT equal the sum of its line items — the fault the vision model reads
        # right field-by-field yet cannot reconcile (the paper's finding), and which the
        # deterministic check_arithmetic recovers. `travel` has no per-diem cap, so no
        # over_limit contaminates the expected flag. `amount` = the printed (wrong) total the
        # model would read; gold also records the true line-item sum.
        vendor, category, dt = rng.choice(_VENDORS), "travel", _recent_date(rng)
        items = _items_for("travel", rng)
        while len(items) < 2:                       # ≥2 lines so it reads as a dropped line
            items.append({"desc": rng.choice(_ITEM_NAMES["travel"]),
                          "amount": round(rng.uniform(2, 15), 2)})
        true_sum = round(sum(i["amount"] for i in items), 2)
        printed_total = round(true_sum + round(rng.uniform(5, 20), 2), 2)  # ≠ Σ items
        meta["expected_flags"] = ["arithmetic_mismatch"]
        meta["true_line_item_sum"] = true_sum
        gold = {"vendor": vendor, "date": dt, "amount": printed_total, "currency": "GBP",
                "category": category, "line_items": items}
        return _render_receipt(gold), gold, meta
    else:
        category = rng.choice(_CATEGORIES)
        vendor = rng.choice(_VENDORS)
        dt = _recent_date(rng)
        items = _items_for(category, rng)

    amount = round(sum(i["amount"] for i in items), 2)
    gold = {"vendor": vendor, "date": dt, "amount": amount, "currency": "GBP",
            "category": category, "line_items": items}
    return _degrade(_render_receipt(gold), tier, rng), gold, meta


def write_dataset(out_dir: str, n_per_tier: int = 3, seed: int = 0,
                  counts: Optional[dict[str, int]] = None) -> list[dict]:
    """Render a balanced dataset to ``out_dir`` + a ``manifest.jsonl`` of (image, gold, meta).

    ``counts`` overrides ``n_per_tier`` per tier (see ``FINAL_COUNTS``)."""
    os.makedirs(out_dir, exist_ok=True)
    manifest: list[dict] = []
    for t_idx, tier in enumerate(TIERS):
        for i in range(counts.get(tier, n_per_tier) if counts else n_per_tier):
            img, gold, meta = make_receipt_case(tier, seed=seed * 1000 + t_idx * 100 + i)
            fname = f"{tier}_{i}.png"
            img.save(os.path.join(out_dir, fname))
            manifest.append({"image": fname, "gold": gold, "meta": meta})
    with open(os.path.join(out_dir, "manifest.jsonl"), "w", encoding="utf-8") as f:
        for m in manifest:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    return manifest


if __name__ == "__main__":  # pragma: no cover
    import sys

    out = sys.argv[1] if len(sys.argv) > 1 else "data/receipts/synthetic"
    spec = sys.argv[2] if len(sys.argv) > 2 else "3"
    if spec == "final":
        written = write_dataset(out, counts=FINAL_COUNTS)
        print(f"wrote {len(written)} receipts (FINAL_COUNTS {FINAL_COUNTS}) to {out}")
    else:
        written = write_dataset(out, int(spec))
        print(f"wrote {len(written)} receipts ({spec}/tier × {len(TIERS)} tiers) to {out}")
