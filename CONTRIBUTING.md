# Contributing

This repository is an evidence-bearing research prototype. Changes must preserve its
evaluation and safety boundaries.

## Before opening a pull request

1. Use synthetic people, messages, receipts, and calendar records only.
2. Keep all model output reviewable. An LLM must not submit, approve, send, or book without
   the existing human approval transition.
3. Put side effects behind the current backend interfaces. Tests and evaluation must inject
   mock backends.
4. Do not rewrite frozen datasets, cached model outputs, or append-only formal result rows.
5. Add or update tests for behaviour changes.

Run the release checks from the repository root:

```bash
PYTHONPATH=. .venv/bin/python -m backend.scripts.materialize_evaluation_receipts
PYTHONPATH=. .venv/bin/python -m pytest backend -q --import-mode=importlib
.venv/bin/ruff check --no-cache backend
PYTHONPATH=. .venv/bin/python -m backend.evals.final_part_a

cd frontend-next
npm ci
npx tsc --noEmit
npm run build
```

Open an issue before proposing a new provider integration or any use of real personal data.
Those changes affect the project's ethics and evaluation boundaries, not just its code.
