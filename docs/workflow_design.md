# Architecture and workflow design

This document describes the implemented system. Historical planning documents have been
removed from the public repository so that the code and this document remain the two sources
of truth.

## Design principle

The model proposes, deterministic code validates, a human decides, and code performs the
approved side effect.

```text
input -> LLM draft -> deterministic checks -> human review -> deterministic execution
                                                  |                    |
                                                  +-- reject ----------+
```

The LLM is used for language and image interpretation. It does not own policy decisions,
availability checks, database writes, or approval authority.

## Runtime structure

| Layer | Location | Responsibility |
|---|---|---|
| API | `backend/routers/` | HTTP contracts and workflow transitions |
| Agent | `backend/agent/` | Text extraction, vision extraction, prompts, normalisation |
| Workflow | `backend/workflows/` | Validation, policy, reconciliation, lifecycle rules |
| Backends | `backend/backends/` | SQLite records and calendar/directory interfaces |
| UI | `frontend-next/src/` | Review workspaces and evaluation views |
| Evaluation | `backend/evals/` | Frozen datasets, matched replays, scoring and reporting |

All core demo identities use `example.com`, and the default calendar backend is an in-memory
mock. The SQLite store can also be replaced with an in-memory store for tests and evaluation.

## Shared lifecycle

Every workflow follows the same control boundary:

1. Ingest the source and preserve its provenance.
2. Ask the model for a structured draft.
3. Validate required fields, identities, dates, resources and policy in code.
4. Show the draft, source evidence and warnings to a reviewer.
5. Revalidate the reviewer's final state.
6. Execute only after approval and append an audit record.

Edits are treated as a new version. Idempotency keys prevent repeated requests from creating
duplicate effects. Rejection records a reason and performs no operational mutation.

## WF1: inbox triage

WF1 reads a multi-party message thread and proposes zero or more administrative drafts. The
supported hand-offs are meeting requests and expense-related requests. Social,
hypothetical, cancelled and informational messages should produce no action.

Each proposed action stores its source message IDs and attachments. Thread-level
reconciliation catches retractions and prevents a later cancellation from being ignored.
Approved routes create pending downstream drafts; they do not book meetings or approve
claims.

Primary implementation:

- `backend/workflows/triage.py`
- `backend/agent/extract.py`
- `backend/routers/triage.py`

## WF2: conflict-aware scheduling

WF2 resolves participants, dates, times, duration, meeting mode and room requirements. Code
checks the organiser, participants and canonical room identifier against current state. If a
requested time is unavailable, the system can propose verified alternatives.

Approval creates a local event and an iCalendar file. Optional Google Calendar sync is
isolated behind a backend interface and is disabled by default. Formal evaluation always
injects a mock backend, so replay cannot contact Google.

Primary implementation:

- `backend/workflows/scheduling.py`
- `backend/workflows/date_resolution.py`
- `backend/backends/calendar.py`
- `backend/routers/scheduling.py`

## WF3: evidence-first expense review

WF3 stores receipt bytes, extracts structured fields, and keeps the model read separate from
the employee-submitted values. The reviewer sees the source image, both snapshots and the
deterministic verification state.

Policy code checks limits, budgets, currency conversion, duplicate evidence and arithmetic
consistency. A second critical-field read can expose plausible OCR errors. The employee and
approver are separate roles, and self-approval is blocked. Only an approved, revalidated
claim changes the ledger and budget.

Primary implementation:

- `backend/agent/vision_extract.py`
- `backend/workflows/expense.py`
- `backend/workflows/policy.py`
- `backend/routers/expense.py`

## Cross-workflow state

The record store contains threads, routed drafts, events, submissions, decisions and audit
entries. A routed item includes an origin link so the UI can return to the source thread.
The domain pages expose the consequence of a decision: an event appears on the calendar, or
an approved claim appears in the ledger and reduces the fictional department budget.

## Safety boundaries

- Model output is always untrusted input to typed schemas and deterministic validation.
- Missing required facts are surfaced instead of invented.
- Hard policy failures block execution; soft warnings require explicit acknowledgement.
- Approval is checked again immediately before mutation to catch stale conflicts.
- Evaluation runs use frozen inputs and isolated stores.
- Google credentials and local databases are gitignored.

## Intentional limitations

This is a research prototype, not a production enterprise service. It does not provide
authentication, tenancy, production observability, compliance controls or guarantees for
real employee and financial data. See [`results.md`](results.md) for empirical boundaries
and [`evaluation.md`](evaluation.md) for the scoring contract.
