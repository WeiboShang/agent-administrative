"""Tests for the synthetic receipt generator (offline — Pillow only, no key/model)."""
from PIL import Image

from backend.evals.receipt_data import TIERS, make_receipt_case


def test_deterministic_in_seed():
    _, g1, m1 = make_receipt_case("clean", 7)
    _, g2, m2 = make_receipt_case("clean", 7)
    assert g1 == g2 and m1 == m2


def test_all_tiers_render_an_image():
    for tier in TIERS:
        img, gold, meta = make_receipt_case(tier, 1)
        assert isinstance(img, Image.Image)
        assert img.size[0] > 0 and img.size[1] > 0
        assert meta["tier"] == tier


def test_clean_amount_equals_line_item_sum():
    _, gold, _ = make_receipt_case("clean", 3)
    assert gold["amount"] == round(sum(i["amount"] for i in gold["line_items"]), 2)
    assert gold["vendor"] and gold["date"] and gold["currency"] == "GBP"


def test_non_receipt_has_no_fields_and_is_flagged():
    _, gold, meta = make_receipt_case("non_receipt", 2)
    assert meta["is_receipt"] is False
    assert gold["vendor"] is None and gold["amount"] is None
    assert gold["line_items"] == []


def test_over_limit_case():
    _, gold, meta = make_receipt_case("over_limit", 4)
    assert gold["category"] == "meals" and gold["amount"] > 50
    assert "over_limit" in meta["expected_flags"]


def test_duplicate_case_matches_seed_target():
    _, gold, meta = make_receipt_case("duplicate", 5)
    assert gold["vendor"] == "CityCab" and gold["date"] == "2026-06-22" and gold["amount"] == 24.0
    assert "duplicate" in meta["expected_flags"]


def test_inconsistent_tier_total_differs_from_line_sum():
    _, gold, meta = make_receipt_case("inconsistent", 0)
    assert meta["expected_flags"] == ["arithmetic_mismatch"]
    line_sum = round(sum(i["amount"] for i in gold["line_items"]), 2)
    assert abs(line_sum - gold["amount"]) > 0.02      # a real, above-tolerance mismatch
    assert meta["true_line_item_sum"] == line_sum
    assert gold["currency"] == "GBP" and gold["category"] == "travel"


def test_write_dataset(tmp_path):
    from backend.evals.receipt_data import write_dataset
    manifest = write_dataset(str(tmp_path), n_per_tier=1)
    assert len(manifest) == len(TIERS)
    assert (tmp_path / "manifest.jsonl").exists()
    assert (tmp_path / "clean_0.png").exists()


# ── foreign_currency tier: the "only over-limit once converted" case ──
def test_foreign_currency_receipts_are_under_the_cap_in_their_own_currency():
    """The whole point of the tier: reading the number alone would pass it. Only a
    currency-aware policy engine catches these."""
    from backend import money
    from backend.evals.receipt_data import FINAL_COUNTS, make_receipt_case
    from backend.workflows import policy

    for seed in range(FINAL_COUNTS["foreign_currency"]):
        _, gold, meta = make_receipt_case("foreign_currency", seed=seed)
        gbp = money.to_gbp(gold["amount"], gold["currency"])
        assert gold["currency"] != "GBP"
        assert gbp > policy.PER_DIEM["meals"], "gold says over_limit but converts under it"
        assert meta["expected_flags"] == ["over_limit"]


def test_foreign_currency_gold_keeps_the_original_currency():
    from backend.evals.receipt_data import make_receipt_case
    _, gold, _ = make_receipt_case("foreign_currency", seed=1)
    assert gold["currency"] in {"EUR", "USD", "JPY"}
    assert gold["amount"] == gold["line_items"][0]["amount"]


def test_currencies_without_a_minor_unit_render_whole():
    """A real JPY receipt does not print "12000.00"; the rendered image must not either,
    or the currency-reading test is unfairly easy/odd."""
    from backend.evals.receipt_data import _NO_MINOR_UNIT, make_receipt_case
    seeds = [s for s in range(24)
             if make_receipt_case("foreign_currency", seed=s)[1]["currency"] in _NO_MINOR_UNIT]
    assert seeds, "no JPY sample in range — widen the search"
    _, gold, _ = make_receipt_case("foreign_currency", seed=seeds[0])
    assert float(gold["amount"]).is_integer()
