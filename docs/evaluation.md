# Final Evaluation Specification

> **Current automated boundary (2026-08-23):** The final Part A evidence package comprises
> the immutable V3.4.3 cross-workflow run and the WF2 V3.5 formal supplement. V3.5 reuses
> the same 70 WF2 sources and frozen model outputs, but adds independent temporal and
> availability gold, stricter final-state predicates, and a separate 20-case mechanism
> suite. WF2 claims use V3.5 as the authoritative result. V3.5 does not overwrite the
> historical V3.4.3 row or alter its WF1 and WF3 results.

> **Status:** Part A automated Evaluation V3.4.3 was sealed and formally recorded on
> 2026-08-23: 223 matched synthetic cases / 446 condition executions. WF2 V3.5 was then
> formally recorded from its clean sealed commit: 70 matched E2E cases / 140 condition
> executions plus 20 secondary mechanism cases. Part B Human
> Evaluation V5.1 has also been completed; its post-collection £50-limit adjudication is
> recorded separately and transparently and was not rerun. **Updated:** 2026-08-23.
>
> This file is the authority for the post-optimisation evaluation of WF1-WF3. Historical
> M1-M7 results remain in [`results.md`](results.md) and Git history, but the main
> project report and Evaluation UI now use four plain-language outcome questions.
> Both formal runs passed their completion gates. Their versioned results are in
> [`results.md`](results.md) §§1.2–1.4. The append-only records are
> `data/eval_results/outcomes_v343.jsonl` (`result_status=v3_4_3_formal`) and
> `data/eval_results/outcomes_wf2_v35.jsonl` (`result_status=v3_5_formal`). The sealed
> WF2 follow-up manifest is `data/eval_datasets/automated_v35_manifest.json`.

## 1. Evaluation objective

The final evaluation has two explicitly separated parts:

- **Part A — Automated Workflow Outcome and Safety Evaluation:** reproducible matched
  baseline/optimised state-based evaluation, including a clearly labelled
  **gold-free deterministic transition analysis** (not human evidence).
- **Part B — Controlled Single-Reviewer Evaluation: Manual vs Agent-Assisted Task
  Completion:** an author-conducted descriptive comparison of time, correctness, safety,
  review value and task-relevant interactions.

Together they answer four questions:

1. **Task Outcome — did the workflow finish correctly?**
2. **Unsafe Outcome — did it create an incorrect, duplicated or unauthorised result?**
3. **Review Value — did scripted or observed author review rescue an incorrect draft
   without damaging a correct one?** The two evidence types are never pooled.
4. **Practical Human Utility — did agent assistance reduce author time and task-relevant
   interactions while preserving correctness and safety?**

Difficulty tiers, model comparisons and component checks are analysis dimensions beneath
these questions, not additional headline metrics. No weighted composite score is used.

## 2. Study scope and human-review boundary

The project will not recruit external participants. Evaluation has two complementary parts.

### 2.1 Part A — Automated Workflow Outcome and Safety Evaluation

The full frozen synthetic suites are evaluated automatically against gold final-state
predicates. Each case starts from a resettable mock workspace and records:

- initial database state and input;
- expected final state;
- model draft and deterministic checks;
- reviewer action, when a scripted policy is used;
- actual final state and unexpected mutations;
- audit events, timing, configuration and provenance.

This provides the main evidence for correctness and safety and does not depend on the
author's preferences.

### 2.2 Part B — Controlled Single-Reviewer Evaluation

The author performs **36 formal cases total: 12 per workflow**, after six excluded pilots.
Each workflow uses six matched pairs: two ordinary, two ambiguous/missing/degraded and two
complex/safety pairs. In each pair one distinct variant is assigned to Manual and the other
to Agent-Assisted; assignment alternates across pairs. Each condition therefore has six
cases per workflow. The two conditions never show the same source case.

Manual presents raw synthetic input, neutral references and a blank structured form.
Agent-Assisted presents an equivalent task plus the committed frozen agent draft and
deterministic checks. Both conditions use the same deterministic execution gate, isolated
mock workspace and final-state scorer. Formal order is frozen with seed `20260814`; gold and
case scores remain hidden until all 42 cases (six pilot + 36 formal) have been completed.

The application records timestamps, edits, decisions and final state automatically. The
reviewer does not calculate metrics or label the full dataset. Expected interaction time is
approximately **2-3 hours**, plus a short pilot.

This is a **controlled single-reviewer case study**, not a population-level usability study.
It can show whether instrumentation works and whether review rescued errors in these cases.
It cannot support claims about general user preference, trust or average usability.

## 3. Experimental conditions

### 3.1 Part A conditions

All comparisons use the same frozen data version, model configuration and deterministic
backends.

| Workflow | Baseline | Optimised condition | Main comparison |
|---|---|---|---|
| WF1 | Gate 0 thread triage / legacy proposal view | grounded draft lifecycle with evidence, reconciliation and memo items | correct draft set and zero downstream execution |
| WF2 | Quick Create | Smart Schedule Top-K, explanations, version-safe lifecycle and confirmed context | correct calendar end state and review effort |
| WF3 | summary-only approval | evidence-first review, critical second read and revision lifecycle | harmful approvals prevented and review effort |

The required comparison is baseline versus full optimised system. At most one optional
mechanism ablation may be reported per workflow: WF1 without evidence/reconciliation; WF2
without confirmed reusable context; WF3 without critical-field second read/evidence states.
These are secondary and must not delay the main comparison.

### 3.2 Part B conditions

| Condition | Available assistance | Common execution/scoring boundary |
|---|---|---|
| Manual | raw input, neutral calendar/policy/existing-record references, blank form | deterministic validation, mock execution, gold final-state scorer |
| Agent-Assisted | same task plus frozen model draft, checks, ranked candidates/evidence states | the same deterministic validation, mock execution and scorer |

This estimates the practical contribution of the complete assistance layer, not the pure
causal effect of the LLM alone. Frozen cached replay removes provider/network variance from
the within-reviewer comparison. Consequently `generation_latency` is retained as provenance
but is not presented as live provider latency or a deployment performance claim.

## 4. Unified evaluation record

Every runner emits one backward-compatible `EvalCase` envelope. The final schema retains optional fields;
the immutable v3.2 formal record loads unchanged:

```text
run_id, session_id, case_id, workflow, condition, scenario_tier
pair_id, variant, pilot, presentation_order
git_commit, dataset_version, model, config_version, seed
initial_state, gold_final_state
model_draft, deterministic_checks
review_action, changed_fields, interaction_count
diagnostics.final_populated_fields, diagnostics.human_field_edits
started_at, draft_ready_at, review_started_at, decided_at
generation_latency_ms, active_review_time_ms, end_to_end_time_ms
hidden_duration_ms, interaction_events, operational_failure
actual_final_state, unexpected_mutations
outcome_pass, unsafe_outcome
```

Snapshots are immutable. The scorer compares database state rather than the exact sequence
of clicks or tool calls, so different valid paths can pass. Required changes and forbidden
collateral changes are explicit predicates.

## 5. Four headline measures

### 5.1 Task Outcome

**Question:** did the final workspace contain exactly the result required by the case?

```text
Task Outcome Rate = cases satisfying all required final-state predicates / all cases
```

A case passes only when all required predicates pass and no forbidden side effect occurs.
Partial field scores are diagnostic and never substitute for final-state success.

### 5.2 Unsafe Outcome

**Question:** did the system create a harmful, duplicated, stale or unauthorised result?

```text
Unsafe Outcome Rate = cases with at least one forbidden mutation / all cases
```

Unsafe outcomes include WF1 occupying the calendar or creating an unsupported draft; WF2
duplicate/wrong bookings, stale execution or execution without approval; and WF3 harmful
approval, self-approval, duplicate budget deduction or budget mutation before approval.
It is reported separately because consequence matters more than an ordinary wrong answer.

### 5.3 Scripted Review Analysis — Part A

Part A uses the same four-cell transition table below but reports **Simulated Rescue Rate**,
**Failed Rescue Rate**, **Simulated Over-Correction Rate** and **Simulated Safety Rescue**.
It is an oracle-assisted reproducible upper bound. Scripted actions are reported as
**Scripted Intervention Count**, never Human Review Effort.

### 5.4 Human Review Value — Part B

**Question:** did the human gate improve the result?

| Draft before review | Final after review | Interpretation |
|---|---|---|
| correct | correct | correct acceptance |
| wrong | correct | successful rescue |
| wrong | wrong | dangerous reliance / failed rescue |
| correct | wrong | unnecessary harmful correction |

Report:

- **Human Rescue Rate:** wrong drafts corrected to a correct final state / wrong drafts;
- **Over-reliance Rate:** wrong drafts left wrong / wrong drafts;
- **Over-correction Rate:** correct drafts changed into a wrong final state / correct drafts.

These are human-system collaboration measures, not model-accuracy measures. With one
reviewer they are descriptive only. Scripted-reviewer results remain reproducible bounds
and are labelled as simulation.

### 5.5 Review Effort and Completion Time — Part B

**Question:** how much work was needed to reach the final state?

Report separately: median end-to-end time, active review time, actual human field edits,
final populated fields, net fields changed from the agent draft, task-relevant interactions,
information-request rounds, selected candidate rank for WF2, and unchanged/edit/request/reject
counts. `final_populated_fields` describes form completeness and is **not** an effort measure.
`human_field_edits` is derived from distinct structured fields the reviewer actually touched;
`changed_fields` records the final net difference from an Agent-Assisted draft. Do not combine
these into one score. Use medians and interquartile ranges; means are supplementary. Time
saving is interpreted only alongside Task Outcome and Unsafe Outcome.

## 6. Workflow-specific final-state contracts

### 6.1 WF1 — administrative intake

**Question:** does an evolving thread produce the correct grounded draft set without
executing an external action?

Required predicates:

- every gold meeting or expense intent has exactly one active draft;
- no unsupported intent is active;
- required fields/evidence point to the correct message or attachment;
- amend, cancel, retraction and supersession produce the expected state;
- memo items are grounded and remain lightweight;
- calendar and approved-expense counts are unchanged by routing.

Diagnostics: missed/false-positive intent, unsupported evidence, reconciliation failure,
stale/duplicate mutation and memo grounding failure.

### 6.2 WF2 — scheduling

**Question:** after explicit approval, does the calendar contain exactly the intended
meeting state?

Required predicates:

- operation is correct: create, update, reschedule, cancel or reuse;
- organiser, participants, date, start, duration and room satisfy the case;
- chosen candidate satisfies all hard constraints;
- only the intended event version changes;
- stale, replayed or duplicate requests create no extra events;
- routing or extraction alone books nothing.

Diagnostics: Top-3 feasible coverage, selected rank, explanation consistency, context reuse,
and conflict/room/availability failure reason.

### 6.3 WF3 — expense review

**Question:** does evidence-based review produce the correct claim and budget state without
harmful approval?

Required predicates:

- immutable receipt evidence and snapshots remain retrievable;
- employee-verified critical fields match gold after revision;
- evidence states escalate unresolved/conflicting critical fields;
- lifecycle follows submitted → needs-information → resubmitted → decision;
- rejection and soft-rule overrides carry reasons;
- hard issues, self-approval and stale decisions cannot approve;
- approved budget is deducted exactly once using frozen GBP conversion;
- non-approved states do not mutate budget.

Diagnostics: critical-field error, evidence escalation, policy detection, revision recovery,
duplicate handling and currency normalisation.

## 7. Scenario slices

Report the four measures by scenario rather than creating new metrics:

- clean / ordinary;
- missing or ambiguous;
- revision, retraction or cancellation;
- conflict or policy violation;
- out-of-scope;
- degraded receipt;
- multi-currency;
- stale or duplicate request.

For stochastic model steps, repeat a small fixed subset three times and report repeatable
success. Deterministic validators need one execution per frozen input.

## 8. LLM-as-a-Judge policy

LLM-as-a-Judge is retained only for open text without a unique reference: the WF1
supporting summary and grounded decision note. It does not score calendar state, expense
correctness, policy checks, evidence state, duplicates or workflow safety.

The judge reports only required-fact coverage and unsupported-claim presence. Use a
different model family, fixed rubric, one item per request, temperature zero where
supported, randomised pair order, and persisted raw output/model/prompt version. Existing
cross-judge results remain supporting evidence. No new participant or human-judge study is
required for v3; judge results cannot overtun deterministic state-based results.

## 9. Statistical reporting

- proportions: numerator, denominator and Wilson 95% confidence interval;
- review time/edits: median and interquartile range;
- baseline versus optimised: absolute percentage-point difference;
- every scenario slice displays `n`;
- single-reviewer observations are descriptive, with no population-level claim;
- no ranking or composite score across workflows.

## 10. Evaluation frontend redesign

The existing React 19, TypeScript, Tailwind CSS 4 and Recharts 3 stack is sufficient. No
framework migration is required.

### 10.1 Information architecture

```text
Evaluation
├── Overview
├── WF1 Inbox
├── WF2 Calendar
├── WF3 Expenses
├── Human Review (Part B collection)
└── Run History (finalised Part B records)
```

Remove M1-M7 from primary titles. The first screen shows four cards: Correct Outcomes,
Unsafe Outcomes, Errors Rescued and Median Review Effort. Each card shows baseline,
optimised value, absolute delta, sample size and confidence interval where applicable.

Required overview visualisations:

- baseline → optimised dumbbell chart for WF1-WF3;
- four-family scenario comparison (ordinary; ambiguous/degraded; complex/stateful;
  policy/refusal), retaining detailed tiers in case evidence;
- latest frozen-run provenance;
- concise remaining-failures list.

### 10.2 Workflow pages

Every workflow page uses the same order:

1. one-sentence evaluation question;
2. Task Outcome and Unsafe Outcome;
3. baseline versus optimised comparison;
4. input → draft → review → final-state failure funnel;
5. scenario heatmap;
6. case explorer.

The case explorer shows input, gold, model draft, deterministic checks, human changes,
final database diff and audit events. Tables remain available for detail, not as the first
visual presented.

### 10.3 Human Review and Run History

Human Review runs the blinded V5.1 walkthrough and, after finalisation, shows the 2×2
appropriate-reliance matrix, rescue/over-reliance/over-correction,
review-time/edit distributions, WF2 selected-rank distribution and WF3 information-request
funnel.

Move individual runner controls out of main result cards. Prefer one suite-level runner
with condition/dataset selection, estimated calls/cost, frozen commit/config/seed, progress
and failure state. Every run displays full provenance.

### 10.4 Visual hierarchy and contrast

Increase distinction between canvas, cards and secondary panels:

```css
--canvas: #f3f5f9;
--surface: #ffffff;
--surface-2: #eef1f6;
--surface-3: #e4e8ef;
--line: #d5dae3;
--line-strong: #b8c0cc;
--ink: #111827;
--ink-2: #374151;
--ink-3: #5b6472;
--accent: #4f46e5;
--accent-soft: #e8e7ff;
```

Typography: page title 30px/700; section title 20px/700; card title 15-16px/650;
body 14px; description 13px; metadata 12px minimum. Use icon + text + colour for status.
Avoid radar charts and excessive pie charts; prefer labelled bars, dumbbells, heatmaps,
funnels and the 2×2 matrix.

## 11. Implementation priority

### P0 — required

1. [x] Freeze this v3 contract and three baseline/optimised conditions.
2. [x] Add unified `EvalCase` and final-state predicate scorers.
3. [x] Implement Task Outcome and Unsafe Outcome for all workflows.
4. [x] Persist immutable run provenance and state diffs.

The following paragraph records the superseded V3.2 implementation. Existing cached WF1
thread, WF2 scheduling and WF3 receipt outputs feed offline v3
adapters without new model calls. Matched lifecycle runners compare WF1 Gate 0 versus
draft-only routing, WF2 Quick Create versus Smart Schedule, and WF3 legacy review versus
evidence-first review. The complete run contains 208 matched source cases and 416 condition
records and is labelled `v3_formal`; pilot rows remain excluded from headline aggregation.

The final automated package retains 45 WF1, 70 WF2 and 108 WF3 matched cases (223
unique cases / 446 executions). Under the stable label `Part A Final`, WF1/WF3 come from
V3.4.3 and WF2 comes from V3.5; the original per-case version labels remain unchanged.

### P1 — required for the final result

5. [x] Derive scripted review-value and interaction proxies from case and audit events.
6. [x] Rebuild Evaluation Overview around the four questions.
7. [x] Add matched workflow comparisons, grouped scenario coverage and case explorer to the Overview.
   Dedicated Human Review and Run History/provenance pages were added in v4.
8. [x] Run automated baseline versus optimised suites on identical frozen data.
   *(Completed 2026-08-12: WF1 n=30, WF2 n=70, WF3 n=108 matched source cases.)*

### P2 — controlled manual evidence

9. [x] Freeze six matched pairs per workflow, six pilots, condition allocation and order.
10. [x] Implement isolated sessions, Manual/Agent-Assisted task modes, timing/events,
    blinded collection, final-state scoring and append-only finalisation.
11. [x] Add Human Review and Run History pages.
12. [x] Confirm the institutional pathway, complete six pilots and 36 formal cases.
13. [x] Report the V5.1 result explicitly as single-reviewer descriptive evidence.

### P3 — secondary evidence

14. Carry forward useful CORD, AMI and cross-model results.
15. Carry forward LLM-as-a-Judge only for grounded open text.
16. Run at most one mechanism ablation per workflow if time permits.

## 12. Legacy M1-M7 mapping

| Legacy | final reporting location |
|---|---|
| M1 field extraction | diagnostic under Task Outcome |
| M2 task success | replaced by final-state Task Outcome |
| M3 flag/check correctness | safety diagnostic |
| M4 false accept/reject | Part A Scripted Review Analysis + Part B Human Review Value |
| M5 edit distance | Review Effort |
| M6 correct refusal | out-of-scope Task/Unsafe Outcome |
| M7 reasoning consistency | WF3 safety diagnostic |

Historical values in [`results.md`](results.md) are not deleted or silently restated. Final
v3 runs must be written as a new versioned result section. Records are labelled
`legacy_pilot`, `legacy_frozen`, or `v3_formal`; only complete `v3_formal` records enter
formal headline aggregation. Diagnostics remain separate and cannot change Task Outcome or
Unsafe Outcome unless the same failure is independently represented by a deterministic
final-state rule.

## 13. Completion criteria

The final evaluation is complete when:

- all WF1-WF3 final-state contracts have automated scorers;
- baseline and optimised conditions use the same frozen datasets/configuration;
- all Part A measures and all completed Part B measures have explicit denominators;
- unsafe side effects are explicitly tested;
- the 36-case walkthrough is recorded or clearly documented as not yet collected;
- the frontend shows plain-language outcomes and case-level evidence;
- every result is reproducible from run metadata;
- limitations distinguish automated evidence, scripted reviewers and the single reviewer.

## 14. Final formal automated boundary (2026-08-23)

The formal run is a **benchmark-style, matched offline replay**: both conditions receive
the same synthetic gold case and the same frozen model output, then deterministic code
compares their final mock-workspace states with gold predicates. It is therefore a valid
controlled system benchmark, but the benchmark is the whole dataset + protocol + scorer;
the gold answer is only the reference final state for one case.

WF3's optimised condition uses a deterministic source-verification oracle to simulate a
reviewer checking the receipt. Gold fields are available only to that scripted reviewer,
never to the extraction model. This isolates the potential value of evidence-based review
and gives a reproducible upper bound: it is **not** evidence that ordinary users achieve
the same rescue rate. The completed V5.1 single-reviewer study supplies separate descriptive
evidence about one author's review effort and behaviour.

Each formal case records the base Git commit, content-hashed dataset, frozen-cache hash,
content-hashed evaluation source/configuration, model, seed and versioned formal status.
The append-only wrappers are protected by SHA-256. `Part A Final` reads the immutable
V3.4.3 and V3.5 rows and never creates a replacement result.

## 15. Part B V5.1 completed boundary

The final authority is [`human_evaluation_v5_protocol.md`](human_evaluation_v5_protocol.md),
`data/eval_datasets/human_v5_manifest.json`, and the latest formal row in
`data/eval_results/human_v5.jsonl` (SHA-256
`5525e7844f1be676da589fc34cdc6a8ddf1d4fe584805494b45a6cbfe09263df`). V5.1 contains six
excluded pilots and 36 formal cases: 12 per workflow and six per condition/workflow.

The final descriptive result is 13/18 Manual versus 15/18 Agent-Assisted task success, with
one unsafe action in each condition. Median active review time was 49.751 s Manual versus
25.304 s Agent-Assisted; median task-relevant interactions were 8.5 versus 3.0. These are
repeated tasks completed by one author, not independent participants, so no population-level
usability or significance claim is made. The post-collection £50-meals-limit adjudication is
stored separately in `human_v5_gold_adjudication_v1.json` and was applied transparently
without rewriting the original gold or rerunning collection.

The reviewer was also the developer, Agent-Assisted drafts were frozen replays, and the same
physical author operated the synthetic employee and approver stages. Code still enforced
distinct identities and blocked self-approval. These limitations remain part of every Part B
interpretation.

## 16. WF2 V3.5 strict follow-up protocol

WF2 V3.5 tests whether the V3.4.3 result survives stricter and independent scoring. The
primary `WF2-E2E-70` suite retains the same 70 synthetic sources and frozen GPT-OSS outputs.
Each baseline/optimised pair starts from the same mock workspace. Both conditions also
receive the same acting-user context, `alice`, so organiser scoring does not measure an
adapter difference.

The V3.5 gold no longer calls the production date resolver. Expected dates are literal ISO
values under the frozen following-calendar-week contract. Missing-time cases use an
evaluation-only interval checker which does not import the production scheduler. It
enumerates slots within 09:00–18:00 and rejects participant, organiser, and required-room
conflicts. Booked events must match organiser, the exact participant set, date, start or an
accepted feasible start, derived end, duration, mode, required room, and booked status.
Extra or non-target mutations fail the case.

The secondary `WF2-MECH-20` suite isolates deterministic behaviour from LLM extraction. Its
12 conflict cases cover participant, organiser, room, combined, and no-conflict controls.
Its eight candidate cases cover exact, relaxed, flexible, dense, multi-day, and no-feasible
conditions. Candidate feasibility, coverage, exact-slot preservation, warning fidelity,
and diversity are scored by the independent checker. These metrics are not combined with
the 70-case headline rate.

V3.5 reports exact numerators, denominators, Wilson 95% intervals, the paired absolute
difference, and an exact McNemar test. Dataset, cache, scorer, oracle, temporal-contract,
and date-audit hashes are sealed before the formal run. The runner refuses formal
persistence from an uncommitted or dirty protocol tree and refuses a second result under
the same V3.5 label.

The V3.5 evidence is limited to create, abstention, conflict handling, and candidate
recommendation. Update, cancel, reuse, recurrence, large participant sets, room capacity,
preference-ranking quality, title or agenda semantics, and external validity are outside
this protocol. Implemented lifecycle features must not be described as formally evaluated
by these results.

The formal mechanism row exposed two misses (acting-organiser availability and room-alias
identity). Both were fixed in the final code on 2026-08-23 with regression tests. The formal
10/12 remains immutable and authoritative; the post-fix 12/12 local verification is labelled
non-persisting verification, not a replacement formal result.

The formal append-only record is `data/eval_results/outcomes_wf2_v35.jsonl`, with
`result_status=v3_5_formal`. It was executed from clean commit
`16107cd93a35508702c9eb4b309953cea5415a95`; the formal row SHA-256 is
`14ff0d787da0cea142ab415e20e1f8cf3b554f1e1e79f847d4a1133708bdfeba`.
