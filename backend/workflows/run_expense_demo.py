"""Run WF3 vision → validate on a real receipt image (needs GROQ_API_KEY + an image).

Usage: python -m backend.workflows.run_expense_demo <receipt_image> [employee_name]

Vision-extracts the receipt (Llama 4 Scout), maps to expense fields, then validates and
runs the policy engine against a freshly-seeded store, printing the review-time draft.
Nothing is written (no decision made) — this is the reviewer's view.
"""
import sys

from ..agent.vision_extract import extract_receipt, receipt_to_fields
from ..backends.records import RecordStore
from ..fixtures import org
from .expense import validate_and_complete_expense


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python -m backend.workflows.run_expense_demo <image> [employee_name]")
        raise SystemExit(1)
    image = sys.argv[1]
    employee = sys.argv[2] if len(sys.argv) > 2 else "Alice Tan"
    mime = "image/jpeg" if image.lower().endswith((".jpg", ".jpeg")) else "image/png"

    store = RecordStore(":memory:")
    org.seed_from_org(store)

    vision = extract_receipt(image, mime=mime)
    print("— vision extraction —")
    print(vision)

    fields = receipt_to_fields(vision, employee_name=employee)
    draft = validate_and_complete_expense(fields, store)
    print("\n— expense draft (review) —")
    print("fields:  ", draft.fields)
    print("missing: ", draft.missing_required)
    print("flags:   ", [(f.rule, f.severity, f.message) for f in draft.flags])


if __name__ == "__main__":  # pragma: no cover
    main()
