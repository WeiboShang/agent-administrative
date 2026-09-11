# Data Strategy

> How the project obtains the data it runs and is evaluated on. Companion to
> `workflow_design.md`. Governed by CLAUDE.md §3 (synthetic task data; mock-only formal
> evaluation).
>
> ⚠️ **Written 2026-06-30. §1–§3 (reverse generation, difficulty tiers) held up and are what
> the generators implement. §4's external-dataset recommendation for WF1 is superseded:**
> it proposed AMI/QMSum for WF1 as a *summarisation* benchmark, but the 2026-07-01 re-scope
> made WF1 **triage / action-detection**, and no public corpus labels administrative intents
> in enterprise chat. AMI was integrated anyway, as an **abstention** test (real transcripts
> contain none of WF1's intents, so any detection is a false positive) — see
> [`results.md`](results.md) §2.8, which also records what that measurement *cannot* show.
> Actually integrated: CORD (WF3, real receipts) and AMI/QMSum (WF1, abstention only). SGD
> was never integrated, so WF2 has no external anchor.

---

## 1. Two layers — don't conflate them

| Layer | What it is | Constraint | This doc |
|---|---|---|---|
| **Input data** | the unstructured comms fed to the agent (emails, chats, requests) | **synthetic only** — no real identifiable people (CLAUDE.md §3.1) | §2–§5 |
| **Backends** | calendar/directory/state stores that get written to | evaluation: **mock only**; interactive WF2: approved Google Calendar sync to project calendars | `workflow_design.md` §2.2 |

"Use an open dataset" is a decision about the **input layer**. It does not touch the
backends. And because of §3.1, an open dataset is only admissible in the evaluated core
if it is itself synthetic / PII-free. Real corpora can still be used as **style
reference** (read to calibrate the generator), not as evaluated data.

---

## 2. Why not a RAG benchmark (e.g. enterprise RAG-bench)

Two independent reasons:

1. **Wrong task shape.** RAG benchmarks are *retrieval over a document corpus →
   answer*. This project is *single communication artifact → structured draft/action*.
   There is no knowledge-base retrieval step in the core task (directory lookup is a
   structured query, not RAG). The (query, corpus, answer) triples don't map to the
   labels we need: `(message → gold structured action)`.
2. **No usable ground truth + too heavy.** RAG-bench gives answer spans, not the
   structured `schedule_meeting`/form-field labels RQ2 measures.

→ **Dropped.**

---

## 3. Primary dataset: controllable synthetic generation

This is the **evaluated** dataset. It is the only option that satisfies *all* of:
ethics-safe, has ground-truth labels, and supports controlled difficulty. Building it
is itself a methodological contribution ("a controllable benchmark generator for
administrative agents"), not a shortcut.

### 3.1 Core idea — reverse generation

Do **not** write messages and then hand-label them. Instead:

```
sample gold structure (CODE) ──► realise as natural language (LLM) ──► back-check (CODE/LLM) ──► store (input, gold, meta)
```

Because the gold structure is fixed **before** the text exists, every example is
labelled by construction. The LLM only does the part it's good at (writing natural
prose); the labels never depend on the LLM being correct.

### 3.2 Pipeline, step by step (example: WF2 scheduling)

**Step 1 — sample a gold object (CODE, deterministic).** Draw from the shared synthetic
org fixture and controlled distributions:

```python
gold = ScheduleMeeting(
    title="Q3 budget sync",
    participants=["alice", "bob"],        # drawn from the org fixture
    date="2026-07-07",                    # absolute, known
    time="14:30",
    duration_minutes=30,
    mode="virtual",
)
meta = DifficultyConfig(tier="ambiguous",
                        date_style="relative",   # render date as "next Tuesday"
                        omit=["duration"],        # leave duration unstated
                        noise=True)               # add unrelated chit-chat
```

**Step 2 — realise as text (LLM).** Prompt the model with the gold object + difficulty
config and ask for a realistic message:

> "Write a short, natural Slack message from {alice} requesting this meeting. Refer to
> the date as a relative expression ('next Tuesday'), do **not** state the duration, and
> include one sentence of unrelated small talk. Do not restate the fields as a list."

Output (the `input_text`):
> *"Hey Bob — hope the move went ok! Can we grab 30 mins… actually whenever suits next
> Tuesday afternoon to go over the Q3 budget? Happy to do it over Zoom."*

**Step 3 — back-check (CODE + optional LLM-judge).** Round-trip: confirm the rendered
text still entails the gold object (e.g. the relative date, once resolved against the
generation `now`, equals `2026-07-07`; participants/mode are recoverable). If it drifted
(LLM added a wrong detail, dropped a participant), **discard and regenerate**. Spot-check
a human sample for calibration.

**Step 4 — store the record.**
```json
{"input_text": "...", "gold": { ...ScheduleMeeting... },
 "meta": {"workflow": "scheduling", "tier": "ambiguous",
          "now": "2026-06-30T09:00", "generator_version": "v1"}}
```

The same four steps apply to every workflow — only the gold schema and the difficulty
knobs change.

### 3.3 Difficulty taxonomy (this is what makes evaluation rigorous)

Generate a balanced set across tiers so you can report accuracy **per tier** (far more
convincing than one aggregate number):

| Tier | What's injected | Tests |
|---|---|---|
| `clean` | all required info explicit | baseline extraction |
| `missing` | a required field omitted | missing-field detection / refusal to auto-fill |
| `ambiguous` | relative dates, vague refs | resolution + provenance tagging |
| `multi` | several actions in one message | decomposition |
| `noise` | unrelated chit-chat / distractors | robustness |
| `out_of_scope` | nothing the workflow should act on | correct refusal (no force-fit) |

`out_of_scope` and `missing` are where human-in-the-loop value shows up — they're the
cases an over-eager autonomous agent gets wrong. Make sure they're well represented.

### 3.4 Why this is defensible at viva

- **Controlled:** you vary one factor at a time → causal claims about what breaks.
- **Labelled by construction:** no annotation noise.
- **Ethics-clean:** fictional org, no real PII.
- **Reproducible:** seed + `generator_version` regenerates the exact set (CLAUDE.md §3.4).
- Pre-register the taxonomy and generator before running evals so it isn't "tuning the
  test to the model".

---

## 4. External open datasets — survey & verdict

Use these as a **secondary, external-validity** check and/or style calibration. Verdict
column says how each may be used given §3.1.

| Dataset | What it is | Fits | Ethics / licence | Use as |
|---|---|---|---|---|
| **Schema-Guided Dialogue (SGD)** | 16k+ synthetic multi-domain dialogues with explicit schema/intents/slots; includes Calendar/Events/Travel | WF2, WF3 (slot extraction) | **Synthetic, crowd-paraphrased — PII-free** | **Secondary eval / bootstrap.** Closest external fit; domains differ from enterprise admin so adapt, don't adopt wholesale |
| **AMI Meeting Corpus** | ~100 scenario-**acted** meetings (role-play design team), transcripts + abstractive/extractive summaries; ~381 action-item annotations | WF1 | Scenario-acted, consented, research licence — **low PII risk** | **External eval for WF1.** Best real-but-safe fit for summarisation/action-items |
| **QMSum** | query-based meeting summaries over 232 meetings (AMI + ICSI + Parliament) | WF1 | Built on AMI/ICSI (consented) + public Parliament | External eval for WF1 (query-focused summaries) |
| **SNIPS / NLU-Benchmark (HWU64)** | short single-utterance commands incl. calendar `set_event` intents | WF2 (intent/slot only) | Crowd-collected, PII-free | Quick intent/slot sanity check; too short for realistic threads |
| **Enron Email** | ~500k real corporate emails, rich scheduling/request content | WF2, WF4 (style) | **Real people, real PII** | **Style reference ONLY** — read to calibrate generator phrasing; never in evaluated set |
| **Avocado** | anonymised real Outlook mailboxes, 26k meeting schedules | WF2 (style) | Real (anonymised), LDC-licensed | Style reference only; licence + PII hurdles — likely skip |
| **ATIS / MultiWOZ** | airline / restaurant-hotel-taxi booking dialogues | weak | synthetic-ish | Mostly off-domain; mention as related work, not data |

**Bottom line on external data:**
- **WF1 (summarisation)** has a genuinely usable public benchmark: **AMI / QMSum**. Run
  on it for an external-validity number.
- **WF2/WF3 (scheduling/forms)** has no enterprise-admin public benchmark; **SGD** is the
  nearest synthetic option (different domain) — use it as a secondary slot-extraction
  check. The enterprise-admin scenarios (leave/expense/IT ticket) only exist in **your
  generated set**.
- **WF4 (drafting)** has no clean external benchmark → synthetic generation only; Enron
  as style reference (with ethics note).

---

## 5. Recommended combined evaluation design

Two-track, which examiners read as rigorous:

1. **Internal (primary):** the synthetic generator (§3), reported **per difficulty
   tier**, per workflow. Gives controlled, labelled, ethics-clean coverage of all four
   workflows — including the admin-specific scenarios no public set has.
2. **External (validity):** AMI/QMSum for WF1, SGD for WF2/WF3 slot extraction. Shows
   the system isn't only good on its own data distribution.

Report both; discuss the gap between them as a limitation/threat-to-validity. That
contrast is itself an important validity finding.

---

## 6. Ethics checklist (confirm authorisation before using real corpora)

- Synthetic generator + SGD/AMI/QMSum: low risk, no personal data → fine for the
  evaluated core.
- Enron/Avocado as **style reference**: you are *reading* real (anonymised) data to tune
  a generator, not redistributing or evaluating on it. State this explicitly in the
  ethics section and confirm it's within your approved scope **before** touching them.
- Keep the synthetic org fixture (names, emails) obviously fictional (`@example.com`).
