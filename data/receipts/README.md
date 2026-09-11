# Test receipt images (WF3)

Drop receipt images here to smoke-test the WF3 vision pipeline, then run:

```bash
cd administrative-agent
.venv/bin/python -m backend.workflows.run_expense_demo data/receipts/<your_file>.jpg "Alice Tan"
```

Supported: `.jpg` / `.jpeg` / `.png` (≤ 20 MB — Groq's image-input limit).

**Ethics (docs/workflow_design.md):** use synthetic / sample receipts, or ones with no real
person's identifiable data. Do **not** commit real receipts into the evaluated dataset —
the primary eval data will come from the synthetic receipt generator.
