# WF1 - Thread-aware Administrative Action Intake

> **Status:** implementation complete; final automated and production-build verification
> passed 2026-08-23. The authoritative formal result is V3.4.3 under `Part A Final`.
> Code is authoritative for current behaviour; older target/checkpoint text below is retained
> only where it explains design rationale.

---

## Target design at a glance

> **Normative optimisation specification; implementation complete.** The old 2026-07-01
> sections retained below are a historical appendix. This target separates implemented
> behaviour from proposed work so the project report does not claim unimplemented features.

WF1 is not primarily a summariser. It is a human-controlled **thread-to-work intake layer**
that converts a multi-message email/chat thread into two useful outputs: versioned workflow
actions for supported business processes, and a lightweight memo checklist for important
dates/events which do not need a dedicated workflow. A one-line summary remains supporting
context only.

---

## Target 1. Design decision and scope

Upgrade WF1 from single-pass triage to **thread-aware administrative action intake**:

- detect `schedule_meeting` and route a draft to WF2;
- detect `expense_claim`, preserve receipt attachment IDs and route a draft to WF3;
- turn other explicit follow-ups, important dates and confirmed events into editable
  `memo_items`, rather than promising a new downstream workflow for every business category;
- distinguish `create`, `amend` and `cancel` for supported workflow actions;
- let a human edit workflow fields/evidence/attachments and edit/check/dismiss memo items;
- route incomplete expense requests as `needs_evidence` drafts without inventing data;
- never create a live event, submit a claim, or cancel a real record in WF1.

The differentiating scenario is one evolving thread containing several supported workflow
requests, later corrections and ordinary administrative follow-ups. It demonstrates
multi-intent decomposition, conversation state, grounded extraction, workflow routing and
useful lightweight record-keeping without becoming a universal enterprise agent.

Included: email/chat threads, pasted text transcripts and optional synthetic/test
attachments. Excluded: a full task manager, dedicated leave/onboarding/procurement systems,
autonomous replies, live Gmail ingestion, policy calculation, calendar conflict checking,
receipt vision extraction and audio transcription. Audio can later be a preprocessing adapter
(`audio -> transcript -> WF1`), not a separate workflow or main evaluation track.

---

## Target 2. Pre-optimisation baseline versus implemented target

| Concern | Implemented now | Required target |
|---|---|---|
| Routable types | `schedule_meeting`, `leave_request` | supported routes limited to meeting + expense |
| Expense | explicitly excluded in prompt/router | detect claim creation and forward attachments |
| Key points | generic summary bullets | replace with editable `memo_items` for explicit dates/events/follow-ups |
| Unsupported business | leave is specially routed; other categories are undefined | represent useful details as memo items; no promised downstream automation |
| Thread state | one supplied `raw_text` | message IDs, incremental delta and revision links |
| Multiple actions | list-shaped output | stable identity, deduplication and independent lifecycle |
| Human gate | Route or Dismiss | edit workflow proposals; edit/check/dismiss memo items |
| Meeting/leave route | meeting creates `pending_review` / `needs_input` WF2 drafts; legacy leave may submit | all supported routes create downstream drafts only |
| Evidence | one action-level `source_span` | message-linked, field-level provenance for actions and memos |
| Re-triage | handled action may block later re-triage | preserve workflow/memo history and analyse new messages |

All rows in the implemented-target column are now built; historical baseline wording is
retained only for the project comparison.

**Implementation checkpoint — 2026-07-30, Phase 0 meeting slice.** A human-routed
`schedule_meeting` now runs deterministic WF2 validation and persists a
`schedule_meeting` record in `pending_review` or `needs_input`. WF1 no longer imports or
calls the scheduling execution function, creates no `booked` record, emits no notification
or `.ics`, and cannot reach the optional calendar backend. Complete and incomplete routes,
double-click idempotency and unchanged booked-event counts are covered at core and API
levels. The Inbox UI reports the downstream draft ID and explicitly says the calendar is
unchanged.

**Implementation checkpoint — 2026-07-30, Phase 1 action-contract slice.** Inbox actions
now expose a stable `action_id`, integer `version`, `operation`, model seed snapshot and
current seed snapshot. As of 2026-08-13, existing workspace rows are upgraded by an
idempotent startup migration and production records/API responses contain canonical fields
only. Route and Dismiss address an action by ID, require
`expected_version`, reject stale mutations of pending actions with HTTP 409 and increment
the version after a successful mutation. A downstream draft records its originating thread,
action ID/version and any available source message IDs. Both Inbox clients use this contract.

**Implementation checkpoint — 2026-07-30, WF1 Pass A feature-complete coding.** The code now
normalises legacy and incremental messages/attachments, grounds action and field evidence to
message IDs, reconciles stable action/memo identities, preserves model/current/version
snapshots, and records human/agent audit events. Supported actions are limited to
`schedule_meeting` and `expense_claim`; leave/onboarding and other explicit follow-ups become
local memo items. Human edits use version checks, and `create`/`amend`/`cancel` proposals use
linked revisions and deterministic route idempotency keys. Meeting routes create only WF2
review/input drafts. Expense routes create only WF3 evidence, exception-review or
needs-evidence drafts while preserving attachment IDs and origin links. The Inbox work UI now
supports incremental messages, action edit/route/dismiss, memo edit/check/dismiss, evidence
links and audit history. Its operational Analysis separates thread and action denominators,
provides attention filters, human-resolution counts and upcoming-memo drill-down.

**Historical verification checkpoint - 2026-08-01, WF1 automated Pass B.** Focused route,
grounding, reconciliation, incremental triage, stale action, memo lifecycle and archive-guard
tests pass. The evaluation taxonomy now uses the implemented meeting + expense capability
set, and an amend-version overwrite bug found by the new reconciliation test is fixed.
The then-current backend suite (354 tests), Ruff, TypeScript typecheck, production build and
live HTTP/static-asset smoke passed. This count is retained as a dated checkpoint, not a
claim about the current suite.

---

## Target 3. Pipeline and responsibility boundary

```text
1. CODE ingest       normalise messages, sender, timestamp and attachment IDs
2. LLM propose       one-line summary + workflow_actions[] + memo_items[] + evidence
3. CODE validate     schema, evidence, dates, duplicates, target links and flags
4. CODE reconcile    merge proposals into versioned workflow/memo state
5. UI review         human routes actions and edits/checks/dismisses memo items
   ----------------  WF1 ROUTING GATE  ----------------
6. CODE hand off     create a downstream draft only; preserve origin/provenance
7. UI downstream     human reviews WF2/WF3 completion and validation
   ----------------  DOWNSTREAM EXECUTION GATE  -------
8. CODE execute      downstream performs the approved external action
9. CODE audit        persist proposal, edit, decision and downstream link
```

WF1 detects intent, extracts seed data and records lightweight memo items. WF2 resolves
meeting dates, people and conflicts. WF3 reads receipts/evidence and applies expense checks.
Downstream consumes the human-confirmed seed instead of asking a second LLM to reinterpret
the full thread. Memo items remain local to WF1 and never execute external actions.

---

## Target 4. Action and operation taxonomy

| `action_type` | Meaning | Route |
|---|---|---|
| `schedule_meeting` | request to arrange a meeting | WF2 event draft |
| `expense_claim` | request to reimburse/submit a new expense | WF3 claim draft |
| `none` | no supported workflow action | no downstream route |

The target capability registry contains only meeting and expense. Leave, onboarding,
procurement, IT and similar content do not create pretend workflows: their explicit dates,
events or follow-ups become local memo items. General background remains only in the
one-line summary.

An expense policy question, historical mention, or request to approve somebody else's
existing claim is **not** a new `expense_claim`. It may produce a memo only when the thread
contains a concrete follow-up. A possible future `expense_approval_reference` is outside the
MVP because claim creation and approval have different semantics.

| `operation` | Meaning | Behaviour |
|---|---|---|
| `create` | new action | assign a stable action ID |
| `amend` | change an earlier action/draft | link target and append a version |
| `cancel` | cancel an earlier action/draft | create a reviewable cancellation proposal |

`confirm` is excluded from the MVP: it may be evidence, but is not a new action.

---

## Target 5. Structured contract

The LLM returns strict structured output; CODE assigns stable IDs, versions and timestamps.

```json
{
  "thread_summary": "Budget follow-up, a train reimbursement and Ana's start date are discussed.",
  "workflow_actions": [
    {
      "client_action_ref": "proposal-1",
      "action_type": "expense_claim",
      "operation": "create",
      "target_action_ref": null,
      "confidence": 0.92,
      "seed_fields": {
        "amount": 48.0,
        "currency": "GBP",
        "category": "travel",
        "business_purpose": "client-site train fare"
      },
      "source_evidence": [
        {"message_id": "m-003", "span": "Please reimburse the GBP 48 train fare"}
      ],
      "field_sources": {
        "amount": {"message_id": "m-003", "span": "GBP 48"}
      },
      "attachment_ids": ["att-receipt-01"]
    }
  ],
  "memo_items": [
    {
      "client_memo_ref": "memo-1",
      "text": "Prepare Ana's access before she starts",
      "item_type": "todo",
      "date_phrase": "before 2 September",
      "resolved_date": "2026-09-02",
      "date_relation": "before",
      "confidence": 0.89,
      "source_evidence": [
        {"message_id": "m-004", "span": "Ana starts on 2 September; access must be ready beforehand"}
      ]
    }
  ]
}
```

Persisted workflow-action fields:

```text
action_id, version, action_type, operation, target_action_id,
model_confidence, model_seed_fields, current_seed_fields,
source_evidence[], field_sources{}, attachment_ids[], missing_fields[], flags[],
status, routed_to, created_at, updated_at
```

Persisted memo fields:

```text
memo_id, text, item_type (`todo` | `important_date`),
date_phrase, resolved_date, date_relation, is_completed, source_evidence[],
model_text, current_text, created_at, updated_at, dismissed_at
```

`is_completed` defaults to `false` in CODE; the LLM does not decide whether the user has
completed a memo. The user may edit, add, reorder, check or dismiss memo items.

Action lifecycle: `proposed -> edited -> routed | dismissed | superseded`.
Memo lifecycle: `active -> completed | dismissed`.
Thread lifecycle: `unread -> analysed -> in_review -> partially_routed -> resolved | archived`.
Archive is allowed only when no workflow proposal remains pending. Active memo items remain
available after the thread itself is reviewed.

Target-specific workflow fields:

- Meeting: `title`, `participants[]`, `date_phrase/date`, `start_time`,
  `duration_minutes`, `location_or_video`, `agenda`.
- Expense: `employee_name`, `vendor`, `expense_date`, `amount`, `currency`, `category`,
  `business_purpose`, `cost_centre`, `attachment_ids[]`.

Missing values remain `null` and appear in `missing_fields`; the model must not invent an
amount, receipt, participant or date.

### Memo extraction boundary

Create a memo only for an explicit commitment, confirmed event, important date/deadline,
required follow-up or unresolved question which requires action. Do not create a memo for
general background, sentiment, speculation, completed history or an unsupported inference.
A supported meeting/expense workflow action must not be duplicated as an independent memo.
For leave/onboarding/procurement/IT content, record only the dates/events/follow-ups actually
stated in the source; never invent a standard business checklist.

---

## Target 6. Expense semantics

The previous assumption that a text thread cannot contain an expense is incorrect: email can
request reimbursement and carry attachments. WF1 detects/routes the request; WF3 reads the
receipt.

| Thread content | WF1 outcome |
|---|---|
| reimbursement request and receipt attached | claim draft with attachment ID |
| reimbursement request but no receipt | draft in `needs_evidence` |
| alternative evidence supplied | claim draft records evidence type and enters review |
| receipt is lost/unavailable | user may add a declaration; state becomes `pending_exception_review` |
| text amount conflicts with receipt extraction | WF3 flags `text_receipt_mismatch` |
| expense policy question | no new claim; memo only if a concrete follow-up exists |
| third-party completed claim | no new claim |
| approve an existing claim | unsupported in MVP; not claim creation |

WF1 validates attachment identity/MIME metadata but performs no OCR. In WF3, `needs_evidence`
allows three user paths: attach a receipt/duplicate receipt, attach alternative evidence, or
complete a missing-receipt declaration. A missing-receipt declaration never auto-approves a
claim; it enters human exception review. No universal amount threshold is hard-coded because
receipt requirements are organisation-specific. The handoff preserves thread/action/message
provenance for WF3.

---

## Target 7. Thread-level reconciliation

“Thread-aware” means more than giving an LLM one long string.

- Process initial messages chronologically and permit several active actions.
- Persist `last_triaged_message_id`; later analysis receives new messages plus compact
  active-action state.
- Routed/dismissed actions remain in history and do not block new-message analysis.
- CODE assigns `action_id` and monotonically increasing `version`.
- `amend`/`cancel` must resolve in-thread or to a linked record; otherwise add
  `target_unresolved` for human review.
- Corrections change only supported fields and retain earlier values/provenance.
- Deduplicate equivalent proposals but keep distinct meeting/expense actions separate.
- Use idempotency key `(thread_id, action_id, version, route_target)`.
- Latest supported correction wins per field; retractions/conflicting speakers become flags.
- Re-triage may propose a new/corrected memo, but must never reset a user-controlled
  `is_completed` value or recreate a dismissed memo.
- Normalised memo dates retain the original `date_phrase`; ambiguous dates remain `null` and
  receive `date_ambiguous` rather than being guessed.

```text
m1: Arrange a budget review next Tuesday with Bob.
m2: Also reimburse my GBP 48 train fare; receipt attached.
m3: Move the budget review to Thursday.
m4: Correction: the fare was GBP 84.
m5: Ana starts on 2 September; her access must be ready beforehand.
```

Expected: two workflow actions with separate version chains plus one memo item for Ana's
access/start date. Cancelling the meeting later must not cancel/recreate the expense or alter
the user's memo completion state.

---

## Target 8. Human review, deterministic guards and handoff

Workflow cards show type, operation, target, confidence, evidence, editable seed fields,
attachments, missing fields and flags. Their decisions are **Route as proposed**,
**Modify and route**, **Save as needs input** and **Dismiss**. Archive is available only when
all workflow proposals are resolved or none exists.

The Memo Checklist is deliberately phone-memo-like: each row shows text, optional important
date, source evidence and a checkbox. The user can check/uncheck, edit, add, reorder or dismiss
items. It has no assignee system, priority, dependencies, recurrence, notifications or team
collaboration.

Persist model and human versions of workflow fields and memo text/dates. This separates model
accuracy from usefulness after correction.

CODE must validate the Pydantic schema, verify evidence spans against messages, validate
attachment IDs, distinguish request from mention/history, detect workflow/memo duplicates,
validate revision targets, compute missing fields, enforce idempotency and ensure route means
draft. A memo cannot execute an external action.

| Proposal | Downstream state |
|---|---|
| complete/incomplete meeting | WF2 `pending_review` / `needs_input` |
| expense with receipt | WF3 `pending_extraction` |
| expense without receipt/evidence | WF3 `needs_evidence` |
| missing-receipt declaration | WF3 `pending_exception_review` |
| amend/cancel | linked revision `pending_review` |
| memo item | remains local to WF1; no downstream state |

Each downstream record has immutable `workflow`, `thread_id`, `action_id`, `action_version`
and `source_message_ids` origin data.

Suggested API (adapt naming to current routers):

```text
POST  /api/inbox/threads/{thread_id}/triage
POST  /api/inbox/threads/{thread_id}/messages
PATCH /api/inbox/threads/{thread_id}/actions/{action_id}
POST  /api/inbox/threads/{thread_id}/actions/{action_id}/route
POST  /api/inbox/threads/{thread_id}/actions/{action_id}/dismiss
POST  /api/inbox/threads/{thread_id}/memos
PATCH /api/inbox/threads/{thread_id}/memos/{memo_id}
POST  /api/inbox/threads/{thread_id}/archive
```

PATCH uses an allow-list. Route/dismiss includes expected version to reject stale UI writes.

---

## Target 9. Existing data inventory

WF1 does use open data, but its present public coverage is narrow and negative-only.

| Asset | Current size | Purpose | Limitation |
|---|---:|---|---|
| standard synthetic tiers | 36 cached, about 6/tier | meeting/leave/multi/noise/out-of-scope/ambiguous | legacy labels; no expense/memo/operation taxonomy |
| frozen realised file | 45 rows; 30 in current evaluated cache | linguistic variation | not 45 independent gold cases |
| minimal pairs | 48 rows | controlled intent contrasts | narrow contrasts |
| retraction/control | 18 rows | near/far retraction | no version-linked route or memo persistence |
| underspecified | 6 rows | incomplete request | too small for a strong claim |
| AMI/QMSum sample | 20 public transcripts | false-positive/abstention stress | no positive route or memo labels in current harness |

Do not sum these into one independent headline sample: some are paired transformations and
answer different questions. The key weaknesses are small cells (often `n=6`), no public
expense-route gold and no current gold for the new Memo Checklist.

---

## Target 10. Data upgrade plan

### Controlled synthetic core

Freeze **90 semantic gold specifications** before text realisation:

| Stratum | Gold specifications |
|---|---:|
| meeting create | 15 |
| expense create, with/without receipt/evidence | 15 |
| mixed workflow actions plus memo items | 15 |
| amend/cancel/retraction | 15 |
| memo-only dates/events/follow-ups (leave/onboarding/etc.) | 10 |
| incomplete/ambiguous/date-unresolved | 10 |
| out-of-scope/third-party/completed/social negatives | 10 |
| **Total** | **90** |

For each specification create a deterministic template and one LLM-realised conversation.
This is 180 texts but only 90 underlying cases; report separately/paired, not as 180
independent cases. Store generator model/version, prompt hash, seed, time, back-check and
rejection reason. Prefer a different model family for realisation. Freeze gold first and
accept samples using rules plus human inspection, not the evaluated model grading itself.

### Public external data

- **MailEx**: held-out `Request Meeting` and `Amend Meeting Data` fit positive meeting and
  revision transfer. A manually verified, predeclared subset of `Request Action` may test
  whether explicit follow-ups become grounded memo items. It has no native `expense_claim`,
  so it is not expense gold.
- **AMI/QMSum**: keep, and if feasible deterministically expand to 50, as an over-action/
  abstention set. Meeting discussion is not a scheduling request.
- **Lampert request corpus / email dialogue-act corpus**: possible binary actionability
  evidence, not route-specific gold; verify licence/access/mapping before use.
- **EmailSum/QMSum summary labels**: exclude from the main study because summary is secondary.

The evaluation may use LLM-generated and public data together, but report them as distinct
validity layers rather than one pooled accuracy:

```text
template synthetic      -> controlled edge cases/internal validity
LLM-realised synthetic  -> linguistic robustness with known gold
public held-out data     -> external transfer or abstention validity
```

Cite provenance/licence, predefine mappings, avoid train/test contamination, and state that
the study evaluates prompting/workflow design rather than a newly trained model.

---

## Target 11. Implementation sequence

### Phase 0 - correctness

- make every WF1 route create a downstream draft instead of execute/submit;
- add origin linkage, idempotency and tests proving no external execution.

### Phase 1 - differentiating MVP

- define a capability registry with only `schedule_meeting` and `expense_claim` routes;
- add expense prompt/schema/router support, attachment forwarding and `needs_evidence` paths;
- replace standalone `key_points` with grounded `memo_items` (`todo`/`important_date`);
- add human edit-and-route for workflows and edit/add/reorder/check/dismiss for memos;
- preserve model versus human values and test meeting + expense + memo threads;
- stop exposing `leave_request` as a target WF1 route; the unused runtime schema/policy was
  subsequently removed in the 2026-08-13 consolidation.

### Phase 2 - true thread lifecycle

- store message IDs and `last_triaged_message_id`;
- implement versioned amend/cancel reconciliation and incremental analysis;
- preserve user-controlled memo completion/dismissal state across re-triage;
- add stale-version/duplicate-route protection and render history/provenance.

### Phase 3 - data freeze before evaluation

- freeze 90 semantic cases and paired renderings;
- integrate only declared MailEx subsets/mappings;
- correct AMI/QMSum documentation to negative-only;
- freeze a versioned WF1 evaluation manifest.

Formal comparisons, baselines and ablations begin only after all workflows are stable.

---

## Target 12. Focused operational Analysis

> **Status: implemented; final automated/build verification passed 2026-08-23.** This is the user-facing operational view for an administrative
> coordinator. It must help the user decide what needs attention next; it is not a model
> evaluation dashboard. Precision, recall, extraction accuracy, confidence and ablation
> results belong in the later Evaluation work.

### Questions the page must answer

1. Which threads or proposed actions are waiting for human review?
2. Which expense routes are blocked because receipt or alternative evidence is missing?
3. What work has been routed to WF2/WF3, modified, dismissed or left pending?
4. Which grounded memo dates or events need attention soon?

### Primary tiles and views

Keep the page small and decision-oriented:

| View | Required content | Interaction |
|---|---|---|
| attention tiles | awaiting review · needs evidence · open memo items · important dates in the next 7 days | click to filter the underlying queue |
| work-queue funnel | new → triaged → awaiting review → routed / archived | show counts and percentages, but retain the count denominator |
| proposed output mix | meeting route · expense route · memo-only | count actions separately from distinct threads |
| human resolution | routed unchanged · modified then routed · dismissed · pending | filter by period and open the corresponding thread |
| upcoming memo list | date, concise event, source thread and completion state | review/check/dismiss without turning WF1 into a task manager |

The existing Open threads / Triaged / Actions routed / Awaiting you tiles and status bars
are the baseline. Reuse them where they answer the questions above; remove duplicated status
charts instead of adding more panels.

### Data and presentation rules

- A multi-action thread is one thread but several proposed actions; never mix those
  denominators in one total.
- `needs_evidence` is a workflow state, not a model error or automatic rejection.
- Memo completion/dismissal is user-controlled state and must survive re-triage.
- Important dates require a resolvable date; unresolved dates stay in the review queue.
- Every count must link back to its records so the page supports action rather than passive
  reporting.
- Do not show model-reported confidence, precision/recall, false-positive rate or gold-label
  correctness on this page.

Useful filters are time range, thread status, output type and assignee/owner. Evaluation-only
diagnostics may reuse the same logged events later, but they must appear in a separate
research view.

## Target 13. Acceptance criteria and later evaluation contract

Acceptance tests must prove: one thread independently routes meeting and expense while also
creating non-duplicated memo items; missing receipt becomes `needs_evidence`; receipt or
alternative-evidence IDs reach WF3 unchanged; a declaration requires exception review; WF1
performs no OCR; workflow and memo edits remain auditable; user memo completion is not reset
by re-triage; ambiguous dates are not guessed; amendment changes only its target; replayed
Route is idempotent; evidence is grounded; negative threads abstain; and WF1 never executes
external actions.

When evaluation begins, use three headline outputs:

1. **Strict work-output correctness** - workflow action type/operation/required fields and
   memo item/date correctness against frozen gold, reported as two subrows rather than a new
   family of unrelated metrics.
2. **End-to-end draft outcome** - correct draft, wrong draft, correct abstention or blocked;
   report before and after human correction separately. Memo checkbox usage is not a model
   metric.
3. **Evidence grounding** - evidence supports critical workflow fields and memo content, and
   no unsupported critical item is introduced.

Revision linking, missing-evidence behaviour, memo omissions/duplicates, false-positive type
and edit burden are appendix diagnostics. Instrument now; evaluate formally only after
WF1-WF3 are stable.

---

## Target 14. Text transcript and audio boundary

A pasted or uploaded **text transcript** may use the same WF1 schema: one-line summary,
supported workflow actions and memo items. It is another text source, not a fourth workflow.
Direct audio support is deferred: speech-to-text and speaker diarisation would introduce a
separate error chain (transcription, speaker attribution and audio robustness) and a large
new evaluation burden. If added later, it should be an input adapter which produces a
reviewable transcript before WF1, not a claimed workflow innovation.

## Target 15. Research/open-source basis

- MailEx paper: <https://aclanthology.org/2023.emnlp-main.801/>
- MailEx data/code: <https://github.com/salokr/Email-Event-Extraction>
- Lampert et al. action-request detection: <https://aclanthology.org/N10-1142/>
- Large email dialogue-act corpus: <https://aclanthology.org/2020.coling-main.436/>
- EmailSum: <https://aclanthology.org/2021.acl-long.537/>
- QMSum: <https://aclanthology.org/2021.naacl-main.472/>
- AMI annotation information: <https://groups.inf.ed.ac.uk/ami/corpus/annotation.shtml>
- AIMU action annotation: <https://aclanthology.org/L16-1117/>
- LangChain email-agent reference: <https://github.com/langchain-ai/agents-from-scratch>
- AutomationBench: <https://github.com/zapier/AutomationBench>
- Email-as-interface workflow paper: <https://arxiv.org/abs/2506.23850>

MailEx is the best immediate external fit: its taxonomy includes meeting requests and meeting
amendments in conversational email (about 1,500 threads, 4,000 emails and 8,000 events across
ten event types), but no native expense-claim label. QMSum/EmailSum are summary resources;
AMI is more defensible for abstention than positive routing. Open-source architectures
support triage plus HITL, but adding LangGraph is not itself innovation and is unnecessary
unless later implementation complexity justifies it.

---

# Historical appendix - superseded 2026-07-01 record

The remaining sections are non-normative and retained only to show design evolution. Their
expense exclusion and AMI/QMSum positive-label claim are explicitly superseded above.

## A. Positioning

Lives in the **📥 Inbox** domain. Input = an unstructured multi-party chat / email
thread. Job = turn a noisy conversation into **structured, routable actions**, keeping
the human in control of what actually gets routed.

---

## B. End-to-end pipeline (LLM vs CODE)

```
1. CODE ingest    split into turns (speaker + timestamp); strip signatures / quoted history
2. LLM  triage    read thread -> summary + key_points + decisions + [detected_actions] + per-action seed fields & confidence
3. CODE validate  action_type is valid? de-dupe? mark low-confidence?
4. CODE assemble  triage card (summary + action list + per-action routing suggestion)
   ───────────────  ★ APPROVAL GATE (human confirms routing) ★
5a. Route  an action  -> create a downstream WF2/WF3 draft, prefilled from seed_fields
5b. Dismiss an action -> mark false-positive, log (evaluation data)
5c. Archive the thread -> no action; mark reviewed + store summary
6. CODE log       append to audit trail
```

**Split:** the LLM only *detects + extracts seed fields*. All date resolution, directory
lookup, conflict/policy checks are done by the **downstream** workflow, not duplicated in
WF1. So **WF1 = detect + seed**, downstream = **validate + complete + govern**.

---

## C. Triage schema (LLM output)

```json
{
  "thread_summary": "one-line context (the demoted summary)",
  "key_points": ["…"],
  "decisions": [{"decision": "…", "by_whom": "…"}],
  "open_questions": ["…"],
  "detected_actions": [
    {
      "action_type": "schedule_meeting",
      "confidence": 0.9,
      "seed_fields": {"title": "Budget review", "participants": ["Bob", "Chen"],
                      "date_phrase": "next Tuesday", "time": "14:00"},
      "source_span": "…the exact words that triggered this…",
      "rationale": "why this is a scheduling action"
    }
  ]
}
```

`source_span` is load-bearing: at the gate it shows the human **which sentence the agent
based its judgement on** — traceable.

---

## D. Routing mechanism

**Multi-action.** A thread may contain several actions ("sync on the budget next Tuesday"
*and* "expense the offsite tickets") → `detected_actions` is a **list**; each is routed
independently. This covers the `multi` difficulty tier and is where WF1 has real depth
(decomposing a messy thread into several structured, routable actions).

**Routing targets + a consistency rule:**

| Detected action | Routes to | Note |
|---|---|---|
| `schedule_meeting` | **WF2** | most natural |
| `leave_request` | **WF3 – leave (text)** | e.g. "I'd like leave 14–21 Jul" → extract leave fields |
| generic to-do ("chase legal") | **not routed**; recorded as a to-do annotation on the thread | no matching structured workflow |
| pure FYI / small talk | **Archive** (correctly does nothing) | out-of-scope |

**⚠ Expense never goes through triage.** An expense needs a *receipt image*, which a chat
thread does not contain — you do not "detect an expense" in text and fabricate a claim.
At most, WF1 surfaces a to-do ("expense mentioned — upload the receipt in Expenses"). So:

- **Reactive entry (Inbox / WF1):** text thread → routes to **scheduling / leave**.
- **Direct entry (domain page):** upload a receipt → expense; or book directly in Calendar.

**Extraction hand-off rule (important).** When an action is Routed, the downstream
workflow **takes WF1's `seed_fields` as its extraction and runs only its CODE
validate+complete** — it does **not** re-run an LLM extraction on the thread (no double
extraction, no divergence). `seed_fields` therefore follow the downstream schema exactly
(WF1's prompt is given the target schemas). Direct-entry (typed request in a domain page)
still runs that workflow's own extractor.

**Traceability / linkage.** On Route: `detected_action.routed_to = <downstream record id>`
and the downstream record carries `origin = {thread_id, action_index}`. Re-routing an
already-routed action is blocked (`status = routed`).

---

## E. Thread record & lifecycle

Written to the **`threads`** store (behind the backend interface, like `submissions`/
`events`):

```json
{
  "id": "thr-000017",
  "source": "email",
  "raw_text": "…the thread…",
  "summary": "…",
  "detected_actions": [
    {"action_type": "schedule_meeting", "status": "routed",
     "routed_to": "evt-000031", "seed_fields": {…}, "source_span": "…", "confidence": 0.9},
    {"action_type": "leave_request",  "status": "dismissed", "seed_fields": {…}}
  ],
  "status": "resolved",
  "reviewed_by": "coordinator",
  "created_at": "…", "updated_at": "…", "audit": ["…"]
}
```

Lifecycle: `unread → in_review → resolved` (every action routed or dismissed) or
`archived` (no actionable content). Per-action status: `pending → routed | dismissed`.

---

## F. Approval gate

Per-action, at the WF1 gate: **Route** (create downstream draft) / **Dismiss** (false
positive) / thread-level **Archive** (whole thread has nothing to do). Routed actions
then get their own downstream review (the WF2/WF3 gate) — so there are two stages: WF1
confirms *routing*, the downstream confirms the *action*. For multi-action threads this
is necessary, and the routing decision is itself human-controlled RQ3 data.

**No auto-archive.** Even a thread with zero detected actions is shown for the human to
Archive — confirming the agent's "nothing to do" is where correct-refusal data comes from.

---

## G. Consequences of each decision

- **Route** = routing executed; a pending draft appears in the target domain
  (Calendar / Leave) — real downstream work created.
- **Dismiss** = recorded as a false positive (evaluation data: the agent over-detected).
- **Archive** = thread marked reviewed + summary stored; no downstream.

Generic to-dos are display-only annotations on the thread (no task-manager is built).

---

## H. Data

**① Synthetic thread generator (PRIMARY)** — reverse generation; the **LLM realiser
matters most here** (multi-party dialogue cannot be templated):

```
CODE sample gold (a thread containing N actions of known type with known seed fields)
  → LLM realise as a natural multi-party conversation
  → back-check (are the intended actions detected, seed fields recoverable?)
```

- **Difficulty tiers:** clean (one clear action) · **multi** (several actions) ·
  **implicit** ("someone should sort the venue") · noise (small talk around one action) ·
  **out_of_scope** (pure FYI → must Archive) · ambiguous (unclear if actionable).
- **Note:** the back-check here is *softer* than WF2's exact date round-trip (detection is
  fuzzy). It verifies the gold action types are detectable and seed fields recoverable;
  drifted samples (dropped/spurious action) are discarded and regenerated.

**② External validity:** **AMI / QMSum** — meeting transcripts with **~381 action-item
annotations**, the natural gold for the "detect action items" sub-task. WF1's strongest
external fit.

---

## I. Frontend

The 📥 Inbox domain page: thread list + a two-pane thread detail (original conversation |
triage card with detected actions, source evidence, Route/Dismiss + thread Archive). The
maintained UI contract is the React implementation under `frontend-next/src/pages/inbox/`.

---

## J. Models

Text LLM: Groq Llama-3.3-70B (primary) + a cross-family comparison — model = RQ2
variable. *(As built: the comparison is `openai/gpt-oss-120b`.)*

---

## K. Evaluation signals (deferred — placeholder)

Action-detection precision/recall (vs gold) · routing accuracy (right downstream) ·
correct-Archive rate on out-of-scope (correct refusal) · seed-field extraction accuracy ·
false-positive rate · summary faithfulness.

---

## Open items to confirm

- Generic to-dos are display-only (no task manager) — acceptable for scope?
- Two-stage gate (route, then downstream approve) vs streamlining single high-confidence
  actions to one gate — current design keeps two stages for clarity + multi-action.
