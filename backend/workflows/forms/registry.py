"""WF3 expense schema — required/optional fields for evidence review.

The central design artifact of WF3 (docs/workflow_design.md): the field sets are defined in
CODE, not decided by the LLM. Values match prompts.py FORM_PREFILL_PROMPT and the
``FormType`` literal in schemas/drafts.py.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class FormSchema:
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    date_fields: tuple[str, ...] = ()      # required-or-optional fields that must be YYYY-MM-DD
    numeric_fields: tuple[str, ...] = ()   # fields that must parse as a number


FORM_SCHEMAS: dict[str, FormSchema] = {
    "expense_claim": FormSchema(
        # v2 (multimodal): vendor comes from the receipt; business_purpose never appears on
        # a receipt so it is deliberately required → surfaces as missing until the human
        # fills it (docs/workflow_design.md).
        required=("employee_name", "vendor", "date", "amount", "currency", "category",
                  "business_purpose"),
        optional=("department", "payment_method", "line_items", "tax"),
        date_fields=("date",),
        numeric_fields=("amount",),
    ),
}
