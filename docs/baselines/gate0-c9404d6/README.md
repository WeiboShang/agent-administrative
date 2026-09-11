# Gate 0 Baseline — `c9404d6`

Captured on 2026-07-30 from branch `codex/workflow-optimisation` before
feature-code changes.

## Purpose

This baseline separates pre-existing behaviour from regressions introduced by
the workflow optimisation. It records executable checks and the visible state
of WF1–WF3 before implementation.

## Environment

- Python: project `.venv`, Python 3.11
- Frontend runtime used for checks: existing Linux Node `v24.18.0`
- npm: `11.16.0`
- Application: FastAPI/Uvicorn on `http://127.0.0.1:8000`
- Browser viewport: 1440 × 900
- Data: existing synthetic local workspace

The Windows `npm/npx` entries appear earlier than Linux Node in the default WSL
PATH and cannot run correctly from the UNC workspace. Baseline frontend commands
therefore use the existing Linux Node path explicitly; no dependency was
installed or upgraded.

Playwright Chromium initially lacked `libnspr4`, `libnss3` and `libasound`.
Their Ubuntu packages were downloaded and extracted under `/tmp/chromedeps`
only. They were not installed system-wide and are not project dependencies.

## Executable baseline

| Check | Result |
|---|---|
| backend pytest | **339 passed**, one dependency deprecation warning |
| Ruff (`backend`) | **passed** |
| TypeScript `--noEmit` | **passed** |
| production build | **passed** |
| light-theme route smoke | **9/9 passed** |
| dark-theme route smoke | **9/9 passed** |
| WF1/WF2/WF3 Analysis tabs | **3/3 passed** |
| console errors / failed requests | **none detected** |
| horizontal overflow at 1440 px | **none detected** |

The pytest warning comes from `fastapi.testclient` importing the deprecated
Starlette/httpx compatibility path. It is a pre-existing dependency warning and
must not be mixed into a workflow feature slice.

## Saved screenshots

### WF1

- [Inbox work view](_inbox.png)
- [Inbox Analysis](_inbox_analytics.png)

### WF2

- [Calendar work view](_calendar.png)
- [Calendar Analysis](_calendar_analytics.png)

### WF3

- [Expense work view](_expenses.png)
- [Expense Analysis](_expenses_analytics.png)

## Visible baseline observations

These are characterisation findings, not new regressions:

### WF1

- The current page presents Summary & Key Points rather than the target Memo
  Checklist.
- The current review card exposes model-reported confidence.
- The current Analysis page is descriptive but sparse: open/triaged/routed
  tiles plus status, intent and outcome bars.
- One thread message visibly ends with an unsupported square glyph after
  “weekend”; preserve as a separate presentation issue unless the relevant
  WF1 slice touches text rendering.

### WF2

- Meeting creation starts from one natural-language form; Quick Create and
  explainable Top-K recommendation cards are not yet present.
- The current Analysis page already has a useful booking-density heatmap,
  meeting duration, room utilisation and participant-load views.
- Participant load splits `Alice Tan` and `alice` into separate identities.
  This is a pre-existing canonical-identity correctness issue.
- Both seeded meetings appear as `unassigned` for room utilisation.
- The current event representation cannot yet produce a true
  created/rescheduled/cancelled lifecycle trend.

### WF3

- The employee work page shows upload plus ledger/budget consequences.
- The submitted EUR claim retains an original EUR amount and derived GBP
  amount, which is the intended multi-currency baseline.
- The ledger does not expose an approver receipt-evidence workspace.
- The lifecycle has submitted/approved records but no
  needs-information/resubmission state.
- The current Analysis page shows status, GBP category/department spend and
  policy flags; currency exposure and lifecycle timing are not yet present.

## Gate result

Gate 0 executable checks were green. This is a frozen historical baseline; the optimisation
programme and formal Evaluation v3 were subsequently completed. Current behaviour is defined
by code and `docs/evaluation.md`.
