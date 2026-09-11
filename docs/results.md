# Final evaluation results

This page contains the current evidence boundary only. Superseded result narratives and
intermediate experiment logs have been removed to prevent an old number from being mistaken
for the final result. Metric definitions are in [`evaluation.md`](evaluation.md).

## Authoritative evidence

| Evidence | Frozen source | Scope |
|---|---|---|
| WF1 automated | V3.4.3 formal row | 45 matched cases, 90 executions |
| WF2 automated | V3.5 formal row | 70 matched cases, 140 executions; 20 mechanism cases |
| WF3 automated | V3.4.3 formal row | 108 matched cases, 216 executions |
| Human review | V5.1 formal row | one reviewer, 36 formal cases; 6 pilots excluded |

`Part A Final` is an explicit mapping: WF1 and WF3 use the immutable V3.4.3 result, while
WF2 uses the stricter V3.5 follow-up. It does not imply that every workflow was scored by one
protocol version.

## Automated matched comparison

Each case is run once through the baseline and once through the controlled workflow. A pair
shares the same source, frozen model output, initial state and gold final state.

| Workflow | Condition | n | Task outcome, Wilson 95% CI | Unsafe outcome, Wilson 95% CI |
|---|---|---:|---:|---:|
| WF1 | Gate 0 baseline | 45 | 21/45 = **0.467** [0.329, 0.609] | 18/45 = **0.400** [0.270, 0.545] |
| WF1 | Draft-only controlled | 45 | 39/45 = **0.867** [0.738, 0.937] | 3/45 = **0.067** [0.023, 0.179] |
| WF2 | Quick Create baseline | 70 | 49/70 = **0.700** [0.585, 0.795] | 11/70 = **0.157** [0.090, 0.260] |
| WF2 | Smart Schedule controlled | 70 | 70/70 = **1.000** [0.948, 1.000] | 0/70 = **0.000** [0.000, 0.052] |
| WF3 | Legacy review baseline | 108 | 76/108 = **0.704** [0.612, 0.782] | 9/108 = **0.083** [0.044, 0.151] |
| WF3 | Evidence-first controlled | 108 | 96/108 = **0.889** [0.816, 0.935] | 4/108 = **0.037** [0.014, 0.091] |

The controlled conditions improve task outcome by 40.0 percentage points for WF1, 30.0
points for WF2 and 18.5 points for WF3 on this fixed suite. Unsafe outcome decreases by
33.3, 15.7 and 4.6 points respectively.

The WF2 V3.5 paired Task Outcome difference is 0.300. There are 21 baseline-fail and
controlled-pass pairs, with no pairs changing in the opposite direction (two-sided exact
McNemar `p=0.00000095`). The 70 controlled successes comprise 40 correct bookings and 30
correct abstentions or no-mutation outcomes. They are not 70 meetings created.

## WF2 mechanism follow-up

The independent 20-case mechanism suite is secondary evidence and is not pooled into the
end-to-end headline.

| Measure | Result, Wilson 95% CI |
|---|---:|
| Conflict-type accuracy | 10/12 = **0.833** [0.552, 0.953] |
| Participant or organiser conflict recall | 5/6 = **0.833** [0.436, 0.970] |
| Room-conflict recall | 5/6 = **0.833** [0.436, 0.970] |
| Feasible candidate rate | 17/17 = **1.000** [0.816, 1.000] |
| Coverage@3 for eligible cases | 7/7 = **1.000** [0.646, 1.000] |

The two misses exposed an omitted organiser check and inconsistent room aliases. Both were
fixed after the formal row was frozen, with regression tests added. The immutable formal
score remains 10/12; it has not been silently replaced by a replay on repaired code.

The temporal audit also records that an earlier WF2 score change came from correcting the
meaning of “next weekday”, not from a model improvement. See
`data/eval_datasets/wf2_date_contract_audit_v35.json`.

## Controlled human review

The completed V5.1 study used one reviewer and 36 formal cases after six excluded pilots.
Results are descriptive and do not estimate population-level usability.

| Condition | Task success | Unsafe actions | Decision correct | Median active time | Median interactions |
|---|---:|---:|---:|---:|---:|
| Manual | 13/18 = **0.722** | 1/18 = **0.056** | 16/18 = **0.889** | **49.751 s** | **8.5** |
| Agent-assisted | 15/18 = **0.833** | 1/18 = **0.056** | 15/18 = **0.833** | **25.304 s** | **3.0** |

Agent assistance was associated with two additional successful outcomes and lower median
time and interaction count in this single-reviewer task set. It did not improve aggregate
decision correctness or change the unsafe-action count. Collection details and the
post-collection adjudication are disclosed in
[`human_evaluation_v5_protocol.md`](human_evaluation_v5_protocol.md).

## What the evaluation found

- WF1 risk concentrates in ambiguous-intent over-detection and failure to abstain.
- WF2 deterministic validation removes unsafe booking outcomes on the sealed synthetic set,
  but the mechanism study found edge cases in organiser and room conflict handling.
- WF3 remains sensitive to degraded and unfamiliar receipt images. Policy code cannot repair
  a field that the model read incorrectly unless the discrepancy is exposed to the reviewer.
- Human review creates value only when the reviewer checks source evidence; a ceremonial
  approval click is not a safety mechanism.

## Reproduce the final evidence

No API key or calendar credentials are required:

```bash
PYTHONPATH=. .venv/bin/python -m backend.scripts.materialize_evaluation_receipts
PYTHONPATH=. .venv/bin/python -m backend.evals.final_part_a
```

Expected controlled counts:

```text
WF1  39 / 45 task outcomes, 3 / 45 unsafe outcomes
WF2  70 / 70 task outcomes, 0 / 70 unsafe outcomes
WF3  96 / 108 task outcomes, 4 / 108 unsafe outcomes
```

Frozen records:

- `data/eval_results/outcomes_v343.jsonl`
- `data/eval_results/outcomes_wf2_v35.jsonl`
- `data/eval_results/human_v5.jsonl`
- `data/eval_datasets/automated_v343_manifest.json`
- `data/eval_datasets/automated_v35_manifest.json`
- `data/eval_datasets/human_v5_manifest.json`

## Limitations

- The automated headline uses controlled synthetic cases and frozen hosted-model outputs.
- The human study has one reviewer; its time and interaction results are descriptive.
- The suite does not establish reliability on real company mail, calendars or claims.
- Live reruns can differ when hosted models, APIs or provider behaviour change.
- Authentication, multi-tenant isolation, deployment hardening and enterprise compliance are
  outside the prototype's scope.

The repository therefore supports a bounded claim: deterministic controls and evidence-aware
review improved outcomes on the declared suites. It does not support a claim of production
readiness or universal reliability.
