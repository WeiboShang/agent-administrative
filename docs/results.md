# Final Evaluation Results

> **Authority (2026-08-23):** use the stable label **Part A Final**. WF1 and WF3 use the
> immutable V3.4.3 formal cross-workflow row; WF2 uses the stricter V3.5 formal row. Part B
> uses the latest completed Human Evaluation V5.1 formal row. Older version sections are
> retained only as labelled provenance and must not be quoted as current results.
> Metric definitions: [`evaluation.md`](evaluation.md). Data design: [`data_strategy.md`](data_strategy.md).
> All numbers were produced by the in-repo harnesses on reproducible synthetic data
> (label-by-construction) plus one external dataset (CORD); reruns: §6.
> Generators: Groq `llama-3.3-70b-versatile` + `openai/gpt-oss-120b` (text, WF1/WF2/O4) ·
> vision (WF3) = `qwen/qwen3.6-27b` since the 2026-07-16 migration; the `llama-4-scout`
> numbers below were collected **before its retirement** and are kept as the frozen
> pre-migration record (comparison: §2.7). Judges: Gemini 2.5 Flash (cross-family, **20 req/day** free cap,
> measured 2026-07-27) · gpt-oss-120b (OpenAI family, ~1000/day) — the two agree at
> κ=0.608 (§2.2b). **All faithfulness numbers are unbatched**: batching the judge
> halves the unsupported-claim rate (§2.2b). **Data conditions:** `template` (rule realiser)
> vs `realised` (Qwen-paraphrased prose, back-checked, **regenerated 2026-07-10** after
> rejecting meta-output rewrites — see §4). **Collection dates: 2026-07-13/14 (final,
> current gold)**; earlier runs superseded where noted. Wilson 95% CIs on headline
> proportions; n=5–18 cells are directional.

## 1. Authoritative final evidence

| Evidence | Authoritative source | Scope |
|---|---|---|
| WF1 automated | V3.4.3 formal row | 45 matched cases / 90 executions |
| WF2 automated | V3.5 formal row | 70 matched E2E cases / 140 executions + 20 mechanism cases |
| WF3 automated | V3.4.3 formal row | 108 matched cases / 216 executions |
| Human review | V5.1 latest formal row | one reviewer, 36 formal cases + 6 excluded pilots |

`Part A Final` is a code/UI/report alias for this mapping. It does not rename the immutable
rows or imply that all workflows were scored by one protocol version.

### 1.1 Supporting diagnostic table — where each workflow breaks

| Workflow | Component stressed | Saturated (=1.00) | **Discriminating result** | Metric |
|---|---|---|---|---|
| WF1 triage | **ambiguity / abstention** | detection recall + exact — all action tiers, both models, both data conditions (cleaned realised set) | **ambiguous-social refusal 0.40 [0.12,0.77] on BOTH models** (over-detects meetings from borderline chat); **on REAL transcripts (AMI, n=20) abstention 0.90 — but both failures are a new error mode the synthetic set cannot produce** (§2.8) | M6 |
| **WF1 abstention (minimal pairs)** | **which cue the model actually uses** | act (T+) 1.00 on all four δ | **abstain 0.00 on `time_specificity` and `hypothetical_vs_actual`; 0.17 on `third_party_vs_self`** — a +100pt act-over-abstain gap where AgentAbstain reports ~21 across frontier models (§2.1b) | paired acc. · CAR |
| **WF1 retraction** | discourse-level consistency | near 1.00 | far 0.83 [0.44,0.97]; `check_retraction` recovers the miss at **0.00 false positives** (§2.1c) | net caught |
| WF1 summary | information selection · judge choice | coverage 1.00 under the constrained prompt (ablation: 0.20–0.43 loose → 1.00) | **faithfulness 0.85, unsupported-claim rate 0.47 (Gemini judge, n=15)** vs 0.95/0.25 under the same-family judge — cross-family judge is stricter | coverage · faithfulness |
| WF2 scheduling | (nearly saturated) | everything, both models, both conditions — incl. stateful conflicts, never-invent, revision *time* tracking | llama drops the **organiser** from participants ~1/10 (0.90 [0.60,0.98]); llama realised abstention 0.90; gpt-oss = 1.00 everywhere | M1 |
| WF3 expense | **vision robustness** ← the strongest axis | clean/skewed/faint all fields 1.00 (n=18/tier) | **low_res date 0.44 [0.25,0.66]** (systematic 2026→2020 blur misread); cropped 0.89–0.94; **CORD real receipts 0.82 [0.68,0.91] (final, n=40)** | M1 × tier |
| WF3 policy | rules engine | over-limit 6/6 · duplicate 3/3 · non-receipt refusal 9/9 | auto-approve error rate **0.131** | M3 · M6 |
| **WF3 reasoning** | cross-field consistency | code detection 1.00 (12/12 gold · 11/11 on the model's own extraction) | **the model reads fields at 0.92 yet flags the contradiction 0/12 — in 11/11 cases it is inside its own output** (§2.4b) | M7 |
| **Task success (M2)** | the record, not the extraction | WF2 0.975 · abstains 30/30 where gold says don't book | **WF3 0.879; harmful-record rate WF3 0.083 vs WF2 0.014** — per-field means overstate it (cropped: no field below 0.72, only 0.72 of *records* right) (§2.4c) | M2 |
| **O4 content** | grounded generation | **fact coverage 1.00** (n=8 — decision/amount/vendor/date/reason all present) | faithfulness 0.78 w/ unsupported 1.00 under strict claim decomposition — driven by boilerplate courtesy sentences, not fact errors; no further judge run is in the final evidence | coverage · faithfulness |
| **RQ3 gate (M4)** | value of the human check | — | **blind FA 0.40 [0.34,0.47] · flag-following 0.39 (catches 2.5%) · ideal 0.00 (catches 100% at 0.4 edits/case)** | M4 |

**Corrected cross-workflow narrative:** with clean gold and clean realised data, the text
workflows are *near-saturated* — the LLM half of WF1/WF2 is not where the risk lives. The
risk concentrates in (a) **perception** (WF3 image degradation and real-world formats),
(b) **abstention** (WF1 ambiguous over-detection, both models), and (c) **judgement about
people** (llama's occasional organiser drop). The uniform human gate covers all three,
and M4 quantifies that the human's *verify-against-source* step — not the rules — is what
stops field-level errors.

### 1.2 WF2 Evaluation V3.5 — final formal WF2 result (2026-08-23)

WF2 V3.5 checks whether the 70/70 result survives a stricter, independently authored
contract. It preserves the 70 V3.4.3 sources and frozen GPT-OSS outputs. The scorer now
requires the organiser, exact participant set, date, derived end, duration, mode, required
room, booked status, and no extra mutation. Missing-time cases must use a slot accepted by
an evaluation-only availability checker. The date gold is stored as literal ISO values and
the checker imports neither the production date resolver nor the production recommender.

The formal replay produced the following primary results from the clean sealed protocol
commit. This V3.5 row is the authoritative WF2 result in the final Part A evidence package;
V3.4.3 remains the immutable cross-workflow row for WF1 and WF3 and as historical context.

| WF2-E2E-70 condition | Task Outcome, Wilson 95% CI | Unsafe Outcome, Wilson 95% CI |
|---|---:|---:|
| Quick Create baseline | 49/70 = **0.700** [0.585, 0.795] | 11/70 = **0.157** [0.090, 0.260] |
| Smart Schedule optimised | 70/70 = **1.000** [0.948, 1.000] | 0/70 = **0.000** [0.000, 0.052] |

The paired Task Outcome difference is 0.300. There were 21 baseline-fail/optimised-pass
cases and no changes in the opposite direction (two-sided exact McNemar
`p=0.00000095`). The unchanged optimised result shows that the V3.4.3 100% was not caused
by omitted organiser, room, end-time, or flexible-slot feasibility predicates. It remains
a result on this bounded internal synthetic suite, not a universal scheduling claim.
The 70 optimised successes comprise 40 correct bookings and 30 correct abstentions or
no-mutation outcomes. They must not be described as 70 meetings successfully created.

The separate WF2-MECH-20 suite found a narrower mechanism boundary. It is not combined
with the E2E headline.

| Secondary mechanism measure | Result, Wilson 95% CI |
|---|---:|
| Conflict-type accuracy | 10/12 = **0.833** [0.552, 0.953] |
| Participant/organiser conflict recall | 5/6 = **0.833** [0.436, 0.970] |
| Room-conflict recall | 5/6 = **0.833** [0.436, 0.970] |
| No-conflict false-positive rate | 0/3 = **0.000** [0.000, 0.562] |
| Warning-reason accuracy | 10/12 = **0.833** [0.552, 0.953] |
| Feasible@3, candidate level | 17/17 = **1.000** [0.816, 1.000] |
| Coverage@3, eligible cases | 7/7 = **1.000** [0.646, 1.000] |
| Exact-slot preservation | 2/2 = **1.000** [0.342, 1.000] |
| Relaxation-warning fidelity | 2/2 = **1.000** [0.342, 1.000] |
| Diversity@3 | 6/6 = **1.000** [0.610, 1.000] |
| No-feasible behaviour | 1/1 = **1.000** [0.207, 1.000] |

The two conflict misses are informative. The production availability check omits the acting
organiser unless that person also appears in `participants`. It also compares free-text room
names exactly, so `Orion` and `Orion room` are treated as different resources. All returned
Top-3 candidates in the eight focused recommendation cases were independently feasible,
and all declared coverage and diversity checks passed.

**Post-evaluation defect closure (final code, 2026-08-23):** the formal V3.5 row above stays
immutable at 10/12; it is not silently restated. Before the code freeze, both defects it
identified were fixed: the interactive/API path now passes the acting organiser into every
availability and revalidation check, and known room display aliases resolve to one room ID.
New regression tests cover both cases. A non-persisting replay of the frozen mechanism set on
the final code gives 12/12 conflict-type and warning-reason accuracy, but this verification is
not promoted to a new formal result and is not used to replace the authoritative V3.5 number.

The 15-case temporal audit attributes the V3.3 to V3.4.3 score change to an evaluation
contract correction. Twelve V3.3 failures used nearest-future gold while the system used
the following calendar week. Three missing-time cases were first exposed when V3.4 began
deterministic source-only selection. This change must not be presented as a model-capability
improvement. The audit is frozen in
`data/eval_datasets/wf2_date_contract_audit_v35.json`.

The sealed manifest SHA-256 is
`bad6987eb968f79ce8f11daa2f85f95c32c0382bbf7c2e3149782bcdd442ae1c`.
The append-only formal record is `data/eval_results/outcomes_wf2_v35.jsonl`, status
`v3_5_formal`, row SHA-256
`14ff0d787da0cea142ab415e20e1f8cf3b554f1e1e79f847d4a1133708bdfeba`. It was executed
from clean protocol commit `16107cd93a35508702c9eb4b309953cea5415a95` and links the
historical V3.4.3 row by SHA-256.
V3.5 does not evaluate update, cancel, reuse, recurrence, large participant sets, room
capacity, preference-ranking quality, title or agenda semantics, or external validity.

### 1.3 Evaluation V3.4.3 — authoritative WF1/WF3 formal row (2026-08-23)

V3.4.3 is the immutable cross-workflow Part A row. It preserves all 223 V3.4.2 cases and all
WF1/WF3 frozen outputs. The only source repair completes one truncated WF2 noise message
(`... go over the` → `... go over the sprint review?`); its gold is unchanged and only
that synthetic message is re-read by GPT-OSS. The WF2 task contract additionally scores
categorical meeting mode because virtual versus in-person changes the realised event. It
continues to accept any deterministic feasible slot when exact time is absent. Gold/meta
labels remain scoring-only, and every matched pair shares source, model output, initial
state and GoldFinalState.

| Workflow / condition | n | Task Outcome, Wilson 95% CI | Unsafe Outcome, Wilson 95% CI | Absolute change vs baseline |
|---|---:|---:|---:|---:|
| WF1 Gate 0 baseline | 45 | 21/45 = **0.467** [0.329, 0.609] | 18/45 = **0.400** [0.270, 0.545] | — |
| WF1 draft-only optimised | 45 | 39/45 = **0.867** [0.738, 0.937] | 3/45 = **0.067** [0.023, 0.179] | Task +40.0 pp; unsafe −33.3 pp |
| WF2 Quick Create baseline | 70 | 49/70 = **0.700** [0.585, 0.795] | 11/70 = **0.157** [0.090, 0.260] | — |
| WF2 Smart Schedule optimised | 70 | 70/70 = **1.000** [0.948, 1.000] | 0/70 = **0.000** [0.000, 0.052] | Task +30.0 pp; unsafe −15.7 pp |
| WF3 legacy-review baseline | 108 | 76/108 = **0.704** [0.612, 0.782] | 9/108 = **0.083** [0.044, 0.151] | — |
| WF3 gold-free policy gate | 108 | 96/108 = **0.889** [0.816, 0.935] | 4/108 = **0.037** [0.014, 0.091] | Task +18.5 pp; unsafe −4.6 pp |
| **All baseline conditions** | **223** | **146/223 = 0.655** [0.590, 0.714] | **38/223 = 0.170** [0.127, 0.225] | — |
| **All optimised conditions** | **223** | **205/223 = 0.919** [0.876, 0.948] | **7/223 = 0.031** [0.015, 0.063] | Task +26.5 pp; unsafe −13.9 pp |

The WF2 result remains 70/70 with zero unsafe outcomes after the stronger mode predicate.
This historical row predates the independent V3.5 follow-up. Its increase over V3.3 is
attributed to a temporal evaluation-contract correction rather than model improvement, as
shown by the frozen V3.5 date audit. The source-only scheduler succeeds on all sealed
ordinary, missing-time, ambiguity, revision and pre-booked-conflict cases. The
95% Wilson lower bound is 0.948, so the result should be reported as perfect performance
on this fixed synthetic suite, not as universal reliability. Two complete offline replays
were byte-identical. Scripted transition/review summaries are secondary diagnostics and
are explicitly not human evidence.

The sealed manifest is `data/eval_datasets/automated_v343_manifest.json` (SHA-256
`e2ba8f8b15da67b55eae33aba9a1813bee8831af3acb9dae5892195261f74429`). The append-only
formal record is `data/eval_results/outcomes_v343.jsonl`, status `v3_4_3_formal`, row
SHA-256 `b20130d4400158520bb51e98f28ffce20b160eec7f32fab83b4236f88ac3f479`, recorded from
clean implementation commit `b02bf418e16ba6444dc43446c1a7b968d24d6a1e`. The row explicitly supersedes V3.4.2
SHA-256 `1041617baf918c32b331754ccd9bc8e0f7f01be9c3615ce9b88cdc893de463e5` and stores the
sealed source, dataset and cache hashes.

### 1.4 Part B Human Evaluation V5.1 — final descriptive result (2026-08-20)

The completed controlled single-reviewer study contains 36 formal cases (12 per workflow,
six per condition/workflow) after six excluded pilots. The final authority is the latest
`human_v5_formal` row, SHA-256
`5525e7844f1be676da589fc34cdc6a8ddf1d4fe584805494b45a6cbfe09263df`.

| Condition | Task success | Unsafe actions | Decision correct | Median active review time | Median interactions |
|---|---:|---:|---:|---:|---:|
| Manual | 13/18 = **0.722** | 1/18 = **0.056** | 16/18 = **0.889** | **49.751 s** | **8.5** |
| Agent-Assisted | 15/18 = **0.833** | 1/18 = **0.056** | 15/18 = **0.833** | **25.304 s** | **3.0** |

Agent assistance was associated with two more successful outcomes and substantially lower
median review time and interactions in this one-author task set, without changing the unsafe
count. It did not improve decision correctness in aggregate. These repeated observations are
descriptive evidence, not independent-user or population-level usability estimates. The
post-collection £50 meals-limit adjudication is preserved separately and disclosed in
[`human_evaluation_v5_protocol.md`](human_evaluation_v5_protocol.md); collection was not
rerun.

### 1.5 Historical provenance — V3.4.1 (superseded)

Sections 1.5–1.8 explain why the contract evolved. Their superseded JSONL wrappers were
removed from the final checkout to avoid competing "latest" results; the original immutable
files and commits remain recoverable in Git history. None of these sections is current
final evaluation evidence.

V3.4.1 is a superseded Part A result. It retains the 223 V3.4 source cases and the same
frozen GPT-OSS/Qwen outputs, but aligns every workflow with the current production
contract. WF1 scores source-explicit draft fields and separates safe pending-draft errors
from harmful mutations. WF2 seals V5 weekday semantics in both gold and pre-booked state.
WF3 retains category as task-defining but treats a category-only error as task-only when
the final policy status is unchanged. Gold/meta labels remain scoring-only.

| Workflow / condition | n | Task Outcome, Wilson 95% CI | Unsafe Outcome, Wilson 95% CI | Absolute change vs baseline |
|---|---:|---:|---:|---:|
| WF1 Gate 0 baseline | 45 | 21/45 = **0.467** [0.329, 0.609] | 18/45 = **0.400** [0.270, 0.545] | — |
| WF1 draft-only optimised | 45 | 39/45 = **0.867** [0.738, 0.937] | 3/45 = **0.067** [0.023, 0.179] | Task +40.0 pp; unsafe −33.3 pp |
| WF2 Quick Create baseline | 70 | 49/70 = **0.700** [0.585, 0.795] | 11/70 = **0.157** [0.090, 0.260] | — |
| WF2 Smart Schedule optimised | 70 | 70/70 = **1.000** [0.948, 1.000] | 0/70 = **0.000** [0.000, 0.052] | Task +30.0 pp; unsafe −15.7 pp |
| WF3 legacy-review baseline | 108 | 64/108 = **0.593** [0.498, 0.681] | 9/108 = **0.083** [0.044, 0.151] | — |
| WF3 gold-free policy gate | 108 | 72/108 = **0.667** [0.573, 0.748] | 9/108 = **0.083** [0.044, 0.151] | Task +7.4 pp; unsafe unchanged |
| **All baseline conditions** | **223** | **134/223 = 0.601** [0.535, 0.663] | **38/223 = 0.170** [0.127, 0.225] | — |
| **All optimised conditions** | **223** | **181/223 = 0.812** [0.755, 0.858] | **12/223 = 0.054** [0.031, 0.092] | Task +21.1 pp; unsafe −11.7 pp |

The cross-workflow scenario families are secondary diagnostics: optimised Task Outcome is
33/40 (82.5%) for ordinary, 89/123 (72.4%) for ambiguous/degraded, 25/26 (96.2%)
for pooled multi-step/revision/conflict and 34/34 (100%) for policy/refusal. The lower
ambiguous/degraded value is concentrated in degraded WF3 receipt evidence; it must not be
read as a single generic agent capability.

The sealed manifest is `data/eval_datasets/automated_v341_manifest.json` (SHA-256
`164c2caf33d6a3f353d273c65e4873abea47120b711dd04aa4b60963c0e38669`). The append-only
formal row was stored as `data/eval_results/outcomes_v341.jsonl` (Git history only in the
final checkout), status `v3_4_1_formal`, row SHA-256
`4f6dfb6ca9522b1e36c32b380827b17c950d51f5e9fd23aa306e7816fc694987`, recorded from
clean implementation commit `0b030d5e2866981ec5bf27e1e7e210f2f7328c78`.

### 1.6 Historical provenance — V3.4 (superseded)

V3.4 was the first Part A validity-repair audit. It uses 223 unique synthetic cases and 446
matched executions. Every pair has the same source, frozen model output, deterministic
initial state and GoldFinalState; gold/meta labels are scoring-only. WF1 now contains
supported meeting, expense and genuine meeting+expense cases and uses production message
IDs/attachment grounding. WF2 preserves Smart Schedule's exact-time-optional behaviour.
WF3 scores category and executes non-receipt refusal only from frozen Qwen output.

| Workflow / condition | n | Task Outcome, Wilson 95% CI | Unsafe Outcome, Wilson 95% CI | Absolute change vs baseline |
|---|---:|---:|---:|---:|
| WF1 Gate 0 baseline | 45 | 21/45 = **0.467** [0.329, 0.609] | 18/45 = **0.400** [0.270, 0.545] | — |
| WF1 draft-only optimised | 45 | 30/45 = **0.667** [0.521, 0.786] | 15/45 = **0.333** [0.214, 0.479] | Task +20.0 pp; unsafe −6.7 pp |
| WF2 Quick Create baseline | 70 | 39/70 = **0.557** [0.441, 0.668] | 21/70 = **0.300** [0.205, 0.415] | — |
| WF2 Smart Schedule optimised | 70 | 55/70 = **0.786** [0.676, 0.866] | 15/70 = **0.214** [0.134, 0.324] | Task +22.9 pp; unsafe −8.6 pp |
| WF3 legacy-review baseline | 108 | 64/108 = **0.593** [0.498, 0.681] | 32/108 = **0.296** [0.218, 0.388] | — |
| WF3 gold-free policy gate | 108 | 72/108 = **0.667** [0.573, 0.748] | 28/108 = **0.259** [0.186, 0.349] | Task +7.4 pp; unsafe −3.7 pp |
| **All baseline conditions** | **223** | **124/223 = 0.556** [0.490, 0.620] | **71/223 = 0.318** [0.261, 0.382] | — |
| **All optimised conditions** | **223** | **157/223 = 0.704** [0.641, 0.760] | **58/223 = 0.260** [0.207, 0.321] | Task +14.8 pp; unsafe −5.8 pp |

These values are retained to show the strict-contract sensitivity that motivated V3.4.1.
They are not the current headline and are not evidence of a newly tuned system. Scripted
transition summaries remain secondary, non-human diagnostics.

The sealed manifest is `data/eval_datasets/automated_v34_manifest.json` (SHA-256
`011c3a2346b94a5bf12e4ee2a67ef53941e365bcbb69643ac4dcd05516491d5b`). The formal row was
stored as `data/eval_results/outcomes_v34.jsonl` (Git history only in the final checkout),
status `v3_4_formal`, row SHA-256
`f5f26238cda6d8c878ca58b821bf94bccf138220a11454e5a8ccf15ea34bfccb`, recorded from
clean implementation commit `388a73fb26a9160915a8df9c55ad6c8e334d4b2f`.

### 1.7 Historical provenance — V3.3 (superseded)

V3.3 is a superseded historical automated result. It uses actual frozen
`openai/gpt-oss-120b` outputs for WF1/WF2 and the frozen `qwen/qwen3.6-27b` receipt
outputs for WF3. The £50 meals limit is a hard rejection rule. The primary WF3 condition
does not read gold to repair model fields. There are 223 unique synthetic cases and 446
matched condition executions.

| Workflow / condition | n | Task Outcome, Wilson 95% CI | Unsafe Outcome, Wilson 95% CI | Absolute change vs baseline |
|---|---:|---:|---:|---:|
| WF1 Gate 0 baseline | 45 | 27/45 = **0.600** [0.455, 0.730] | 0/45 = **0.000** [0.000, 0.079] | — |
| WF1 draft-only optimised | 45 | 39/45 = **0.867** [0.738, 0.937] | 6/45 = **0.133** [0.063, 0.262] | Task +26.7 pp; unsafe +13.3 pp |
| WF2 Quick Create baseline | 70 | 49/70 = **0.700** [0.585, 0.795] | 21/70 = **0.300** [0.205, 0.415] | — |
| WF2 Smart Schedule optimised | 70 | 58/70 = **0.829** [0.724, 0.899] | 12/70 = **0.171** [0.101, 0.276] | Task +12.9 pp; unsafe −12.9 pp |
| WF3 legacy-review baseline | 108 | 87/108 = **0.806** [0.721, 0.869] | 9/108 = **0.083** [0.044, 0.151] | — |
| WF3 gold-free policy gate | 108 | 96/108 = **0.889** [0.816, 0.935] | 9/108 = **0.083** [0.044, 0.151] | Task +8.3 pp; unsafe unchanged |
| **All baseline conditions** | **223** | **163/223 = 0.731** [0.669, 0.785] | **30/223 = 0.135** [0.096, 0.186] | — |
| **All optimised conditions** | **223** | **193/223 = 0.865** [0.814, 0.904] | **27/223 = 0.121** [0.085, 0.170] | Task +13.5 pp; unsafe −1.3 pp |

The paired task comparison contains 36 baseline-fail/optimised-pass cases and six changes
in the opposite direction (two-sided exact McNemar/sign test, exploratory
`p=0.00000283`). By workflow the discordant counts are 18/6 for WF1 (`p=0.0227`), 9/0
for WF2 (`p=0.00391`) and 9/0 for WF3 (`p=0.00391`). The unsafe comparison is much less
clear: nine cases become safe and six become unsafe, so the pooled change is not
statistically distinguishable in this fixed suite (`p=0.607`). These p-values are
exploratory and unadjusted; workflow estimates and failure modes remain more informative
than the unequal-size pooled average.

The result does not support a claim that every optimisation improves safety. All six new
WF1 unsafe outcomes are ambiguous-message false positives: the optimised router supports
more action types, but therefore exposes GPT-OSS over-detection that the meeting-only
baseline happens not to execute. WF2 removes nine unsafe outcomes. Its remaining 12
failures are temporal-contract mismatches: three clean cases, eight revisions, and one
stateful conflict use following-week system dates against nearest-future V3.3 gold. They
are not extraction failures and are audited by the final V3.5 temporal analysis in §1.2.
WF3 correctly rejects all six over-limit and three duplicate cases, improving task
completion over the baseline's blocked-but-still-submitted state. Its 12 remaining task
failures come from uncorrected Qwen evidence errors in clean (2), cropped (5) and
low-resolution (5) receipts. Nine of those failures are unsafe; removing the former gold
oracle deliberately exposes this residual risk.

The sealed protocol is `data/eval_datasets/automated_v33_manifest.json`; the active formal
wrapper SHA-256 is
`4df36b9965a9128d2a0cb00455cb8ae51f730d64cfdb5794e36778a4213c924d`.
The append-only log also retains an immediately superseded V3.3 row whose per-case
`evaluation_version` was incorrectly labelled `v3.2`; the active row references that row's
SHA in `supersedes_sha256`. Outcomes and frozen model caches are identical. Reporting APIs
exclude the superseded row, leaving exactly one active `v3_3_formal` record.

### 1.8 Historical provenance — V3.2 (superseded)

This is the final automated outcome run. It replays committed synthetic data
and previously frozen model outputs; it makes no new model calls and never touches the live
workspace. Within each workflow, baseline and optimised conditions use identical case IDs,
model drafts and gold final-state predicates. There are 208 matched source cases and 416
condition records in total.

| Workflow / condition | n | Task Outcome, Wilson 95% CI | Unsafe Outcome, Wilson 95% CI | Absolute change vs baseline |
|---|---:|---:|---:|---:|
| WF1 Gate 0 baseline | 30 | 12/30 = **0.400** [0.246, 0.577] | 18/30 = **0.600** [0.423, 0.754] | — |
| WF1 draft-only optimised | 30 | 30/30 = **1.000** [0.886, 1.000] | 0/30 = **0.000** [0.000, 0.114] | Task +60.0 pp; unsafe −60.0 pp |
| WF2 Quick Create baseline | 70 | 60/70 = **0.857** [0.757, 0.921] | 10/70 = **0.143** [0.079, 0.243] | — |
| WF2 Smart Schedule optimised | 70 | 70/70 = **1.000** [0.948, 1.000] | 0/70 = **0.000** [0.000, 0.052] | Task +14.3 pp; unsafe −14.3 pp |
| WF3 legacy-review baseline | 108 | 96/108 = **0.889** [0.816, 0.935] | 9/108 = **0.083** [0.044, 0.151] | — |
| WF3 evidence-review optimised | 108 | 108/108 = **1.000** [0.966, 1.000] | 0/108 = **0.000** [0.000, 0.034] | Task +11.1 pp; unsafe −8.3 pp |

For the Overview only, detailed tiers are grouped into four readable risk families:
ordinary (n=40), ambiguous/degraded input (n=108), complex/stateful (n=26), and
policy/refusal (n=34). This is a presentation-only aggregation: all 208 matched cases and
their original tier labels remain in the formal record and case explorer.

Interpretation by workflow:

- **WF1:** the baseline's route-and-execute behaviour violates the workflow boundary in
  18/30 cases; draft-only routing retains all intended work without downstream execution.
- **WF2:** Smart Schedule resolves all ten Quick Create final-state failures in this frozen
  suite while adding one median interaction (2 versus 1). Candidate rank was recorded for
  40 cases and was always rank 1 at the median and quartiles.
- **WF3:** the legacy condition leaves all 12 initially wrong drafts wrong, including nine
  harmful approvals. The scripted evidence verifier rescues all 12; nine use the explicit
  request-information/resubmission path. This is an **oracle-assisted scripted upper bound**,
  not a human-review result and not evidence of model self-correction.

The aggregate across baseline and optimised conditions is 376/416 = 0.904 Task Outcome and
37/416 = 0.089 Unsafe Outcome, but that pooled number is not the main comparison because it
mixes deliberately different conditions. Formal provenance records base commit
`381a244013a5a2c4b170ca88e48882be88ebc168`, content hashes for datasets, frozen outputs and
evaluation source, fixed seed 0, and result status `v3_formal`. The append-only record was
stored in `data/eval_results/outcomes_v3.jsonl` (Git history only in the final checkout);
wrapper SHA-256
`20b7d81393dbea559f0cefd62703f3fa19cd5be9f360a560ab0778d534e0a94e` was independently
recomputed after writing.

These superseded figures are provenance only. The completed V5.1 study in §1.4 now provides
separate descriptive evidence for one author's decision time and interaction burden.

## 2. Per-workflow detail

### 2.1 WF1 — triage / intake (final runs 2026-07-14, both models)

| Condition | tiers at 1.00 | ambiguous refusal |
|---|---|---|
| template (n=5/tier) | recall+exact on meeting/leave/multi/noise; out-of-scope refusal | **0.40 both models** |
| realised-cleaned (n=6/tier) | recall+exact on all action tiers; out-of-scope refusal | *tier added 2026-07-23 (n=15, 9/15 Qwen-realised); **not yet scored** — the scoring run is outstanding (§6)* |

> **Prompt-change re-validation (2026-07-16).** The triage prompt gained a `Channel:
> email|chat` line (WF1 now tells the model which medium the thread arrived on). Because a
> prompt change invalidates previously collected numbers, the template condition was
> **re-run on both models**: results are **identical** (all action tiers 1.00; ambiguous
> refusal 0.40 on both) — the channel hint neither helps nor harms at this difficulty.
> Recorded here rather than silently carried over.

Position sensitivity (template, n=2/cell): recall 1.00 in every cell of length
{10,25,50} × position {early,middle,late}.

> **Correction (methodological finding, write up):** the previously reported realised
> recall collapse (0.33–0.67, runs of 2026-07-08) was traced to **realiser quality**, not
> model capability: the old LLM realiser sometimes rewrote threads into meta-output
> (describing the conversation instead of being it). After adding a reject-and-fallback
> back-check and regenerating the frozen set, recall is 1.00 for both models. The
> stable, real weakness is **ambiguity**: both models over-detect actions in borderline
> social chat (refusal 0.40–0.67 across runs) — exactly what the human Dismiss exists for.

### 2.1b WF1 — abstention under controlled contrasts (minimal pairs, 2026-07-22)

`llama-3.3-70b-versatile`, n=6 twins per δ (48 threads). Each case ships a **twin whose
thread is identical except for one cue**; one side must be routed, the other refused. A
constant policy is right on exactly one side of every twin, so paired accuracy floors
"always act" and "always abstain" at 0. Method after AgentAbstain (2026).

| δ contrast | Act (T+) | Abstain (T−) | Gap | Paired acc. | CAR |
|---|---|---|---|---|---|
| `time_specificity` — "sometime" vs "Tuesday 14:00" | 1.00 | **0.00** [0.00,0.39] | **+100 pts** | 0.00 | 0.00 |
| `hypothetical_vs_actual` — "if we ever need to" vs "we need to" | 1.00 | **0.00** [0.00,0.39] | **+100 pts** | 0.00 | 0.00 |
| `third_party_vs_self` — "marketing are meeting" vs "can we meet" | 1.00 | 0.17 [0.03,0.56] | +83 pts | 0.17 | 0.17 |
| `settled_vs_requested` — "already sorted" vs "need to sort" | 1.00 | 0.67 [0.30,0.90] | +33 pts | 0.67 | 0.67 |

**Act is 1.00 on every δ**, so CAR ≡ paired accuracy: the model is not inert, it is
genuinely biased toward acting. This replaces the un-interpretable `ambiguous` refusal rate
with a mechanism: the model **does not use temporal specificity or grammatical mood at all**,
partially uses tense/aspect, and largely fails on whose meeting it is. That last row
reproduces, on controlled synthetic text, the error mode real AMI transcripts exposed
(§2.8) — a meeting the thread *reports* being taken as one *requested of the agent*.
For scale: AgentAbstain reports a ~21-point act-over-abstain gap across 17 frontier models;
two δ families here are at 100.

Re-run of the standard tier set the same day (n=6): all action tiers 1.00, out_of_scope
refusal 1.00, **`ambiguous` refusal 0.17** (was 0.40 at n=5) — consistent with the pair result.

### 2.1f WF1 — feedback-conditioned prompting: pattern-match, not generalisation (2026-07-23)

Closing the loop on the reviewer's Dismiss: a few dismissed-style wordings are appended to
the triage prompt as few-shot negatives (prompt-layer, not persistent agent memory — the
agent still only proposes). Two conditions isolate *what* is learned; abstain-rate on the
T− (should-refuse) side, per δ, n=6:

| δ contrast | baseline | in_family (same frame) | cross_family (other frames only) |
|---|---|---|---|
| `time_specificity` | 0.00 | 0.33 | **0.00** |
| `hypothetical_vs_actual` | 0.00 | 1.00 | **0.00** |
| `settled_vs_requested` | 0.67 | 1.00 | **0.67** |
| `third_party_vs_self` | 0.17 | 1.00 | **0.67** |

**in_family lifts three δ families to near-perfect abstention; cross_family collapses them
back to baseline.** Negatives that share the test item's sentence frame help a lot;
negatives drawn only from the *other* families barely help (`third_party_vs_self` is the one
partial exception, 0.17→0.67). So the feedback loop teaches the model to **pattern-match the
phrasing it has seen dismissed, not to generalise "this kind of request is not actionable"**.

This is a negative result, and a load-bearing one: without the cross_family arm, the
in_family column alone (three 1.00s) would read as "the feedback loop works". The
held-out-vocabulary design (negatives share the δ *frame* but never the surface content, and
are disjoint from every test case — asserted by a test) is what lets the two columns be
compared cleanly. It also sharpens the HITL story: the human's Dismiss is reusable as a
*local* correction signal, but on this model it does not bootstrap into transferable judgement
— an argument for keeping the human in the loop rather than expecting the agent to learn its
way out of it. Consistent with NATURAL PLAN's finding that LLM self-correction on scheduling
tends not to generalise (§2.3c).

### 2.1c WF1 — retracted plans, and the deterministic recovery layer (2026-07-22)

A fully specified meeting (topic · day · time · room · attendees) that the same thread later
calls off. Gold = no action. `near`/`far` vary how many turns separate plan from retraction.

| Retraction distance | n | Model abstained | Code recovery | Net caught |
|---|---|---|---|---|
| near (gap 1) | 6 | 1.00 | — (nothing missed) | 1.00 |
| far (gap 8) | 6 | 0.83 [0.44,0.97] | 1.00 (1/1) | 1.00 |

**False-positive rate 0.00 [0.00,0.39]** for `check_retraction` on 6 genuine, non-retracted
meeting threads — without which the recovery rate would be meaningless.

This is the WF1 analogue of WF3's M1-vs-M7 contrast: the model reads the plan correctly, a
deterministic check reads what the thread says *later*. Note the **dissociation** with §2.1b:
the model tracks a cancellation across 8 turns of distractors (0.83–1.00) yet cannot tell
"sometime" from "Tuesday 14:00" (0.00). Discourse-level reasoning is not the weak link;
single-cue abstention is.

**Sharper observation from the seeded demo thread** (`Vendor contract sync`, gap 8): the
model's own summary states *"Alice cancels a meeting … is cancelled"* — and it emitted
`schedule_meeting` anyway, at confidence 0.8. This is not a comprehension failure. **The
model's action proposal contradicts its own summary in the same output.** Framed with §2.4,
that makes internal inconsistency the shared failure shape across workflows: WF3's fields do
not add up, WF1's action does not follow from its own summary.

### 2.1e WF1 — underspecified requests: does it invent the missing parts? (2026-07-22)

AgentAbstain's S1 scenario (missing critical parameter), adapted. A genuine request to meet
that names **no day, no time and no attendees**. Detection is the *correct* behaviour here —
the routing step's `needs_input` path exists for exactly this — so abstention is the wrong
lens. What matters is whether `seed_fields` stays honest. n=6, `llama-3.3-70b-versatile`.

| Metric | Value |
|---|---|
| detection rate | 1.00 |
| fabrication rate (any absent field filled) | 1.00 |
| — fabricated `date` | **0.00** |
| — fabricated `time` | **0.00** |
| — fabricated `participants` | **1.00** |

**The model never invents a slot.** It writes `"not specified"` / `null` for date and time in
every case — and the shared null-normaliser maps those to absent, so they reach the human as
missing fields rather than as data. That is the *harmful* fabrication avoided: an invented
"next Tuesday at 14:00" would put a wrong meeting on a real calendar.

**It does, however, always fill `participants` — from the thread's speaker list.** Inspection
of the raw outputs shows it is not hallucinating names: it lists whoever happened to talk,
including people whose only contribution was the broken coffee machine. So the failure is
**over-inclusive inference, not invention**: "who is in the room" is read as "who is in the
meeting". The consequence is concrete in this system, because those names flow into WF2's
participant resolution and conflict check.

Two consequences for the write-up: (a) the never-invent property that WF2 already
demonstrates for slots **holds for WF1 too, and only for slots**; (b) participant inference
needs either a prompt constraint ("list only people the thread names as attending") or a
deterministic check that intersects proposed attendees against those actually addressed —
another instance of the code-checks-the-model pattern.

### 2.1d WF1 — is the self-reported confidence worth anything? (2026-07-22)

Every detected action carries a `confidence` the model writes itself; nothing had ever used
it. Labelled per emitted action against gold (unit = action, not thread), on two datasets:

| Source | actions (correct/spurious) | mean conf. correct | mean conf. spurious | AUROC |
|---|---|---|---|---|
| minimal pairs (designed contrast → upper bound) | 43 (24/19) | 0.900 | 0.805 | **0.974** |
| standard tiers incl. natural `ambiguous` (**independent check**) | 35 (30/5) | 0.897 | 0.800 | **0.983** |

Threshold sweep at t=0.9: pairs → retains **1.00** of true detections, removes **0.95**
[0.75,0.99] of spurious ones; natural tiers → retains 0.97, removes **1.00** [0.57,1.00].

**But the signal is two-valued.** Across both datasets the model emitted only 0.9 and 0.8 —
correct detections were 0.9 in 24/24 cases, spurious were 0.8 in 18/19. So this is **not a
calibrated probability**; it is a coarse two-level commitment bit, and the operating point
sits between the only two values observed (brittle to any prompt or model change).

The load-bearing consequence is not the AUROC but what it implies: **the model marks the
spurious action as weaker and emits it anyway.** It has the information needed to abstain and
does not use it — which is a different and stronger argument for the human gate than "the
model cannot tell". Consistent with *Reported Confidence in LLMs Tracks Commitment More Than
Correctness* (2026).

### 2.2 WF1 — summary quality

- **Coverage ablation** (code-side gold-fact check): loose prompt **0.20–0.43** → one
  constraint ("WHO wants WHAT, WHEN; 3–5 actionable points") → **1.00**, held at n=15.
- **Faithfulness (final, Gemini 2.5 Flash judge, n=15):** mean **0.847**, summaries with
  ≥1 unsupported claim **0.467**. The interim same-family judge (n=4) had said 0.95/0.25 —
  the **cross-family judge is materially stricter**, consistent with self-preference bias;
  report judge identity with any faithfulness number.

### 2.2b Validating the judge — a second opinion, and a rejected optimisation (2026-07-27)

`evaluation.md §4` requires validating the judge before trusting it, since every
faithfulness number rests on it. Two checks were built (`evals/faithfulness.py`,
`run_judge_validation.py`). Judge-to-judge agreement was completed; the hand-labelled
extension was not part of the final frozen evidence and remains future work.

**(a) Judge vs judge — done.** Both `gemini-2.5-flash` (Google) and `openai/gpt-oss-120b`
(OpenAI) are a different family from the Llama generator, so both are legitimate judges.
Over the same n=20 summaries they land in nearly the same place:

| judge | mean faithfulness | unsupported-claim rate |
|---|---|---|
| gemini-2.5-flash | 0.922 | 0.15 |
| openai/gpt-oss-120b | 0.913 | 0.15 |

κ = **0.608**, raw agreement 0.90, disagreeing on 2 of 20 items. Two independent
cross-family judges converging is not proof of correctness — both could share a bias — but
it does rule out the reading that the faithfulness figure is one model's idiosyncrasy, and
the 2 disagreements are the shortlist worth hand-labelling first. *(Collected batched; see
(c) — treat the absolute values here as the batched condition, not as replacements for the
unbatched §2.2 numbers.)*

**(b) Judge vs human (Cohen's κ) — instrumented, not yet run.** `run_judge_validation judge`
writes every judged item to `data/eval_datasets/judge_labelling.jsonl` with an empty
`human_supported` field; `... score` computes κ per judge over whatever has been labelled.
The remaining step is the author labelling ~20–50 items. **Limitation to state when it is
run:** the annotator is the author and can see the judges' labels in the file, which biases
agreement *upward* — so a high κ is weak evidence and a low κ is strong evidence.

**(c) Batching the judge — measured, and rejected.** The binding constraint on judge-based
n is Gemini's free tier: **20 requests/day** against 250K tokens/minute (a single judgement
uses ~2% of the token budget). Packing 5 items per request would have bought ~5× the sample
for the same quota. A controlled check — same 20 pairs, same judge (gpt-oss), batched vs not
— shows it is not verdict-preserving:

| condition | requests | mean faithfulness | **unsupported-claim rate** |
|---|---|---|---|
| unbatched (1 item/request) | 20 | 0.875 | **0.50** |
| batched (5 items/request) | 4 | 0.898 | **0.25** |

κ = 0.30, raw agreement 0.65. **Judging items in company halves the safety-relevant rate** —
the judge decomposes each output more coarsely when several share a prompt. Batching is
therefore opt-in and never the default (a test pins `batch_size=1`), and all published
faithfulness numbers stay unbatched.

This is worth reporting as a finding rather than a footnote: LLM-as-judge results depend on
*how many items share a request*, a degree of freedom rarely stated in papers that use the
method. It also quantifies what the quota ceiling costs — on this free tier, an honest
unbatched judge run at n=20 consumes an entire day's allowance.

### 2.3 WF2 — scheduling (stateful path; final runs 2026-07-13/14, current gold)

| Model | condition | result |
|---|---|---|
| gpt-oss-120b | template + realised | **1.00 on every metric, every tier** (incl. revision, stateful conflict, abstention) |
| llama-3.3 | template | 1.00 everywhere except revision participants **0.90** |
| llama-3.3 | realised | 1.00 everywhere except revision participants **0.90** and out-of-scope abstain **0.90** |

llama's single recurring miss: it sometimes **omits the organiser** from the final
participant set after a multi-turn revision (1/10 in both conditions); it never mistakes
the final agreed *time* (1.00).

> **Correction (methodological finding, write up):** the previously reported revision
> failure ("participants 0.30–0.40 on both models") was a **gold-definition artifact**:
> the tier's gold originally excluded the organiser while models (correctly) included
> them. After fixing the gold (2026-07-10) and **re-scoring the cached raw extractions —
> zero new LLM calls** — the same outputs score 0.90/1.00. Caching raw model outputs and
> versioning gold made the artifact detectable and fixable retroactively.

### 2.3b WF2 — date resolution: a circular metric, and the convention it hid (2026-07-22)

**The methodological finding first.** `scheduling_data.py` builds its gold with
`resolve_relative_date(f"next {weekday}", GEN_NOW)` — *the function under test* — and
`scheduling_score.py` then compares the system's date to it. `date_correct` is therefore
**circular**: it can only fail if the LLM mangles a phrase the prompt told it to copy
verbatim. It measures **transcription fidelity**, not whether the resolver reads English the
way a speaker means it, and it cannot detect a wrong convention *even in principle*. That is
a large part of why WF2 looked saturated at 1.00.

**What the circularity hid.** The resolver treated `next <weekday>` as a synonym for the
soonest future one, so on a **Thursday, "next Friday" resolved to tomorrow** — a reading
almost no speaker intends. `Friday` and `next Friday` were also identical, though English
routinely distinguishes them. The two readings differ by exactly 7 days while the weekday is
still ahead in the current week, and coincide once it has passed.

**Fix, in the project's own idiom:** rather than silently picking a reading or refusing (and
losing the slot), `date_ambiguity()` marks it — `slot_provenance.date = "ambiguous"` plus a
**soft** `ambiguous_date` flag — so the code proposes its reading and the human confirms
which week was meant. Same posture as a low-confidence receipt field in WF3.

**New non-circular measure** (`evals/date_resolution.py`, exposed at `/api/eval/date_resolution`):
20 cases whose expectations are **written by hand from the English meaning**; a test asserts
the gold table's source contains no call to the resolver, so the circularity cannot creep
back. Deterministic — no model, no quota, instant to re-run.

| Behaviour | n | Rate |
|---|---|---|
| exact resolution (ISO, today/tomorrow, bare weekday, prose dates) | 12 | 1.00 |
| refuses to invent a vague date ("sometime next week", "ASAP", 2026-02-29) | 5 | 1.00 |
| flags an ambiguous `next <weekday>` | 3 | 1.00 |

> **Authoring note worth reporting.** One expectation (`next Monday` on a Wednesday) was
> first written as ambiguous and the suite rejected it: by Wednesday, Monday has passed, so
> both readings give the same day. Hand-authored gold forces that reasoning to be explicit —
> gold computed by the function under test would have silently agreed with whatever the code
> did.

### 2.3c WF2 — deterministic slot search instead of asking the model to plan (2026-07-22)

> **Out-of-scope for these numbers:** the current interactive WF2 configuration uses the
> Google Calendar API (`CALENDAR_BACKEND=google`, explicitly approved for controlled use), so an
> approved booking also appears on dedicated project calendars. It is deliberately **not**
> on any evaluated path (a test asserts the scorer never reaches the booking flow), so nothing
> in this results sheet depends on live credentials. See `wf2_scheduling_design.md §K`.


WF2 previously only ever *extracted* a slot the user had already stated; when the stateful
check found a clash, the human had to hunt for a free time by hand. `suggest_free_slots()`
now searches the events store deterministically — every participant and the room free, inside
working hours, spread ≥2h apart so three options are three real choices — and `/api/schedule/run`
returns them whenever a `conflict` or `room_double_booked` flag fires. The reviewer picks one;
the checks re-run against the choice at book time. The agent is still never asked to plan.

The design reason is measured elsewhere: NATURAL PLAN reports LLM accuracy on calendar
scheduling **collapsing as participants and days grow**, and — pointedly for this project's
thesis — **self-correction making it worse**. Constraint satisfaction is exactly the part to
keep in code, which mirrors WF3's arithmetic check and WF1's retraction check: the model reads,
deterministic code computes, the human decides.

### 2.3d WF2 — why there is no external anchor: SGD probed and rejected (2026-07-27)

`data_strategy.md` §4 names **SGD** (Schema-Guided Dialogue) as WF2's external anchor —
16k+ crowd-paraphrased task-oriented dialogues, PII-free, with a `Calendar_1` service whose
schema slots (`event_date` / `event_time` / `event_location` / `event_name`) look like a
one-to-one match for WF2's. Inspecting the corpus before building against it shows the fit
does not survive contact:

| check | finding |
|---|---|
| the intent that matches WF2 | `AddEvent` is declared in the schema but occurs **0 times with slot values** across **435 sampled `Calendar_1` dialogues**; the realised intents are `GetAvailableTime` (630 turns) and `GetEvents` (474) |
| direction of the task | SGD's calendar dialogues **query** a calendar; WF2 **creates** meetings |
| date gold | surface strings (`"Saturday this week"`, `"March 2nd"`), and **no reference date in the dialogue** |
| participants | none — single-user consumer assistant, no attendees, no directory |
| calendar state | none — nothing to detect a conflict against |

The date row is the decisive one. WF2's deterministic contribution is **resolving a relative
expression to an absolute date** against a known "now" — the thing §2.3b built a
hand-authored non-circular suite for. SGD's gold is the unresolved expression itself, so that
capability is **unscoreable there in principle**, not merely inconvenient.

What would still transfer is span extraction: given an utterance, does the model pick out the
right date/time substring. That is not WF2's task, and SGD's gold accumulates across turns
(dialogue-state tracking) so it does not align with single-shot extraction either. A number
built on it would be weaker than the gap it papers over.

**Decision: SGD is not adopted, and WF2's missing external anchor is reported as a limitation
(§4).** `data_strategy.md` §4 already cautioned "adapt, don't adopt wholesale"; the probe
shows even adapting fails, because the transferable intent is absent from the data. Recorded
here so the write-up can state a reasoned exclusion rather than an unfinished task — and so
nobody repeats the investigation.

### 2.4 WF3 — multimodal expense (`llama-4-scout`, final collection 2026-07-13)

Dataset `synthetic_v2`, 108 images, asymmetric per-tier counts by design (robustness
tiers n=18 for CI width; `duplicate` is one fixed claim; `non_receipt` has 3 variants).

| Tier | n | vendor | date | amount | currency | refusal |
|---|---|---|---|---|---|---|
| clean / skewed / faint | 18 ea | 1.00 | 1.00 | 1.00 | 1.00 | — |
| **low_res** | 18 | 1.00 | **0.44** [0.25,0.66] | 1.00 | 1.00 | — |
| **cropped** | 18 | 0.89 [0.67,0.97] | 0.94 | 0.94 | 0.89 | — |
| non_receipt | 9 | — | — | — | — | 1.00 |
| over_limit / duplicate | 6 / 3 | 1.00 | 1.00 | 1.00 | 1.00 | — |

| External | n | amount |
|---|---|---|
| **CORD real receipts (final)** | 40 | **0.82** [0.68,0.91] |

**Foreign-currency tier** (added 2026-07-20, separate dataset `foreign_currency/`, qwen3.6,
n=12 across EUR/USD/JPY). Receipts are priced *under* the £50 meals cap at face value and
*over* it once converted — the case only a currency-aware policy engine catches:

| vendor | date | amount | **currency** | policy (over_limit) |
|---|---|---|---|---|
| 1.00 | 1.00 | 1.00 | **1.00** | **12/12** |

Two things this measures that nothing else did. First, **currency-field extraction**, which
was previously untested — every other synthetic tier is GBP-only, and CORD is unlabelled
IDR. The model read all three currencies correctly, including JPY printed without a minor
unit (`JPY 12892`). Second, **conversion-before-comparison in the policy engine**: all 12
raised `over_limit` on the converted value, none of which would have fired on the printed
number. Perfect scores here are the expected result rather than a weak one — the tier
exists to show the *path* works end to end, and it is the deterministic half doing the work.

- **Failure modes are explainable and systematic.** low_res: 9/10 date failures are the
  same blur misread "202**6**"→"202**0**"; cropped: currency null when the total line is
  cut (2/18), one full-null (safe), one vendor hallucination; CORD: all 7 failures are
  IDR separator/scale misreads ("60.000"→60; "36,500,000"→365,000) — no random errors.
- **Design implication:** the dominant error (implausibly old year) is deterministically
  catchable — a **date-plausibility policy flag** would surface ~90% of low_res date
  errors. Perception weakness maps onto a cheap governance mitigation.
- **auto-approve error rate 0.131** — the concrete stake for the M4 gate argument.
- Scoring note: vendor matching is case- **and accent-insensitive** ("Café"="Cafe" — the
  model transliterates); before this fix the scorer under-reported vendor accuracy (0.33
  on over_limit) on correct reads.
- **Cross-model (RQ2 vision): qwen3.6-27b was run on the identical frozen images**
  (scout's raw outputs were cached pre-retirement); the completed comparison is in §2.7.

### 2.4b WF3 — reasoning consistency: read right, still wrong (M7, 2026-07-24)

The `inconsistent` tier renders a clean, readable receipt whose **printed TOTAL ≠ Σ line
items** — the fault *From Recognition to Reasoning* (arXiv 2605.22413) identifies: an MLLM
reads every field correctly yet never checks that the fields agree. Separate dataset
`inconsistent/` (n=12, qwen3.6), so `synthetic_v2` stays frozen.

| | rate |
|---|---|
| M1 — fields read correctly (vendor/date/amount/currency) | **0.92** (11/12) |
| the model's own extraction is internally contradictory | **11/11** usable |
| the model flags or mentions the discrepancy | **0/12** |
| **M7 — `check_arithmetic` detects it** (on gold) | **1.00** (12/12) |
| **M7 — on the model's own extraction** (deployed path) | **1.00** (11/11) |

**The contrast is the result.** The inconsistency is not hidden from the model — in 11 of 11
usable cases it is *inside the model's own output*, since it extracted both the line items and
the total that fail to reconcile. It still never noticed. Twenty lines of deterministic
arithmetic recover every case. This is the perception→**reasoning**→governance argument in one
table: extraction accuracy says nothing about whether the extracted facts cohere, and the
recovery belongs in code, not in a larger model.

The twelfth case is a truncated JSON response (no fields at all) — it fails safe, surfacing as
missing fields for the human rather than as a confident wrong claim.

### 2.4c M2 — task success: does the RIGHT RECORD get created? (2026-07-24)

M1 asks what fraction of *fields* the model read correctly; **M2 asks what fraction of
*records* are entirely right** after the deterministic layer (date resolution, participant
lookup, window arithmetic) and the gate have run. A record needs a *conjunction* of correct
fields, so per-field averages systematically overstate task-level correctness. Replayed from
the cached extractions the M1 numbers came from — same run, zero additional quota.

Four outcomes rather than one rate, because *no record* and *wrong record* are different
failures: `blocked` is the system declining to act; `wrong` is a wrong meeting on a calendar
or a wrong claim in the ledger.

**WF2** (llama-3.3, realised, n=70): **task success 0.975**, harmful-record rate **0.014**.

| tier | n | outcome |
|---|---|---|
| clean · noise · stateful_conflict | 10 ea | success 1.00 |
| revision | 10 | success 0.90 — 1 **wrong** record (the known organiser drop, §2.3) |
| missing · ambiguous · out_of_scope | 10 ea | **correct_abstain 10/10** |

`missing` (gold has no time) and `ambiguous` (gold has no date) are scored as *correct
abstention*, not failure: gold's answer there is "don't book, surface the gap" (§5), so
counting them as misses would reward a system that invents the absent slot.

**WF3** (qwen3.6, `synthetic_v2`, n=108): **task success 0.879**, harmful-record rate **0.083**.

| tier | n | M1 (vendor/date/amount/curr) | **M2** | outcomes |
|---|---|---|---|---|
| skewed · faint | 18 ea | 1.00 / 1.00 / 1.00 / 1.00 | **1.00** | — |
| clean | 18 | 0.89 / 0.94 / 0.94 / 0.94 | **0.89** | 1 wrong · 1 blocked |
| **low_res** | 18 | 1.00 / **0.72** / 1.00 / 1.00 | **0.72** | 5 wrong |
| **cropped** | 18 | 0.72 / 0.89 / 0.94 / 0.83 | **0.72** | 3 wrong · 2 blocked |
| over_limit · duplicate | 6 / 3 | 1.00 | **1.00** | — |
| non_receipt | 9 | — | — | **correct_abstain 9/9** |

**What M2 adds over M1.** On `cropped` no single field looks alarming (0.72–0.94), but only
**0.72 of records** are wholly correct, because the failures fall on *different* receipts —
the conjunction is what matters and per-field means hide it. The two numbers agree on
`low_res` (0.72 both) precisely because there the failures concentrate in one field.

**The headline for the gate.** 8.3% of receipts would commit a **wrong claim** to the ledger
unattended, versus 1.4% for WF2 — an order of magnitude, and the same asymmetry M1 shows:
perception is the risk, not text. This is the number the human verify-against-image step
(M4, §2.6) exists to absorb, and it is measured on the record rather than on the extraction.

> **Scoring note.** M2 uses `receipt_score._norm` (case- *and* accent-insensitive), the same
> normaliser M1 uses. An earlier draft compared raw strings and scored 4 correct reads of
> "Café Aurora"→"Cafe Aurora" as wrong records (low_res 0.56 instead of 0.72) — the identical
> mistake §2.4 records fixing in the M1 scorer. Comparing M1 with M2 is only honest if
> "correct read" means the same thing in both.

> **Calendar safety.** M2 is the first eval that calls `execute_scheduling` — the only path
> that can reach a real calendar. It injects `MockCalendarBackend()` explicitly rather than
> letting `config.CALENDAR_BACKEND` decide, so evaluation stays on the mock path (CLAUDE.md
> §3.4) even while the interactive app is pointed at the Google demo. Asserted in
> `test_task_success.py`.

### 2.8 WF1 — external validity on REAL meeting transcripts (AMI, 2026-07-16)

**What this can and cannot measure.** AMI (reached via QMSum; `knkarthick/AMI` is gated)
is ~100 scenario-acted meetings of a design team building a remote control. Verified on
sample: **0/25 transcripts mention a holiday or a next meeting** — these meetings contain
*none* of WF1's administrative intents. So AMI **cannot measure detection recall**. It
measures the mirror image, which is the half that actually matters here: **does the model
invent administrative actions when fed real, messy, action-dense human speech?** Gold =
"no routable action" by dataset construction; every raw output is cached and inspected.

> **Note on the plan:** `data_strategy.md` §4 recommends AMI/QMSum as WF1's external
> benchmark — but that was written for the *pre-re-scope* WF1 ("Communication
> Summarisation", 2026-06-30). The 07-01 re-scope made WF1 **triage/action-detection** and
> demoted summary to supporting context, and no public corpus labels administrative intents
> in enterprise chat. The framing above is the honest salvage; §4's claim is stale.

| Metric | llama-3.3-70b, n=20 real transcripts (≤50 turns) |
|---|---|
| **correct abstention** | **0.90** (18/20) |
| invented `leave_request` | **0** |
| invented `schedule_meeting` | 2 |

**Both false positives are the same, previously-unseen error mode** — the model mistakes
*the meeting it is reading* for *a meeting being requested*:

- `ami_8`: "the main thing I was gonna ask people to help with **today** is to give input
  on what database format we should use" → emitted `schedule_meeting`, date `"today"`.
- `ami_12`: "welcome back … the meeting actually we gathering here to discuss about the
  functional design meeting" → emitted `schedule_meeting`, date `"now"`.

Both carry date `today`/`now`: the model cannot separate the **meta-level** (this *is* a
meeting, in progress) from the **object-level** (someone is *asking to book* a meeting).

**This is the case for external validity, in one result.** The synthetic generator
*structurally cannot* produce this failure: its threads are chats *about* scheduling, never
transcripts *of* a meeting in progress. A rigorous, tiered, well-instrumented synthetic
eval was blind to an entire error mode that 20 real transcripts surfaced immediately.

**The gate absorbs it.** Both spurious actions carry no time, so the deterministic
validator returns `needs_input` rather than booking — the human is asked, nothing lands in
the calendar. The HITL design's value, demonstrated on real data rather than argued.

**It also crashed the system (now fixed).** On real transcripts the model emitted the
*string* `"null"` for `time`/`location` instead of a JSON null; `add_minutes` then raised
`ValueError` — an unhandled 500 on the live route. The template generator never produces a
stringy null, so this was invisible to the internal eval. Fixed with a shared `_clean`
normaliser (`"null"/"none"/"n/a"/…` → absent) plus strict `HH:MM` validation, so a
malformed time becomes a *missing field the human fills* rather than a parser crash.
Covered by 6 regression tests.

### 2.5 O4 — grounded decision notes (new feature, first numbers 2026-07-14)

Notes are generated **from the decided record + policy flags only** (fact sheet =
faithfulness source), stored as drafts, never sent. n=8 synthetic decided claims,
generator llama-3.3, judge gpt-oss-120b (cross-family):

- **fact coverage 1.00** — every note states decision, amount, vendor, date (+ reason
  when rejected); generation failures 0.
- faithfulness 0.776, unsupported-rate 1.00 under strict claim decomposition — inspection
  shows the "unsupported" claims are **courtesy boilerplate** ("please retain receipts…",
  sign-offs), not fact errors. Interpretation: claim-decomposition judges over-penalise
  conventional email pragmatics; report alongside coverage. No additional judge run is part
  of the final frozen evidence.

### 2.6 RQ3 — value of the human check (M4 scripted reviewers)

n=200, error rate 0.5 (injected error types mirror the live WF3 failure modes):

| Policy | false-accept | errors caught | edits/case |
|---|---|---|---|
| blind | **0.40** [0.34,0.47] | 0.00 | 0.00 |
| flag_following | **0.39** [0.33,0.46] | 0.025 | 0.00 |
| ideal (verify vs source) | **0.00** [0.00,0.02] | 1.00 | 0.40 |

The policy engine cannot see field-level extraction errors; the ideal scripted
field-vs-source verifier catches all of them at 0.4 edits/case. This is a simulated upper
bound, not observed human evidence. RQ3 supporting table.

### 2.7 RQ2 — cross-model comparison

- **Text (WF1/WF2):** llama-3.3 vs gpt-oss-120b are near-identical at this difficulty —
  both saturate detection and slot extraction; both fail ambiguous refusal at 0.40; the
  only separations are llama's organiser drop (0.90) and realised abstention (0.90 vs
  1.00). Model choice barely moves text accuracy; task structure does.
- **Vision (WF3): scout vs qwen3.6-27b — FINAL (2026-07-16), identical frozen images**
  (108 synthetic + 40 CORD; scout outputs frozen pre-retirement):

| Tier / field | scout | qwen3.6-27b |
|---|---|---|
| clean, all fields (n=18) | **1.00** | 0.89–0.94 (one *no-JSON generation failure*, one "Caf☒" mojibake vendor) |
| skewed / faint, all fields | 1.00 | 1.00 |
| **low_res date** (n=18) | **0.44** [0.25,0.66] | **0.72** [0.49,0.88] |
| low_res failure mode | 9/10 = "2026"→"2020" | **4/5 = the same "2026"→"2020"** |
| cropped v/d/a/c (n=18) | 0.89 / 0.94 / 0.94 / 0.89 | 0.72 / 0.89 / 0.94 / 0.83 |
| non-receipt refusal · policy tiers | 1.00 · 1.00 | 1.00 · 1.00 |
| **CORD real receipts** (n=40) | **0.82** [0.68,0.91] | **0.68** [0.52,0.80] |
| generation failures (no JSON, /108) | 0 | 2 |
| **auto-approve error rate** | **0.131** | **0.131** |

  Reading: **neither model dominates.** qwen is markedly more blur-robust (low_res date
  0.72 vs 0.44) but worse on truncated inputs (cropped), worse on real-world formats
  (CORD 0.68 vs 0.82 — same separator failure class plus nulls), and operationally less
  reliable (2/108 no-JSON outputs — the reasoning-token budget failure mode; plus a
  mojibake). Three thesis-grade conclusions: (a) **the blur year-misread "2026"→"2020"
  is cross-model** — a perceptual property of degraded receipts, not a model quirk — so
  the deterministic date-plausibility flag is a *general* mitigation; (b) **the
  aggregate risk is identical (auto-approve error rate 0.131 = 0.131): swapping the
  model redistributes errors, it does not remove them** — the human gate's value is
  model-independent; (c) migration is not an upgrade but a trade of failure modes —
  exactly what the §4.2 config-switch + frozen-cache infrastructure made measurable
  (the switch itself was one config line). Operational note: qwen TPD 200k ≈ ~55
  images/day (reasoning tokens) — vision eval throughput is itself a constraint.

## 3. Findings to write up

1. **Difficulty tiers + realistic language make reference-based eval informative** — but
   §3.2 now carries the sharper version of this point.
2. **The eval infrastructure is itself a finding (meta-methodology).** Two headline
   "failures" — WF2 revision 0.30–0.40 and WF1 realised recall 0.33–0.67 — were
   **artifacts of the evaluation layer** (a gold definition excluding the organiser; a
   realiser emitting meta-output). Both were caught and corrected *retroactively at zero
   LLM cost* because every raw model output is cached and datasets/gold are versioned.
   Lesson: version your gold, cache raw outputs, re-score on every harness change —
   otherwise eval bugs masquerade as model failures.
3. **Prompt ablation (WF1 summaries):** coverage 0.20–0.43 → 1.00 from one constraint.
   Prose summaries drop structured facts unless told not to; the structured fields +
   human review are the reliable carrier.
4. **The models over-act, not under-act (WF1).** Detection is saturated; both models
   turn borderline social chat into meetings at ~0.4–0.67 refusal. The human's Dismiss
   is the working control for over-detection.
5. **Perception is the weak link and degrades gracefully (WF3).** Errors concentrate in
   degraded/real-world inputs, are systematic (year blur, thousands separators), surface
   as low-confidence fields, and are exactly what the M4 ideal reviewer catches — and
   partly what a date-plausibility rule could catch deterministically.
6. **Judge identity matters (LLM-as-judge).** Same summaries: same-family judge 0.95
   faithfulness, cross-family 0.85 with 2× the unsupported rate; on O4 notes, strict
   claim decomposition flags boilerplate as unsupported. Faithfulness numbers are
   judge-relative; report the judge and validate on a human-labelled subsample (κ).
7. **A uniform gate over heterogeneous workflows is the right design.** The failure axis
   differs per workflow (abstention / perception / people), yet one three-state gate +
   policy engine + M4-style verification covers all of them.
8. **One real-data defect predicted a class of them (§2.9).** The AMI stringy-null crash
   was not a one-off: probing WF2/WF3 for the same *shape* of defect found a negative claim
   that **created £5000 of budget**, `vendor="null"` about to be stored as data, meetings
   bookable in the past, and a client-supplied negative-length meeting. All four are
   invisible to the synthetic eval, whose generators emit only well-typed, well-behaved
   values. Reference-based evaluation measures whether the model reads correctly; it says
   nothing about what the system does with a malformed or adversarial value.
9. **External data found what a rigorous synthetic eval structurally could not (§2.8).**
   20 real meeting transcripts surfaced (a) an unseen error mode — the model mistakes *the
   meeting it is reading* for *a meeting being requested* (both false positives dated
   "today"/"now"), and (b) a **crash**: the model emits the string `"null"`, which the time
   parser could not handle. Neither is producible by the template generator, whose threads
   are chats *about* scheduling and whose fields are always well-typed. Difficulty tiers
   make an internal eval *discriminating*; only real data makes it *complete*. Both the
   error mode and the crash were caught by the human gate / fixed in code — and the gate's
   `needs_input` path stopped both spurious actions from ever reaching the calendar.

10. **Minimal pairs turn an uninterpretable rate into a mechanism (§2.1b).** The
    `ambiguous` refusal rate could not distinguish "the model judges badly" from "these texts
    are harder". Twins differing by ONE cue can: the model ignores temporal specificity and
    grammatical mood entirely (abstain 0.00), partially uses tense/aspect (0.67). Act is 1.00
    everywhere, so CAR ≡ paired accuracy — ruling out the inert-model explanation, which a
    single-sided abstention tier cannot do.
11. **The failure is not comprehension, it is the link from comprehension to action
    (§2.1c/§2.1d).** Two independent signs: (a) on the seeded retraction thread the model's
    own summary says the meeting *is cancelled* while it simultaneously proposes booking it;
    (b) it stamps spurious detections with a lower confidence (0.8 vs 0.9) and emits them
    regardless. The model *has* the evidence to abstain and does not act on it. This is a
    stronger warrant for an external gate than "the model cannot tell", and it reframes the
    HITL argument from compensating for ignorance to compensating for **inconsistency**.
12. **Deterministic consistency checks generalise across workflows.** WF3 checks that fields
    add up (`check_arithmetic`, M7); WF1 checks that an action is not contradicted later in
    the thread (`check_retraction`, §2.1c); WF2's stateful conflict detection is the same
    shape. Each recovers a class of error the LLM produces with high per-field accuracy, and
    each is pure code with no quota cost. The measured WF1 instance recovers 1/1 misses at a
    0.00 false-positive rate on control threads.

## 4. Limitations (draft)

- **Synthetic-first.** LLM-realised prose (back-checked) widens language variety but is
  model-paraphrased; the realised set currently **lacks the ambiguous tier** (§6).
- **External validity is partial, and asymmetric.** WF3: CORD (n=40, amounts only).
  WF1: AMI (n=20) but **only as an abstention test** — no public corpus labels
  administrative intents in enterprise chat, so WF1's *detection recall on real data has
  never been measured*, and its gold ("no routable action") rests on a property of the
  corpus rather than annotation. WF2 has **no** external anchor, and this is now a
  *settled* gap rather than an open task: SGD was probed on 2026-07-27 and rejected — see
  §2.3d. §2.8 shows what this costs: real data immediately exposed an error mode and
  a crash the internal eval could not produce.
- **Small n on discriminating cells** (ambiguous 0.40 at n=5 → [0.12,0.77]; the 2026-07-22
  minimal-pair and retraction runs are n=6 per cell, so every rate there carries a CI of
  roughly ±0.35 — directional, not settled. `retracted_far` rests on a single failure.)
- **The confidence gate is fitted to a two-valued signal (§2.1d).** Only 0.9 and 0.8 were
  ever observed, so the 0.9 threshold sits between the only two points in the distribution;
  it is an operating point, not a calibration curve, and would need re-fitting after any
  prompt or model change. Spurious-removal on the natural set is 5/5 → [0.57,1.00].
- **Minimal-pair δ families are single-dimension and author-designed.** They isolate a cue
  by construction, which is the point, but they do not measure abstention on the messier,
  multi-cue ambiguity of real threads; §2.1b is a lower bound on difficulty.
- **Realiser and gold are moving parts** — §3.2 documents two artifacts; numbers are
  reported against dataset/gold versions (frozen jsonl + git).
- **Faithfulness depends on the judge** (§3.6). Two cross-family judges now agree closely
  (κ=0.608, §2.2b), which rules out one model's idiosyncrasy but is not a correctness
  check; **κ vs human labels is instrumented but not yet run** — the harness and the
  labelling file exist, the labels do not. The Gemini free tier is **20 requests/day**
  (measured 2026-07-27), and an unbatched n=20 run consumes all of it, so judge-based n
  stays small. Batching to escape that ceiling was tried and **rejected**: it halves the
  unsupported-claim rate (§2.2b).
- **M4 uses scripted reviewers, not humans** — bounds, not a user study.
- **The 2026-07-16 WF2 idempotency limitation is superseded** (§2.9): the current scheduling
  lifecycle requires and persists an idempotency key, and repeated decisions replay the
  same result. The formal v3 scorer also rejects duplicated keys. This removes that observed
  defect, but it does not prove distributed exactly-once delivery beyond the mock store.
- **FX is a frozen one-day snapshot.** Rates are ECB euro reference rates of 2026-07-17,
  retrieved once and hardcoded (`backend/money.py`); nothing is fetched at runtime, since a
  live feed would make evaluation runs unreproducible and would place a third-party service
  inside the evaluated core. What that leaves unmodelled: **effective-dated rate ranges**
  (the table is flat, so `fx_rate_date` records which rates were applied rather than
  selecting among them), **a rate provider**, and **realised FX gain/loss** — a real system
  books the difference between the rate at expense date and at reimbursement date, which is
  a treasury concern beyond this project. Conversions are frozen onto each record at submit
  time, so these are stable assumptions rather than drifting ones.
- **Date resolution is Anglophone and single-timezone.** The `next <weekday>` ambiguity is
  now detected and surfaced (§2.3b) rather than silently resolved, but the resolver still
  assumes English phrasing and one timezone; a real calendar integration is where that
  assumption would first break, which is what makes it the natural external anchor for WF2
  (the only workflow still without one).
- **WF2 lifecycle effectiveness is not part of V3.5.** The implementation supports update,
  cancel, reschedule, and reuse paths, but WF2-E2E-70 evaluates create, abstention, and
  conflict handling only. WF2-MECH-20 adds candidate and conflict diagnostics. Neither
  suite supports an empirical effectiveness claim for lifecycle operations, recurrence,
  large participant sets, or preference-ranking quality.
- Scout retired on 2026-07-17; its WF3 outputs remain frozen and production now uses
  qwen3.6-27b. The completed same-image comparison is retained in §2.7.

### 2.9 WF2 / WF3 robustness audit (2026-07-16)

The AMI stringy-null crash (§2.8) implied a *class* of defect, so WF2/WF3 were probed the
same way (direct API calls, adversarial values). Four confirmed and fixed; one open design
question. All found by probing, none by the synthetic eval — the generators emit only
well-typed, well-behaved values.

| # | Defect | Evidence | Fix |
|---|---|---|---|
| 1 | **A negative claim created budget.** An approved −£5000 expense moved Product's remaining budget **2981.50 → 7981.50** — consumption is derived by *summing* approved amounts, so a negative claim funds the department. | probe | numeric form fields must now be **finite and > 0** (every one is money or a count) → nulled → surfaced as missing |
| 2 | **Stringy nulls stored as data (WF3 half of §2.8).** `vendor="null"` passed the required-field check and would have been submitted as a vendor literally named "null"; `currency="N/A"` likewise. Real evidence: 3/296 cached vision outputs on **real CORD receipts** returned an empty vendor. | probe + cached real outputs | shared `agent/normalise.py` (`clean`/`clean_number`) now used by WF2 extraction, WF3 vision mapping, and the form layer |
| 3 | **Meetings bookable in the past**, silently. Made *more* reachable by the §5 `received_at` fix: a thread handled late legitimately resolves to a past date. | probe (booked 2020-01-01) | new **`past_date` soft flag** — flagged, not blocked, per the flag-don't-reject principle: retroactive intent is the human's call |
| 4 | **Client owned the time arithmetic.** `/decide` trusted the incoming `start`/`end`; a hand-edited time with a stale `end` booked a **negative-length meeting** (start 15:00, end 09:00). | probe | `execute_scheduling` **recomputes** the window from `time`+`duration` — code owns the arithmetic (CLAUDE.md §4.4) |

**Historical finding, subsequently fixed:** at the time of this 2026-07-16 audit,
idempotency was asymmetric between the two workflows. Both `/schedule/decide` and
`/expense/submit` were unguarded server-side (the UI disabled the button for the round-trip),
but the consequences differed:

- **WF3 is safe by defence-in-depth.** A double-submit creates two pending claims, but the
  approver can only approve one: the second hits the **`duplicate` hard rule** at the gate
  (`blocked_policy`). Verified. The cost is queue noise, not double payment.
- **WF2 is not.** A repeat `/decide` books a **second identical meeting**; the exact overlap
  raises only a `conflict` flag, and WF2's flags are *all soft by design*, so it books
  anyway. Verified: 2 events from 2 identical POSTs.

The later scheduling lifecycle resolved this without converting soft conflict flags into a
hard policy rule: decision requests now carry a stable idempotency key and replay the
existing event. The original observation is retained here as the audit trail, not as a
current limitation.

## 5. New since 2026-07-13 (system)

- **Multi-currency handling, and the reporting bug it exposed (2026-07-20).** WF3 offers ten
  currencies and CORD is IDR, but GBP conversion existed only inside the policy engine.
  `/api/eval/audit` was therefore **summing raw amounts across currencies** — one approved
  ¥17,000 receipt (≈ £78) added **17,000** to a department whose entire budget is £2,000.
  Now: `backend/money.py` holds a frozen ECB rate snapshot; conversions are **frozen onto
  each record at submit** (`amount_gbp`, `fx_rate`, `fx_rate_date`, `fx_table_version`) so
  editing the table cannot restate history (IAS 21); reporting sums GBP and *excludes and
  counts* unconvertible claims rather than drawing a wrong-scale bar; the review form keeps
  the **original** currency with a live `≈ £X · rate` readout beside it, because the human
  verifies the form against the image. Invented rates were replaced with a citable dated
  source — the previous table (`USD 0.79`, `JPY 0.0052`) was made up, and off by up to 13%.
  18 new tests, including the freeze property and a regression for the ¥17,000 case.

- **WF1 fidelity + correctness (2026-07-16).** Threads now carry `received_at`, and
  relative dates resolve against **the thread's arrival time, not the reader's clock** —
  previously a globally fixed "now" meant a thread read a week late silently shifted its
  meeting by a week ("next Tuesday" is next Tuesday *from when it was written*). The
  channel (`email`/`chat`) is now passed to the triage prompt (re-validated, §2.1).
  Three routing bugs found by direct API probing and fixed with idempotency guards
  (server + button lock): routing the same action twice **booked two meetings**; a routed
  action could be relabelled "dismissed"; re-triage reset handled actions to pending,
  re-enabling the double-book. Covered by 9 new regression tests (155 total).

- **O4 content generation shipped**: decision-note drafts grounded in record+flags,
  stored never-sent, editable in the Expenses UI; eval = coverage + faithfulness (§2.5).
  Closes the scope PDF's O4 item (email/document drafting) as a gate feature.
- **Policy engine**: FX conversion via fixed synthetic table (GBP-denominated limits,
  consumption converted); `unknown_currency` flag; **non_reimbursable** screen (vendor /
  purpose / receipt line items, word-boundary). 146 tests total.
- **Vision model is now an eval parameter** (per-model clients + `<think>`-stripping
  parser) — production default untouched.

## 6. Final freeze and reproducibility

Code and formal evaluation are frozen after the 2026-08-23 verification. The supported
offline check is:

```bash
PYTHONPATH=. .venv/bin/python -m backend.evals.final_part_a
```

This command rebuilds the declared `Part A Final` boundary without model or Google Calendar
calls and never appends a formal row. The V3.4.3, V3.5 and Human V5.1 evidence files remain
immutable. Unrun quota-dependent extensions from earlier working notes are future research,
not requirements for the final project result.
