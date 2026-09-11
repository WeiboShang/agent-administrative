# Workflow Design Specification (v2 — 2026-07-01 re-scope)

> ⚠️ **Design record (written 2026-07-01, before implementation). Not current behaviour.**
> The system evolved past this spec — later additions include O4 content generation, the
> vision-model migration, per-thread date resolution, malformed-output normalisation and
> multi-currency handling. Read this for **design intent and rationale**; for what the
> system actually does, read the code, and for evaluation numbers read
> [`results.md`](results.md). Where this file and the code disagree, the code is right.
> In particular, the leave route and “expense never via triage” statements below are
> superseded: current WF1 routes meeting/expense drafts, and current WF3 is expense-only.
>
> **Role:** the integrating design contract of the re-scope (superseded v1, the old four
> text→JSON workflows). the fine-grained per-workflow contracts live in
> [`wf1_triage_design.md`](wf1_triage_design.md),
> [`wf2_scheduling_design.md`](wf2_scheduling_design.md),
> [`wf3_expense_design.md`](wf3_expense_design.md); the implemented UI in
> `frontend-next/`; data in
> [`data_strategy.md`](data_strategy.md); metrics in [`evaluation.md`](evaluation.md).
> Governed by CLAUDE.md §2 (agent proposes / human decides / code executes) and §3
> (synthetic task data; provider access isolated from evaluation).
>
> Reading order: §0 what changed → §1 skeleton → §2 shared foundation → §3 the three
> workflows → §4 cross-workflow flows → §5–9 frontend / data / eval / WF5 / RQ mapping.

---

## 0. What changed in v2

From "four parallel text→JSON tools with a ceremonial approval gate" to **a stateful
administrative workspace with three deep workflows**, where **approve produces real,
visible, accumulating consequences**. The core principle is unchanged. Concretely:

- **Three core workflows**: WF1 Triage (Inbox) · WF2 Scheduling (Calendar) · WF3
  Expense+Leave (Requests). WF1 feeds WF2/WF3.
- **Old WF4 (email drafting)** → not a workflow; a **content-generation feature** (§2.6).
- **WF5 (daily briefing)** → optional/last, demonstrates the proactive trigger (§8).
- **Stateful, interconnected record stores** make consequences real; a **policy/checks
  engine** adds governance; the UI is organised by **business domain**.

---

## 1. Shared execution skeleton

Every workflow is the same graph with workflow-specific nodes swapped in:

```
[ingest]──[extract*]──[validate+complete/checks*]──[assemble*]──┐
  CODE      LLM              CODE                    CODE        │
                                                     ★ APPROVAL GATE ★
                                                     ├ approve → [execute*] → write to store
                                                     ├ edit    → [validate*] → execute
                                                     └ reject  → [discard]
                                                                    │
                                                            [log eval record]
```

`*` = workflow-specific. **LLM-vs-CODE split (CLAUDE.md §4.4):**

| Concern | Owner |
|---|---|
| Understand language; extract intent/fields (text **or image**); generate prose | **LLM** |
| Date/time resolution; directory/room/availability lookups; conflict & policy checks | **CODE** |
| Schema validation, required-field/missing detection, defaults | **CODE** |
| Writing to a record store | **CODE** |

---

## 2. Shared foundation

### 2.1 Record stores (state made real)

Three stores, each behind the backend interface (§4.2 CLAUDE.md), **real local SQLite +
synthetic data**, **seedable/resettable** so evaluation is reproducible:

| Store | Owner | Records | Lifecycle |
|---|---|---|---|
| `threads` | WF1 | inbox threads + detected actions | `unread → in_review → resolved / archived` |
| `events` | WF2 | calendar events | `proposed → booked / rejected` |
| `submissions` | WF3 | expense claims + leave requests | `draft → approved / rejected` |

Common envelope: `id, type, status, fields(JSON), submitted_by/organizer, reviewed_by,
origin (upstream link), overridden_flags, created_at, updated_at, audit[]`. These stores
are what the domain pages visualise, so **approve → consequence is visible**.

### 2.2 Policy / checks engine

Deterministic CODE. **Flags with a reason; never auto-rejects — the human decides**
(CLAUDE.md §2). Each flag is `soft` (surface, human may override) or `hard` (blocks the
write even on approve). **Overridden flags are recorded** (RQ3 data). Per workflow:

- **WF3 expense** — 4 core rules (over-limit, budget/quota🗄, duplicate🗄,
  documentation-mismatch). Missing `business_purpose` = required-field detection, not a
  rule. (Trimmed from 9; padding rules removed 2026-07-01.)
- **WF3 leave** — leave-balance check🗄 + duration threshold.
- **WF2 scheduling** — conflict, room double-booking, room over-capacity, unknown
  participant, out-of-hours. (🗄 = requires a store.)

### 2.3 Extended org fixture (`backend/fixtures/org.py`)

Single source of truth; all fictional (`@example.com`). Extends today's people/rooms/
busy-slots with:

- **People + `department`** (alice=Product, bob=Engineering, chen=Finance, dana=People,
  evan=IT, fiona=Operations). *No `manager`/routing* — the user is the sole approver.
- **Rooms**: Orion(6) · Lyra(12) · Vega(3) *(unchanged)*.
- **Calendar seed**: `BUSY_SLOTS` *(unchanged)* → conflicts exist on day one.
- **Budgets** (dept × Q3-2026, partly spent): Engineering £5,000 (spent £1,200) · Product
  £3,000 (£600) · Finance £2,000 (£0) · others £2,000 each.
- **Quotas**: per-person annual expense quota £3,000; leave balance 25 days/yr (some used).
- **Policy config**: per-diem meals £50/day · accommodation £150/night · supplies £200 ·
  software £500 · other £100; high-value line £500; non-reimbursable {alcohol, personal,
  gifts}; late window 60 days; working hours 09:00–18:00; default meeting 30 min; leave
  duration flag > 10 days.
- **Seed records**: 2–3 pre-approved expense claims (one a duplicate-test target; consumes
  budget); a handful of seed inbox threads for the demo.

*(All numbers are placeholders — tune freely.)*

### 2.4 Approval gate + audit

One three-state gate for every workflow: **Approve / Edit / Reject**. It emits one audit /
`EvalRecord` per decision: `workflow, decision, extraction (raw), final record,
missing_fields, changed_fields (on edit), overridden_flags, reason (on reject),
timestamps`. This is the RQ3 data surface.

### 2.5 Models (RQ2 variable)

- **Text**: Groq `llama-3.3-70b-versatile` (primary) + a second model as comparison.
- **Vision** (WF3 receipts): a Groq vision model — Llama-3.3-70B is text-only.
- Judge for faithfulness/quality must differ from the generator (CLAUDE.md §4.5).

*(As built: the RQ2 comparison is Groq `openai/gpt-oss-120b`, not Claude — free and
cross-family. Vision migrated Llama 4 Scout → `qwen/qwen3.6-27b` when Groq retired
Scout on 2026-07-17; both models' results are in `results.md` §2.7.)*

### 2.6 Content-generation feature (absorbs old WF4)

Not a workflow. On **approve/reject** in any workflow, the system can **auto-draft the
note/confirmation (approve) or the reason (reject)**, generated **from the actual record +
flags** (so it is grounded, not commodity prose). `store_draft` semantics only — nothing
is sent. Faithfulness evaluation still applies to these grounded drafts.

---

## 3. The three workflows (contract summary → deep spec)

### WF1 — Triage / Intake · Inbox · → [wf1_triage_design.md](wf1_triage_design.md)
Read a multi-party thread → detect **actionable intents** (list; multi-action) → route.
Targets: `schedule_meeting`→WF2, `leave_request`→WF3-leave; generic to-dos = annotations;
FYI → Archive. **Expense never via triage** (needs an image). Gate is per-action
Route/Dismiss + thread Archive. **Hand-off rule:** a routed action passes `seed_fields` to
the downstream, which does **not** re-extract. Summary is demoted to context.

### WF2 — Scheduling · Calendar · → [wf2_scheduling_design.md](wf2_scheduling_design.md)
Slots (LLM) → CODE resolves dates, looks up participants, checks conflicts against the
**stateful** calendar (participants **and** room) + scheduling checks → book. Approve →
persistent event + slot occupied + in-app notification + **real `.ics` file**. Two entries
(routed / direct); one meeting per invocation.
The current interactive configuration additionally synchronises approved lifecycle changes
through the Google Calendar API; formal evaluation injects a mock backend.

### WF3 — Expense (multimodal) + Leave (text) · Requests · → [wf3_expense_design.md](wf3_expense_design.md)
**Expense**: receipt **image** → vision-LLM extract (with per-field confidence) → prefill
form → policy rules → human verifies **against the original image** → write to
`submissions` + decrement budget. **Leave** reuses the whole pipeline with text extraction
+ leave-balance/duration checks. Flagship of the multimodal claim.

---

## 4. Cross-workflow flows

- **Routing (WF1 → WF2/WF3):** approved routing creates a pending draft in the target
  domain, carrying `seed_fields` and an `origin` back-link; the downstream runs only
  validate+complete (no re-extract). Re-routing a routed action is blocked.
- **Two entry patterns:** reactive (Inbox → triage → route) and direct (upload a receipt
  in Expenses; type a request in Calendar).
- **Consequence visibility:** decide in one domain → the effect appears in the target
  domain (pending meeting in Calendar; approved claim + budget drop in Expenses).

---

## 5. Frontend

Business-domain nav (📥 Inbox · 📅 Calendar · 🧾 Expenses · 📊 Overview · ◎ Audit), not
workflow names. The UI **surfaces the workings**: confidence highlights, source spans,
provenance tags, policy flags, pipeline stage and state badges. Maintained frontend
operating notes live in `frontend-next/README.md`.

---

## 6. Data

Primary = **controllable synthetic generation** (reverse generation; **LLM realiser**;
difficulty tiers per workflow, incl. `conflict` for WF2 and `policy-violating`/`non-receipt`
for WF3; label-by-construction; back-check). Adopt a robust date library (`dateparser`) so
the realiser can use rich date phrases. External validity (added later): **AMI/QMSum**
(WF1 action-items), **SGD** (WF2/WF3 slots), **SROIE/CORD** (WF3 receipts). Detail +
receipt-image track: [data_strategy.md](data_strategy.md).

---

## 7. Evaluation (deferred — direction only)

approve/reject alone is meaningless; cross-reference against **ground truth** (gold for
WF2/WF3 structured fields) or a **faithfulness judge** (generative outputs) →
**false-accept / false-reject** are the real HITL metrics. Judge = inline decision support
+ offline metric; judge ≠ generator; validate with Cohen's κ. Detail:
[evaluation.md](evaluation.md).

---

## 8. WF5 — Daily Briefing (optional, proactive, last)

Kept as an optional, architecturally-separate demonstration of the **proactive trigger
model** (scheduled crawl of public news → classify → summarise → review). Build only after
the three core workflows are solid; do not let its crawling stack distract from the core.

---

## 9. Research-question mapping

- **RQ1** — transform unstructured comms (text **and image**) into structured,
  policy-checked drafts → schema-validity + extraction correctness.
- **RQ2** — accuracy/reliability across tasks (scheduling, multimodal expense) + **model
  comparison** (historical Llama/scout baselines vs current GPT-OSS/Qwen models).
- **RQ3** — HITL effect → false-accept/reject vs ground truth, overridden-flag behaviour,
  edit distance, correct-refusal (Archive/abstain), usability.

---

## 10. Constraints recap (CLAUDE.md §2/§3)

Agent proposes, human decides, code executes · synthetic task data only · WF1/WF3 local
side effects · WF2 provider sync only after approval and only to dedicated project calendars
· evaluation structurally pinned to reproducible mock stores · the approval gate is never
bypassed.
