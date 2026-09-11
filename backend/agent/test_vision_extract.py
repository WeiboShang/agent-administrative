"""Tests for the vision-extraction pure helpers (offline — no key, no image, no client)."""
from backend.agent.vision_extract import _parse_receipt_json, receipt_to_fields


def test_parse_valid_json_with_prose():
    out = _parse_receipt_json('Here is the receipt:\n{"vendor": "Café Aurora", "amount": 85.0}\ndone')
    assert out["vendor"] == "Café Aurora"
    assert out["amount"] == 85.0


def test_parse_no_json_returns_error():
    out = _parse_receipt_json("the model rambled with no json")
    assert out["error"] == "no JSON in response"


def test_parse_invalid_json_returns_error():
    out = _parse_receipt_json("{vendor: not valid}")
    assert out["error"] == "invalid JSON"


def test_map_fills_receipt_fields_and_defaults_currency():
    fields = receipt_to_fields(
        {"vendor": "Café Aurora", "date": "2026-06-28", "amount": 85.0,
         "category_guess": "meals"},
        employee_name="Alice Tan",
    )
    assert fields["employee_name"] == "Alice Tan"
    assert fields["vendor"] == "Café Aurora"
    assert fields["amount"] == 85.0
    assert fields["currency"] == "GBP"          # defaulted
    assert fields["category"] == "meals"
    assert fields["business_purpose"] == "Business meal"   # coarse category suggestion


def test_map_rejects_unknown_category():
    fields = receipt_to_fields({"category_guess": "bribes"}, employee_name="Bob")
    assert fields["category"] is None
    assert fields["business_purpose"] == "Business expense"   # generic fallback


def test_map_includes_business_purpose_when_supplied():
    fields = receipt_to_fields({"vendor": "X"}, employee_name="Bob",
                               business_purpose="Client dinner")
    assert fields["business_purpose"] == "Client dinner"


def test_map_normalises_payment_method():
    def pm(v):
        return receipt_to_fields({"payment_method": v}, employee_name="A")["payment_method"]
    assert pm("VISA") == "card"
    assert pm("EDC CIMB NIAGA") == "card"       # card-terminal line → card
    assert pm("CASH") == "cash"
    assert pm("Contactless") == "contactless"
    assert receipt_to_fields({}, employee_name="A")["payment_method"] is None


def test_parse_strips_reasoning_think_block():
    from backend.agent.vision_extract import _parse_receipt_json
    out = _parse_receipt_json(
        '<think>The receipt shows {maybe} a total...</think>\n'
        '```json\n{"vendor": "BrightMart", "amount": 22.9}\n```')
    assert out == {"vendor": "BrightMart", "amount": 22.9}
