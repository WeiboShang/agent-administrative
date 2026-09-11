# Human Evaluation V5 protocol

Status: **V5.1 completed; latest formal row is authoritative**
Protocol version: 5.1
Evaluation type: controlled single-reviewer, within-reviewer Manual versus Agent-Assisted comparison
Data boundary: synthetic inputs and mock backends only

Frozen models: `openai/gpt-oss-120b` for WF1/WF2 text; `qwen/qwen3.6-27b` for WF3 receipts.

## 1. Why V5 exists

V5 replaces V4 for the final evaluation run because V4 could not support a fully
credible interpretation of task success.  V4 exposed an expected WF2 decision in one
reviewer-visible structure, did not always score the submitted decision itself, used weak
WF1 field checks, and could mark a warning-bearing WF3 case complete even when the real
approval transition had been blocked.  Its relative-date policy also treated
`next Wednesday` inconsistently across extraction, deterministic normalisation and the
review form.

V5 changes the evaluation protocol, not the three production workflows.  It freezes a new
case set, uses the existing workflow validation and mock execution paths, and strengthens
the boundary between reviewer assistance and server-only scoring.

## 2. Research comparison and interpretation boundary

The comparison is:

- **Manual:** the reviewer sees the synthetic request, neutral task references, a blank
  editable form, and the common gold-free deterministic policy preflight.
- **Agent-Assisted:** the reviewer sees the same evidence, form and policy preflight, plus
  the actual model extraction. The editable form is pre-filled from this output.

The evaluation contains one reviewer (the project author). Results are descriptive
within-reviewer evidence; they are not estimates of population-level usability.  Six pilot
cases train the reviewer on the interface and are excluded from the formal analysis.

## 3. Frozen case design

There are 42 cases: 6 pilots followed by 36 formal cases.  Each workflow has 12 formal
cases, split 6 Manual / 6 Agent-Assisted.  Within each condition and workflow there are two
ordinary, two underspecified/degraded and two complex/safety cases.  Matched pairs use
different surface details and reverse condition allocation across adjacent pairs.

| Workflow | Ordinary coverage | Underspecified/degraded coverage | Complex/safety coverage |
|---|---|---|---|
| WF1 intake/triage | complete meeting and expense requests | missing date, missing time, unsupported requests | two-action threads, revision, selective retraction |
| WF2 scheduling | explicit, tomorrow, bare weekday and next-weekday requests | missing date, missing time, vague date, unresolved participant role | participant conflict, room conflict, multi-turn revision |
| WF3 expense | clean receipts | skewed receipts and cropped critical evidence | hard-limit rejection; exact duplicate rejection |

The exact case order and allocation are frozen in
`data/eval_datasets/human_v5_manifest.json`.  Reviewer-visible sources are in
`data/eval_datasets/human_v5_sources.json`.  Expected decisions and field predicates are
stored separately in `data/eval_datasets/human_v5_gold.json`.

## 4. Temporal contract

All relative dates are interpreted against the case's `scenario_now`, never the real date
on which the reviewer runs the evaluation.

- A bare weekday is the nearest strictly future occurrence.
- `this <weekday>` means that weekday in the current calendar week if it has not passed.
- `next <weekday>` means that weekday in the following calendar week.
- A vague expression without a resolvable day remains missing and requires information.

For the frozen V5 scenario time Monday 2026-08-17:

| Expression | Result |
|---|---|
| `Tuesday` | 2026-08-18 |
| `this Tuesday` | 2026-08-18 |
| `next Tuesday` | 2026-08-25 |

The LLM is responsible only for preserving or extracting the phrase.  Deterministic code
owns the conversion to an ISO date.  A present time such as `11:30` is already canonical;
that is why it can be displayed without a second temporal conversion.

## 5. Never-invent and safe-completion rules

Essential missing information is not silently supplied:

- WF1 may route an intentionally incomplete downstream draft.  The missing field stays
  null and the routed record must enter the appropriate `needs_input`/evidence state.
- WF2 does not run candidate generation unless date, time and resolvable participants are
  all present. Missing, vague or role-only information requires `request_information`.
  For a conflicting slot, Manual may reject the booking or request information. In the
  Agent-Assisted condition, the authorised reviewer may select one of three verified-free
  Agent suggestions and approve the rescheduled meeting.
- WF3 requests information when critical receipt evidence cannot be verified.  A safe
  `needs_information` state is a successful task outcome for those cases.

Complex and safety cases are not automatically failures. Their gold defines the safe
completion: a safe Manual response or conflict-free Agent rescue for a conflicting slot, a
correct hard-limit or duplicate rejection, or a selective action that
honours the latest instruction.

## 6. Actual Agent cache and freeze discipline

Agent assistance must come from the system's actual extraction path.  It must never be
constructed from gold or manually corrected before the reviewer sees it.

1. Freeze manifest and source inputs before model calls.
2. Run WF1/WF2 inputs through production `llm_extract` once.  Retry at most once and only
   for a technical parse/transport failure; retain semantically wrong outputs.
3. Import WF3 outputs from the committed Qwen receipt extraction cache used by the system.
4. Store raw extraction, model identifier, source SHA-256, prompt SHA-256, origin and UTC
   generation time in `data/eval_cache/human_v5_agent_outputs.jsonl`.
5. Seal the manifest as `frozen_pre_collection`, add `frozen_at`, and do not call a model
   during the formal human run.

The V5 server refuses to create any session unless all 21 Agent-Assisted cache records
exist, every source hash matches, and the manifest is marked frozen. Manual cases never
call a model. Seven WF3 Agent-Assisted records came from the committed receipt cache; the
seven WF1 and seven WF2 Agent-Assisted texts were frozen with `openai/gpt-oss-120b` on
2026-08-20. No model is called during collection.

## 7. Reviewer-visible versus scoring-only information

The reviewer projection is constructed from the manifest, public source and frozen Agent
output.  It does not deserialize the gold file.  A recursive assertion rejects projection
keys such as `expected_decisions`, `expected_status`, `hard_fields`, `slot_policy` or
`correct_answer`.

Reviewer-visible checks may show facts such as:

- missing essential fields;
- the raw date phrase and resolved ISO date;
- unresolved participants;
- calendar conflicts and, only in Agent-Assisted conflict cases, available candidate slots;
- missing receipt evidence;
- policy flags such as `over_limit` or `duplicate`.

They may not show the expected decision, accepted answer, gold candidate or correctness.
Gold is first loaded only after the submitted task has been executed in a fresh mock
workspace.

## 8. Execution and scoring contract

A case succeeds only when all of the following are true:

1. the submitted **decision** is accepted by gold;
2. the canonical **hard structured fields** match;
3. the executed **final state** matches; and
4. no unsafe mutation occurred.

Hard structured fields include dates, times, participant IDs, duration, location where
material, amount, currency, attachment identity and action type.  Participant names are
resolved to canonical synthetic user IDs; amount is compared to cents; currency and room
matching are case-normalised.  Title, agenda and business-purpose wording are not exact
string matched.

Workflow-specific final-state rules are:

- **WF1:** exactly the expected downstream draft type(s) must be created. The person who
  requests a meeting is a participant by default unless explicitly excluded. Required fields
  are checked per action, and deliberately absent fields must remain absent.  A retracted
  expense or superseded meeting value cannot be routed safely.
- **WF2:** `approve` must create exactly one booked event through the production scheduling
  gate and mock calendar backend. In Manual conflict cases, `reject` and
  `request_information` are both safe outcomes. In Agent-Assisted conflict cases, three
  deterministic candidate slots are exposed; selecting one updates the form and it must
  pass the same live conflict check before approval. Booking a conflicting slot is unsafe.
- **WF3:** the executed claim status must be `approved`, `rejected` or
  `needs_information` as specified. The £50 meals limit and exact-duplicate rule are hard
  constraints and require rejection. Any remaining soft-warning approval requires
  acknowledgement and a written reason. If the production transition returns
  `override_acknowledgement_required`
  or another blocked status, the API rejects completion instead of recording a superficial
  approval.

Decision errors therefore cannot pass merely because both choices caused no mutation.

After collection, the £50 meals rule was adjudicated consistently as mandatory. The
original frozen gold is preserved; the formal matched pair and the excluded pilot are
overlaid by `human_v5_gold_adjudication_v1.json`. This outcome-aware correction must be
reported transparently and is not represented as pre-registered gold.

## 9. Timing, interactions and analysis

The browser records case-visible, review-start, first-interaction, decision and completion
timestamps.  Hidden-tab duration is subtracted from active review time.  It also records
first edits, evidence opening, decision selection, warning inspection
and submit actions.  Frozen replay latency is not reported as live provider latency.

The final report excludes pilots and reports task success, unsafe actions, decision
correctness, active review time and interaction count by workflow and condition, plus task
success and safety by scenario family.  Exact protocol file hashes, Git commit and dirty
state are stored with the session and formal result.

## 10. Completed collection and reproducibility boundary

The previous V5 result remains immutable. V5.1 passed implementation tests, its
Agent-Assisted outputs and protocol hashes were sealed, and the six pilots plus 36 formal
cases were completed on 2026-08-20. The authoritative append-only row has SHA-256
`5525e7844f1be676da589fc34cdc6a8ddf1d4fe584805494b45a6cbfe09263df`.

The one-time sealing command used before collection was:

```bash
PYTHONPATH=. .venv/bin/python -m backend.evals.freeze_human_v5_cache --retry-technical 1 --seal
```

The `--seal` step verifies 21 unique Agent-Assisted cache rows and every source hash before
setting:

```json
"protocol_status": "frozen_pre_collection",
"frozen_at": "<UTC ISO-8601 timestamp>"
```

The final code checks remain:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q --import-mode=importlib
cd frontend-next && npx tsc --noEmit && npm run build
```

Do not create another result under the V5.1 label or edit the existing JSONL. Any future
collection would require a new protocol version, a freshly sealed manifest/cache boundary,
and a new append-only result.
