# WF3 — Evidence-first Expense Review Assistant (Design Spec)

> **Status:** evidence-first two-role workflow implemented; final automated/build verification
> passed 2026-08-23. The authoritative formal result is V3.4.3 under `Part A Final`.
> This file began as a 2026-07-01 design record, so code remains authoritative where older
> target prose disagrees. Multi-currency (§D.1), deterministic reasoning (§L.1–L.3), and the
> evidence-first workflow (§M) are built. Evaluation numbers live in
> [`results.md`](results.md).
>
> **Role:** the fine-grained design contract for WF3, part of the 2026-07-01 re-scope
> (integrated into `docs/workflow_design.md`). Companion constraints: CLAUDE.md §2/§3/§4.4.
>
> **Scope decision:** WF3 is not intended to become a complete finance platform. Its
> research focus is an **evidence-first, human-in-the-loop expense review assistant**:
> the model prepares evidence and drafts; employees and approvers make the decisions.
> The former `leave_request` demonstration was removed from runtime code on 2026-08-13
> because no production route or UI used it. §K remains only as historical design rationale.

---

## A. Positioning & two entry modes

WF3 uses one evidence-first pipeline (schema → validation → policy → record store →
approval gate → frontend):

| Form type | Input modality | Extractor | Role |
|---|---|---|---|
| **expense_claim** | **Image** (receipt photo) + optional text note | **Vision LLM** | Flagship (multimodal) |

The rest of this spec details expense; §K records the discarded leave experiment.

---

## B. End-to-end pipeline (LLM vs CODE)

```
1. CODE  ingest        receive receipt image (+ optional note); inject uploader / now
2. LLM   extract       receipt image -> structured fields + raw extraction snapshot
3. CODE  load schema   fetch expense_claim field definitions from the registry
4. CODE  validate+policy  type/format checks, required-field detection, run policy rules -> flags
5. CODE  assemble      prefilled expense draft + flags + receipt-image reference
   ───────────────────  ★ APPROVAL GATE (human reviews against the original image) ★
6a. approve → CODE re-validate → (no hard-block) INSERT into expense DB (status=approved)
              + decrement budget + attach receipt + auto-generate approval note
6b. edit    → user corrects fields → back to step 4 (re-validate) → then approve
6c. reject  → INSERT (status=rejected) + auto-generate rejection reason (from flags)
7. CODE  log           append to audit trail
```

**Hard rule (CLAUDE.md §4.4):** the LLM only *reads the receipt*. Every threshold
decision, budget/duplicate lookup, and DB write is deterministic CODE. The policy engine
**flags with reasons; it does not auto-reject** — the human decides (CLAUDE.md §2).

---

## C. Vision extraction schema (what the vision LLM outputs)

The vision LLM outputs only what is visible on the receipt — no policy judgement:

```json
{
  "vendor": "Café Aurora",
  "date": "2026-06-28",
  "amount": 85.00,
  "currency": "GBP",
  "tax": 7.08,
  "line_items": [
    {"desc": "Set dinner x2", "amount": 78.0},
    {"desc": "Service",       "amount": 7.0}
  ],
  "category_guess": "meals",
  "field_confidence": {"vendor": 0.95, "date": 0.90, "amount": 0.72, "category_guess": 0.60}
}
```

`field_confidence` is **model-reported diagnostic metadata only**. It may be logged for
analysis, but it must not decide whether a field is accepted, highlighted, approved, or
rejected, and the UI must not present it as a calibrated probability. A model can be
confident and wrong.

The human-facing verification status is instead derived from observable evidence:

- **Verified** — independent readings agree and deterministic checks pass.
- **Review required** — readings disagree, the employee edited a critical field, image
  quality is poor, or a deterministic/policy check raised a flag.
- **Unresolved** — required evidence is absent or invalid.

Keep three concepts separate: **extraction reliability** (was the field read correctly?),
**policy risk** (is the expense allowed?), and **workflow completeness** (is the claim
complete enough to decide?).

---

## D. Expense form schema (what gets stored) + one deliberate design point

Based on the existing registry `expense_claim`, lightly extended:

| Field | Source | Required |
|---|---|---|
| employee_name | uploader context | ✓ |
| vendor | vision extraction | ✓ |
| date | vision extraction | ✓ |
| amount | vision extraction | ✓ |
| currency | vision extraction (default GBP) | ✓ |
| category | vision guess + human confirm | ✓ |
| business_purpose | optional note / human-filled | ✓ |
| receipt_ref | attached by CODE | ✓ |

**Deliberate point:** `business_purpose` is **never printed on a receipt** — it is
necessarily missing and the human must supply it. This creates a genuine
"missing field → human intervention" step, so review is real work, not a rubber stamp.

### D.1 Multi-currency: two amounts, one source of truth

Receipts arrive in any supported currency, so each claim carries both amounts, following
the **transaction-currency / functional-currency** model standard in enterprise expense
systems (SAP Concur, Expensify, Workday):

| Stored | Meaning | Role |
|---|---|---|
| `amount` + `currency` | exactly what the receipt prints | **source of truth — never overwritten** |
| `amount_gbp` | converted, rounded to 2dp | derived; what limits compare and reports sum |
| `fx_rate`, `fx_rate_date`, `fx_table_version` | the rate applied and where it came from | makes any row re-derivable and auditable |

Three consequences follow, and each is load-bearing:

1. **The review form shows the original.** The human's task at this gate is to verify the
   form *against the receipt image*; a form reading £14.88 against a receipt reading €17.50
   would make that impossible — and the M4 result (a reviewer who checks each field against
   the source catches 100% of injected errors) depends on it being possible. The GBP value
   appears beside the field as a muted, clearly-derived hint, with its rate.
2. **The conversion is frozen at submit time**, not recomputed on read. Under IAS 21 a
   foreign-currency transaction is recorded at the rate on its date and is not remeasured
   when rates move; practically, this stops an edit to the rate table from restating claims
   already in the ledger, the budget they consumed, or published eval numbers.
3. **Limits are GBP-denominated, so conversion happens before comparison.** A €78 meal is
   under a £50 cap read at face value and over it once converted — the `foreign_currency`
   eval tier exists to exercise exactly this.

Rates are a frozen snapshot of ECB reference rates (see `backend/money.py`); nothing is
fetched at runtime, since a live feed would make evaluation unreproducible and would put a
third-party service inside the evaluated core. Not modelled: effective-dated rate ranges,
a rate provider, and realised FX gain/loss between expense date and reimbursement date.

---

## E. Policy engine — rules with concrete thresholds

Policy config (default values below; tunable):

- **Per-category limits:** meals £50/day · accommodation £150/night · office supplies
  £200 · software £500 · travel (no hard cap) · other £100
- **Per-person annual expense quota** and **per-department budget** (see the org fixture).
- **Approver:** the user (administrative coordinator) is the sole approver in the demo.

| # | Rule | Trigger | Hard-block / Soft-flag | Example message |
|---|---|---|---|---|
| 1 | Over category limit | amount > category limit | soft | "£85 exceeds meals £50/day limit" |
| 2 | Budget / quota exhausted 🗄 | dept budget remaining < amount, or personal annual quota insufficient | **hard** | "Engineering Q3 budget has £0 remaining" |
| 3 | Duplicate claim 🗄 | same vendor + date + amount already in DB | **hard** | "Duplicate of claim #1234" |
| 4 | Documentation mismatch | independent readings disagree / extracted total ≠ entered amount / required evidence absent | soft (configurable to hard) | "Receipt reading and submitted amount disagree" |

🗄 = requires the records DB. **Default: soft-flag (agent surfaces, human decides); only
②③ hard-block** (prevents the DB write even on approve; reuses the existing
`blocked_missing_required` mechanism).

**Trimmed 2026-07-01 — was 9 rules, now 4.** *(As built: six — `non_reimbursable` and
`unknown_currency` were added later; see `backend/workflows/policy.py`.)* These carry the
thesis: two need the DB
(real governance depth), one ties to the multimodal HITL value (documentation mismatch
catches OCR misreads), one is basic policy (over-limit). A missing `business_purpose` is
handled by ordinary **required-field detection**, not a policy rule. **Removed as padding**
(optional/future): non-reimbursable-keyword, vague-purpose, late-submission, high-value
routing flag, unauthorised-vendor. No multi-level approval routing (single approver).

---

## F. Record & state transitions

Written to the unified `submissions` store:

```json
{
  "id": "exp-000042",
  "type": "expense_claim",
  "status": "approved",
  "fields": {
    "employee_name": "Alice", "vendor": "Café Aurora", "date": "2026-06-28",
    "amount": 85.0, "currency": "GBP", "category": "meals",
    "business_purpose": "Client dinner"
  },
  "receipt_ref": "receipts/exp-000042.png",
  "policy_flags": [{"rule": "over_limit", "severity": "hard", "msg": "exceeds meals £50/day"}],
  "submitted_by": "alice",
  "reviewed_by": "coordinator",
  "decision_reason": null,
  "created_at": "…", "updated_at": "…",
  "audit": ["…"]
}
```

Historical lifecycle: `draft → approved / rejected`.
The target lifecycle is `draft → submitted → needs_information → resubmitted →
approved / rejected`. Employee corrections create auditable revisions; the approver
reviews or edits every drafted information request and decision reason. See §M.4 for the
planned transition and atomic/idempotent approval requirements.

---

## G. Data

**① Synthetic receipt generator (PRIMARY)** — reverse generation, extended to images:

```
CODE sample gold (fictional vendor + amount + date + category + line items)
  → render as a receipt IMAGE
  → vision LLM extracts
  → compare to gold (label-by-construction)
```

- Fictional vendor list (e.g. Café Aurora / TechMart Ltd / CityCab — obviously fake).
- **Difficulty tiers:** clean · skewed/rotated · low-res/blurred · handwritten-ish ·
  cropped/partial · **non-receipt (out-of-scope → must refuse)** ·
  **policy-violating (over-limit / duplicate / late → exercises the policy engine + HITL)**.
- Ethics-clean, reproducible (seed + generator_version).

**② External validity:** **SROIE** (company/address/date/total) and **CORD** (line
items) — test vision extraction on *real* receipt photos. Their labels cover only a
subset of the form fields, so they validate the extraction step, not the full form.

**③ Seed expense records:** a few pre-approved claims in the DB so duplicate detection
has something to catch and budgets are already partly consumed.

---

## H. Frontend (the 🧾 Expenses domain page)

Target three views (planned; retain the current summary-only queue as the baseline):

- **Employee Upload + Review:** **left = original receipt · right = editable prefilled
  form**. Display Verified / Review required / Unresolved with reason codes, never a
  model-confidence threshold. The employee corrects and submits the claim.
- **Approver Evidence Workspace:** show the immutable receipt beside the model-first value,
  employee-submitted value, deterministic/policy checks, and plain-language reasons.
  Actions are `[Approve] [Request information] [Reject]`.
- **Ledger:** list of all expense records (status / amount / flags). After approve the
  record appears immediately with status=approved and the budget bar updates — the
  consequence of approval is visible.

---

## I. Models

Vision extraction needs a multimodal model — Llama-3.3-70B is text-only and cannot do this
step. Model is an RQ2 evaluation variable (CLAUDE.md §4.5).

**As built:** Groq **Llama 4 Scout** until Groq retired it on 2026-07-17, then
**`qwen/qwen3.6-27b`** — the only vision-capable model left on the account (the gpt-oss
models Groq recommended as replacements are text-only). Scout's numbers were frozen before
retirement, so the migration doubles as the RQ2 vision comparison: neither model dominates,
and the auto-approve error rate is identical at 0.131 — swapping the model redistributes
errors rather than removing them. See [`results.md`](results.md) §2.7.

---

## J. Focused evaluation

WF3 evaluation has two deliberately separate audiences.

### J.1 User-facing operational analytics

Keep the dashboard small and decision-oriented:

1. spend by category in frozen GBP equivalent;
2. foreign-currency exposure: claim count plus GBP equivalent by currency;
3. lifecycle funnel and median time for submitted / needs information / resubmitted /
   approved / rejected;
4. department budget consumption.

Never sum raw amounts across currencies. Retain the original amount/currency, but use
`amount_gbp` for cross-currency totals.

### J.2 Model and workflow evaluation

The existing **8.3% harmful-record rate is a system-level baseline result**, not evidence
that human reviewers personally miss 8.3% of cases. Freeze the current summary-only UI,
dataset, model configuration, screenshots, and logging before optimisation. Compare:

- **A — summary-only review (baseline);**
- **B — receipt-visible evidence workspace (primary intervention);**
- **C — evidence workspace + risk-adaptive verification (optional).**

Use the same controlled claims and error injections across conditions. The four primary
HITL outcomes are:

1. harmful-error detection rate / false-approval rate (**primary**);
2. review time;
3. false rejection or unnecessary intervention;
4. correctness of request-information decisions.

Continue reporting extraction accuracy, policy-flag correctness, arithmetic-consistency
detection, non-receipt refusal, and performance by image/currency tier as supporting
diagnostics—not as an unbounded list of equal-weight headline metrics.

---

## K. Historical leave experiment — removed from runtime

This was the proposed generalisation: swap only step B.2 for **text LLM extraction** (no
image), with schema `leave_request`
(start/end date, leave_type, reason). Policy rules become **leave-balance check 🗄 +
duration threshold**. Validation, record store, approval gate, the form UI, and
auto-generated reasons would be reused. It never gained a production API or UI and was
deleted during production-path consolidation; it must not be described as shipped.

---

## L. The reasoning layer — planned enhancements (design, 2026-07-21)

> **Status: BUILT (2026-07-21).** L.1–L.3 are implemented and tested — `policy.check_arithmetic`
> + `policy.check_similar_image` (soft flags `arithmetic_mismatch` / `similar_receipt`),
> `agent/image_hash.py` (dHash), `receipt_to_fields` carries `line_items`+`tax`,
> `/api/expense/evidence/extract`
> computes `image_phash`, and the `inconsistent` eval tier + M7 (`reasoning_consistency`) in
> `evals/`. L.4 stays deferred. The design narrative below is retained as the rationale.
>
> Motivated by *From Recognition to Reasoning*
> (arXiv 2605.22413) and by how commercial systems (Concur, Expensify, Ramp) actually catch
> fraud. Frames WF3 as three layers — **perception → reasoning → governance** — where
> perception (vision extract) and governance (policy + human gate) already exist and the
> **reasoning layer in the middle is the gap**. The paper's finding is the hook: MLLMs can
> read every field correctly yet fail to validate that the fields are *mutually consistent*.
> Each item below stays inside the project's existing philosophy — the LLM reads, then
> **deterministic CODE checks** — so nothing here needs a bigger model or more quota.

### L.1 Arithmetic self-consistency (primary — pure code, zero quota)

The vision step already emits `line_items[]` and `tax` (§C), but nothing downstream uses
them: `receipt_to_fields` maps only the scalar fields. So the model's own reading is never
checked against itself. Add that check.

- **Plumb the signals through.** `receipt_to_fields` carries `line_items` and `tax` onto the
  draft (kept out of the required-field set — they are evidence for checks, not fields the
  human must fill). They flow to `validate_and_complete_expense`, the same way
  `extracted_amount` already does.
- **New policy check `check_arithmetic(fields, line_items, tax)`** in `policy.py`:
  - **line-item sum**: if `line_items` is non-empty, `sum(item.amount)` should reconcile to
    `amount` — either `sum == amount` (tax-inclusive lines) or `sum + tax == amount`. Accept
    either within a small tolerance (rounding); otherwise raise **`arithmetic_mismatch`**
    (soft) with the discrepancy, e.g. *"line items total £42.00 but claim total is £52.00"*.
  - **tax plausibility**: if `tax` is present, `0 ≤ tax ≤ amount` and `tax` is not an
    implausible share of `amount` (e.g. > 40%). Same soft flag with a distinct message.
- **Severity: soft.** Consistent with §2 — code flags with a reason, the human decides. A
  mismatch is often a model misread (a line dropped), which is exactly the case the human
  verifies against the image; occasionally it is a genuinely odd receipt.
- **Why this is the headline change.** It is the reasoning layer in one rule: the LLM reads
  the numbers, deterministic code proves they add up. It is pure code (no quota), it maps
  directly onto the cited benchmark, and it turns three currently-wasted extraction fields
  into a fraud/error signal.

### L.2 Perceptual-hash near-duplicate detection (secondary — pure code)

The current `duplicate` rule is an exact match on `vendor + date + amount`, so it misses the
realistic fraud: the **same receipt photographed twice** (slightly different angle), or
**resubmitted with one field edited**. Commercial systems fingerprint the *image*.

- **Compute a perceptual hash at extract time.** An 8×8 difference-hash (dHash) over the
  greyscale image — ~15 lines with Pillow, **no new dependency** (`imagehash` is optional).
  Robust to small crops, rotation and rescale; a 64-bit hash compared by Hamming distance.
- **Carry it onto the record.** `store_image_phash` on the submission (like the frozen FX
  fields in §D.1). The extract endpoint has the image bytes; the submit path does not, so
  the hash is computed at extract and passed through — the same pattern the amount takes.
- **New policy check `check_similar_image`**: Hamming distance to any approved claim's hash
  below a threshold (≈ 6/64) → **`similar_receipt`** (soft) — *"visually ~95% identical to
  approved claim exp-000123"*. Complements, does not replace, the exact-match hard rule:
  exact field-match stays **hard** (certain duplicate, blocks the write); visual similarity
  is **soft** (probable, human confirms).

### L.3 Reasoning-consistency evaluation tier (the benchmark method, made ours)

L.1 needs a test set, and building one reproduces the cited paper's core method on our own
controllable data — an evaluation angle a plain OCR+rules demo does not have.

- **New generator tier `inconsistent`** in `receipt_data.py`: render a normal receipt, then
  inject an arithmetic fault by construction — the printed TOTAL ≠ `sum(line_items)` (drop a
  line from the total, or perturb it by a controlled delta). `gold` records both the printed
  (wrong) total and the true line-item sum; `meta.expected_flags = ["arithmetic_mismatch"]`.
- **New metric — reasoning-consistency detection rate** (call it M7): of the `inconsistent`
  cases, what fraction does `check_arithmetic` flag? This is *code* detection, not model
  detection, so it should approach 1.0 — the point is the **contrast**: the vision model
  reads the fields at high accuracy (M1) yet is blind to the inconsistency between them
  (the paper's finding), and the deterministic reasoning layer is what recovers it. That
  contrast, on reproducible synthetic data, is the write-up result.
- `receipt_score.py` already scores per tier and per policy flag, so this reuses the harness;
  only the tier and one aggregate are new.

### L.4 Deliberately deferred

- **Image-tampering / forgery detection (ELA, EXIF, copy-move).** Attractive and real, but
  **not testable on this project's synthetic data**: Pillow-rendered PNGs have no JPEG
  recompression history for ELA and no camera EXIF. Doing it honestly would need a separate
  tampered-image corpus. Keep as **future work / a clearly-labelled non-evaluated feasibility
  demo**, not a main line.
- **VAT reclaim, per-diem tables, itemisation splitting, attendee counts.** Real Concur
  rules, but they are *more rules of the same kind* — low marginal novelty for a
  multimodal + HITL thesis. Add only if a specific demo needs one.

### L.5 Data note

External real-receipt data stays at the single CORD anchor (n=40, amount only). Public
receipt datasets face a **privacy–utility tradeoff** — CORD redacts store/customer PII, so
only totals are cleanly usable, and SROIE has redactions too — which is *itself* the
argument for the synthetic generator as the primary evaluation (complete, label-by-
construction gold, no PII). If stronger external validity is ever wanted, **ReceiptBench
(2025)** is the reserve candidate — verify its PII redaction and licence before adopting
(see `data_strategy.md`).

## M. Evidence-first optimisation implementation (agreed 2026-07-30; built)

> **Status:** implemented. Code is authoritative for exact current behaviour. The scope is deliberately
> narrow: improve the accuracy, efficiency, explainability, and auditability of human expense
> review. It is not a plan to build an end-to-end finance or ERP product.

### M.1 Research contribution and boundary

WF3's differentiating contribution is:

> An evidence-first, risk-adaptive human review assistant that shows what the model read,
> what the employee changed, what deterministic checks found, and why human attention is
> required before an expense decision is executed.

The LLM may extract fields and draft communications. Deterministic code validates and
executes. Employees own claim corrections; approvers make the final decision. Excel export,
additional finance rules, and more model calls are supporting features rather than the
research contribution.

### M.2 Priority 0 — freeze the existing baseline before changing it

Preserve the current summary-only approver queue as experimental condition A. Record:

- code revision, model/configuration, frozen test set, and evaluation seed;
- screenshots and a short interaction description;
- decision start/end time, approve/reject/request-information action, fields inspected or
  changed, and the final correctness label.

The current 8.3% harmful-record result motivates the intervention but does not measure human
review performance. Later testing must measure whether reviewers actually detect those
errors under the baseline and optimised interfaces.

### M.3 Priority 1 — immutable receipt evidence and approver access

Persist the uploaded receipt instead of retaining only a temporary browser preview. Store:

| Evidence | Purpose |
|---|---|
| `receipt_id` and stable `receipt_ref` | bind the claim to its source image |
| SHA-256, MIME type, byte size, uploaded-at | integrity and audit metadata |
| `extraction_snapshot` | immutable first model output |
| `submitted_snapshot` | employee-confirmed or corrected values |
| actor and timestamp for each change | reconstruct the human process |

The approver workspace must display the original receipt with zoom/rotate beside a field
comparison: model-first value, employee-submitted value, current verification status,
policy flags, and plain-language reason codes. The image and first extraction are immutable.

### M.4 Priority 2 — complete the two-role lifecycle

Replace the two-terminal-state design with:

`draft → submitted → needs_information → resubmitted → approved / rejected`

- The employee verifies the prefilled form, supplies business purpose, edits it, and submits.
- The approver does not silently rewrite the employee's claim.
- For missing or incorrect evidence, the approver selects concrete issues and edits an
  LLM-drafted information request; the employee creates a new revision and resubmits.
- Rejection requires a human-reviewed reason.
- Approving a soft flag requires explicit per-flag acknowledgement and an override reason.
- Approval must be transactional and idempotent so a retry cannot create two records or
  decrement the same budget twice.

### M.5 Priority 3 — evidence-based verification, not self-confidence

Retain model-reported confidence only in diagnostic logs. Do not use it as a decision
threshold or display it as probability-like certainty.

Add a structurally independent second read for the critical fields `amount`, `currency`,
`date`, and `vendor`; do not spend a second model call on every field. Combine:

- agreement/disagreement between the two reads;
- type and format validation;
- arithmetic consistency (built in §L.1);
- receipt image quality indicators;
- employee edits to critical fields;
- exact and perceptual duplicate evidence (the latter built in §L.2);
- policy and missing-evidence checks.

Expose only `Verified`, `Review required`, or `Unresolved`, with the concrete reasons that
produced the state. Extraction reliability, policy risk, and workflow completeness remain
separate signals; a correctly read expense can still violate policy.

OCR is not required for this iteration. It may later provide searchable text, bounding boxes,
field highlighting, and an independent cross-check, but it must not silently become a new
single source of truth.

### M.6 Priority 4 — correctness fixes required alongside the UI

Before evaluating the intervention:

1. serialise the 64-bit perceptual hash as a fixed-length hexadecimal string so JavaScript
   does not lose bits beyond its safe-integer range;
2. include currency in exact-duplicate matching and normalise vendor text before comparison;
3. preserve and re-check `line_items`, `tax`, and the raw extracted amount at submit/approve;
4. make documentation-mismatch messages currency-aware rather than hard-coding GBP;
5. require rejection reasons and explicit per-flag override reasons;
6. re-run deterministic checks atomically at final approval.

### M.7 Priority 5 — controlled multi-currency data

Use public and synthetic data for different purposes. Public CORD/SROIE samples provide
partial external validity only for fields with explicit labels; masked vendor/date/payment
fields and absent currency labels must not be guessed or scored. Dataset-level country or
currency context may be recorded separately, but not treated as per-receipt extraction gold.

Expand the reproducible synthetic full-schema set beyond the current small foreign-currency
tier. Cover GBP, EUR, USD, CNY, JPY and at least one ambiguous dollar currency (CAD/AUD/SGD),
including ISO codes, symbol-only values, missing/conflicting currency, `1,234.56` versus
`1.234,56`, and zero-decimal JPY. Keep evaluation strata balanced; keep demo data plausibly
UK-skewed. Freeze the FX table/version. Never sum raw amounts across currencies.

### M.8 Priority 6 — focused operational analytics

Keep only decision-useful views:

1. category spend in frozen GBP equivalent;
2. currency exposure showing both claim count and GBP equivalent;
3. approval lifecycle and median handling time;
4. department budget consumption.

These are user analytics, not model evaluation. Model/workflow charts belong in the
evaluation view and project report: field error by image/currency tier, verification-state
confusion matrix, errors caught by employee versus approver, and baseline versus evidence-UI
false approvals and review time.

### M.9 Secondary implementation after the core intervention

- Multi-receipt **Expense Packet** grouped by project or trip.
- Excel audit bundle with Claims, Line Items, Policy Flags, Review History, Summary, and an
  Evidence Index. This improves operational usefulness but is not the principal novelty.
- A `needs_receipt` / missing-receipt declaration route where organisational policy permits
  reimbursement without a receipt.

### M.10 Future work — explicitly outside the current build

- OCR bounding boxes and click-to-highlight evidence;
- a larger privacy/licence-checked external receipt benchmark;
- tampered or AI-generated receipt forensics;
- historical/live exchange-rate providers;
- multi-level approvals, corporate-card/ERP integration, and purchase-order matching;
- policy RAG only if policies become large or frequently changing;
- cross-document checks against itineraries, bookings, or card transactions;
- advanced leave rules such as bank holidays, half-days, overlap, and team capacity.

Do not implement these before the evidence workspace, lifecycle, correctness fixes, and
baseline instrumentation are complete. They would increase breadth without strengthening
the central human-in-the-loop research claim.

## Open config values to confirm

- Per-category limits — placeholder values above.
- Expense categories: meals / travel / accommodation / supplies / software / other.
- Currency: GBP default.
- Which rules are hard-block (currently ②③) vs soft-flag.
