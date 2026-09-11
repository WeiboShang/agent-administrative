// Thin typed client over the existing FastAPI /api/expense endpoints (backend unchanged).

export type Flag = { rule: string; severity: 'soft' | 'hard'; message: string }
export type Actor = { id: string; name: string; is_approver: boolean }

export type Options = {
  departments: string[]
  categories: string[]
  payment_methods: string[]
  currencies: string[]
  actors: Actor[]
  vision_model: string
  fx_rates: Record<string, number>
  fx_rate_date: string
  fx_rate_source: string
}

export type LineItem = { desc?: string | null; amount: number }

export type ExpenseFields = {
  employee_name?: string | null
  department?: string | null
  vendor?: string | null
  date?: string | null
  amount?: number | string | null
  currency?: string | null
  payment_method?: string | null
  category?: string | null
  business_purpose?: string | null
  line_items?: LineItem[]
  tax?: number | null
  image_phash?: number | string | null
}

export type Vision = {
  vendor?: string | null
  date?: string | null
  amount?: number | null
  currency?: string | null
  tax?: number | null
  line_items?: LineItem[]
  category_guess?: string | null
  payment_method?: string | null
  field_confidence?: Record<string, number>
  not_a_receipt?: boolean
  raw_text?: string
  [k: string]: unknown
}

export type ReceiptEvidence = {
  receipt_id: string
  receipt_ref: string
  receipt_sha256: string
  receipt_mime_type: string
  receipt_byte_size: number
  receipt_uploaded_at: string
  image_phash: string
}

export type EvidenceExtractResult = {
  vision: Vision
  fields: ExpenseFields
  missing: string[]
  completeness: number
  flags: Flag[]
  extraction_snapshot: Vision
  critical_second_read: Pick<Vision, 'vendor' | 'date' | 'amount' | 'currency'>
  evidence: ReceiptEvidence
}

export type VerificationState = {
  state: 'verified' | 'review_required' | 'unresolved'
  reasons: string[]
}

export type SubmitResult = {
  status: 'submitted' | 'blocked_missing_required' | string
  record_id?: string
  flags?: Flag[]
  missing?: string[]
}

export type QueueItem = {
  id: string
  type: string
  employee_name?: string
  submitted_by?: string
  amount?: number
  currency?: string
  amount_gbp?: number
  vendor?: string
  category?: string
  business_purpose?: string
  department?: string
  payment_method?: string
  policy_flags?: Flag[]
  status?: string
  version?: number
  extraction_snapshot?: Vision
  submitted_snapshot?: ExpenseFields
  verification_states?: Record<string, VerificationState>
  information_request?: { issues: string[]; text: string; reviewed_by: string; timestamp: string }
  receipt_id?: string
  receipt_ref?: string
  evidence_origin?: string
  created_at?: string
  updated_at?: string
  submitted_at?: string
  resubmitted_at?: string
  decided_at?: string
  // leave
  start_date?: string
  end_date?: string
  leave_type?: string
  reason?: string
}

export type DecideResult = {
  status: 'approved' | 'rejected' | 'blocked_policy' | 'self_approval_blocked' | string
  record_id?: string
  flags?: Flag[]
  overridden_flags?: Flag[]
}

export type LedgerRecord = {
  id: string
  status: string
  employee_name?: string
  vendor?: string
  amount?: number
  currency?: string
  amount_gbp?: number
  category?: string
  department?: string
  policy_flags?: Flag[]
  submitted_at?: string
  resubmitted_at?: string
  decided_at?: string
}

export type LedgerResult = {
  records: LedgerRecord[]
  budgets: Record<string, { total: number; remaining: number }>
  approved_total_gbp: number
}

export type RoutedDraft = {
  id: string
  status: string
  type?: string
  title?: string
  current_seed_fields?: Record<string, unknown>
  missing_required?: string[]
  evidence_refs?: Array<Record<string, unknown>>
  origin?: { thread_id?: string; action_id?: string; source_path?: string }
}

export type NoteResult = {
  status: 'draft' | 'not_decided' | 'error' | string
  note_id?: string
  subject?: string
  body?: string
  detail?: string
  raw?: string
}

/* ── WF1 inbox ── */
/** Soft caveat attached to a detected action by a deterministic check (e.g. retraction). */
export type ActionFlag = { rule: string; severity: 'soft' | 'hard'; message: string }
export type SourceEvidence = { message_id: string; span: string; grounded: boolean }
export type ThreadMessage = {
  message_id: string
  sender: string
  sent_at?: string
  body: string
  attachment_ids: string[]
}
export type ThreadAttachment = {
  attachment_id: string
  filename: string
  mime_type: string
  byte_size?: number | null
  evidence_type: string
}

export type ThreadAction = {
  action_id: string
  version: number
  operation: 'create' | 'amend' | 'cancel'
  target_action_id?: string | null
  action_type: string
  model_confidence: number
  model_seed_fields: Record<string, unknown>
  current_seed_fields: Record<string, unknown>
  source_evidence: SourceEvidence[]
  field_sources: Record<string, SourceEvidence>
  attachment_ids: string[]
  missing_fields: string[]
  rationale: string
  status: 'pending' | 'proposed' | 'edited' | 'routed' | 'dismissed' | 'superseded'
  routed_to?: string
  downstream_status?: string | null
  downstream_type?: string | null
  target_record_id?: string | null
  previous_versions?: Array<Record<string, unknown>>
  created_at?: string | null
  updated_at?: string | null
  flags?: ActionFlag[]
}
export type MemoItem = {
  memo_id: string
  version: number
  text: string
  model_text: string
  current_text: string
  item_type: 'todo' | 'important_date'
  date_phrase?: string | null
  resolved_date?: string | null
  date_relation?: string | null
  is_completed: boolean
  status: 'active' | 'completed' | 'dismissed'
  position: number
  source_evidence: SourceEvidence[]
  flags?: ActionFlag[]
}
export type AuditEvent = {
  event_id: string
  actor: string
  action: string
  timestamp: string
  record_version?: number | null
  reason_code: string
  action_id?: string
  memo_id?: string
}
export type Thread = {
  id: string
  status: string
  subject?: string
  source?: string
  raw_text?: string
  received_at?: string
  summary?: string
  key_points: string[]
  messages: ThreadMessage[]
  attachments: ThreadAttachment[]
  detected_actions: ThreadAction[]
  memo_items: MemoItem[]
  audit_events: AuditEvent[]
  last_triaged_message_id?: string | null
  has_untriaged_messages: boolean
}
export type TriageResult = {
  status?: string
  summary?: string
  key_points?: string[]
  detected_actions?: ThreadAction[]
  memo_items?: MemoItem[]
  error?: string
}
export type RouteResult = {
  routed?: string
  status?: string
  missing?: string[]
  record_id?: string
  action_status?: string
  action_id?: string
  version?: number
  error?: string
}

/* ── WF2 scheduling ── */
export type Participant = { name: string; resolved?: boolean }
export type SchedEvent = {
  title?: string | null
  date?: string | null
  time?: string | null
  duration_minutes?: number | null
  location?: string | null
  mode?: string | null
  agenda?: string | null
  start?: string | null
  end?: string | null
  participants?: string[]
  participant_details?: Participant[]
  slot_provenance?: Record<string, string>
  [k: string]: unknown
}
/** A free slot the CODE found — offered only when a clash needs resolving. */
export type FreeSlot = { date: string; start: string; end: string }

export type RunSchedResult = {
  extraction: Record<string, unknown>
  event: SchedEvent
  missing: string[]
  flags: Flag[]
  alternatives?: FreeSlot[]
}
export type RoutedDraftReview = RunSchedResult & {
  draft_id: string
  draft_status: string
  source_path?: string | null
}
export type DecideSchedResult = {
  status: string
  record_id?: string
  ics?: string
  overridden_flags?: Flag[]
  flags?: Flag[]
  alternatives?: FreeSlot[]
  message?: string
  notifications?: unknown[]
  missing?: string[]
  /** Interactive calendar-provider write. 'skipped' = mock backend / no mapped calendar. */
  calendar_backend?: { status: string; html_link?: string; error?: string }
}
export type CalEvent = {
  id: string
  title?: string
  date?: string
  start?: string
  end?: string
  duration_minutes?: number
  participants: string[]
  location?: string | null
  /** Flags that were live when the human booked anyway (RQ3: override behaviour). */
  overridden_flags?: Flag[]
  /** Fields the human edited before booking — e.g. moving the time to clear a conflict. */
  changed_fields?: string[]
}

const BASE = '/api/expense'

async function unwrap<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = r.statusText
    try {
      const d = (await r.json()) as { detail?: string }
      msg = d.detail ?? msg
    } catch {
      /* non-JSON error body */
    }
    throw new Error(msg)
  }
  return (await r.json()) as T
}

/** POST JSON to a full API path. */
function postJSON<T>(path: string, body: unknown): Promise<T> {
  return fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => unwrap<T>(r))
}

function post<T>(path: string, body: unknown): Promise<T> {
  return postJSON<T>(BASE + path, body)
}

export const api = {
  options: () => fetch(`${BASE}/options`).then((r) => unwrap<Options>(r)),

  extractEvidence: (file: File, employeeName: string) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('employee_name', employeeName)
    return fetch(`${BASE}/evidence/extract`, { method: 'POST', body: fd }).then((r) =>
      unwrap<EvidenceExtractResult>(r),
    )
  },

  submitEvidence: (body: { fields: ExpenseFields; extraction_snapshot: Vision; critical_second_read: Pick<Vision, 'vendor' | 'date' | 'amount' | 'currency'>; evidence: ReceiptEvidence; submitted_by: string; changed_fields: string[]; idempotency_key: string }) =>
    post<SubmitResult & { version?: number }>('/evidence/submit', body),

  evidenceQueue: () => fetch(`${BASE}/evidence/queue`).then((r) => unwrap<{ items: QueueItem[] }>(r)),

  requestExpenseInformation: (recordId: string, body: { reviewed_by: string; expected_version: number; issues: string[]; request_text: string; idempotency_key: string }) =>
    post<SubmitResult & { version?: number }>(`/claims/${recordId}/request-information`, body),

  resubmitExpense: (recordId: string, body: { fields: ExpenseFields; submitted_by: string; expected_version: number; changed_fields: string[]; idempotency_key: string }) =>
    post<SubmitResult & { version?: number }>(`/claims/${recordId}/resubmit`, body),

  decideEvidence: (recordId: string, body: { decision: 'approve' | 'reject'; reviewed_by: string; expected_version: number; reason?: string; acknowledged_flags: string[]; idempotency_key: string }) =>
    post<DecideResult & { version?: number; missing_acknowledgements?: string[] }>(`/claims/${recordId}/decision`, body),

  receiptUrl: (recordId: string) => `${BASE}/claims/${recordId}/receipt`,
  routedExpenseDrafts: () =>
    fetch(`${BASE}/routed-drafts`).then((r) => unwrap<{ items: RoutedDraft[] }>(r)),

  ledger: () => fetch(`${BASE}/ledger`).then((r) => unwrap<LedgerResult>(r)),

  exportLedger: async () => {
    const response = await fetch(`${BASE}/ledger/export.xlsx`)
    if (!response.ok) throw new Error(await response.text())
    const disposition = response.headers.get('Content-Disposition') ?? ''
    const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] ?? 'wf3_receipts.xlsx'
    return { blob: await response.blob(), filename }
  },

  draftNote: (record_id: string) => post<NoteResult>('/draft_note', { record_id }),

  saveNote: (body: { note_id: string; subject: string; body: string }) =>
    post<{ status: string }>('/save_note', body),
}

export const inboxApi = {
  threads: () => fetch('/api/inbox/threads').then((r) => unwrap<{ threads: Thread[] }>(r)),
  triage: (thread_id: string) => postJSON<TriageResult>('/api/inbox/triage', { thread_id }),
  route: (thread_id: string, action_id: string, expected_version: number, acting_user: string) =>
    postJSON<RouteResult>('/api/inbox/route', { thread_id, action_id, expected_version, acting_user }),
  dismiss: (thread_id: string, action_id: string, expected_version: number, acting_user: string) =>
    postJSON<RouteResult>('/api/inbox/dismiss', { thread_id, action_id, expected_version, acting_user }),
  archive: (thread_id: string, acting_user = 'alice') =>
    postJSON<{ status: string }>('/api/inbox/archive', { thread_id, acting_user }),
  addMessage: (thread_id: string, body: { sender: string; body: string; acting_user: string }) =>
    postJSON<{ status: string; message: ThreadMessage }>(`/api/inbox/threads/${thread_id}/messages`, body),
  editAction: (
    thread_id: string,
    action_id: string,
    body: {
      expected_version: number
      fields: Record<string, unknown>
      operation?: ThreadAction['operation']
      target_action_id?: string | null
      attachment_ids?: string[]
      acting_user: string
      reason?: string
    },
  ) => patchJSON<{ status: string; action: ThreadAction }>(
    `/api/inbox/threads/${thread_id}/actions/${action_id}`, body),
  addMemo: (thread_id: string, body: {
    text: string
    item_type: MemoItem['item_type']
    date_phrase?: string | null
    resolved_date?: string | null
    acting_user: string
  }) => postJSON<{ status: string; memo: MemoItem }>(`/api/inbox/threads/${thread_id}/memos`, body),
  editMemo: (thread_id: string, memo_id: string, body: Record<string, unknown> & {
    expected_version: number
    acting_user: string
  }) => patchJSON<{ status: string; memo: MemoItem }>(
    `/api/inbox/threads/${thread_id}/memos/${memo_id}`, body),
}

/* ── Evaluation (backend / researcher facing) ── */
export type EvalRecord = {
  name: string
  at: string
  model?: string
  params?: Record<string, unknown>
  result: Record<string, unknown>
}

export type OutcomeSummary = {
  n: number
  task_outcomes: number
  unsafe_outcomes: number
  task_outcome_rate: number
  unsafe_outcome_rate: number
}

export type OutcomeCheck = {
  name: string
  passed: boolean
  detail: string
  expected?: unknown
  actual?: unknown
}

export type StateRecord = {
  id: string
  store: 'threads' | 'events' | 'submissions'
  type: string
  status: string
  data: Record<string, unknown>
}

export type StateChange = {
  record_id: string
  store: StateRecord['store']
  change: 'created' | 'updated' | 'deleted'
  before?: StateRecord | null
  after?: StateRecord | null
}

export type OutcomeCase = {
  run_id: string
  case_id: string
  workflow: 'wf1' | 'wf2' | 'wf3'
  condition: string
  scenario_tier: string
  task_outcome: boolean
  unsafe_outcome: boolean
  task_checks: OutcomeCheck[]
  safety_checks: OutcomeCheck[]
  mutation_ids: string[]
  state_diff: StateChange[]
  provenance: Record<string, unknown>
}

export type CaseContext = {
  case_id: string
  workflow: OutcomeCase['workflow']
  condition: string
  scenario_tier: string
  gold_final_state: Record<string, unknown>
  model_draft: Record<string, unknown>
  deterministic_checks: Array<Record<string, unknown>>
  review_action: string | Record<string, unknown> | null
  reviewer_type: 'scripted' | 'author' | 'none'
  draft_outcome: boolean | null
}

export type DistributionSummary = {
  n: number
  median: number | null
  q1: number | null
  q3: number | null
}

export type ReviewValueSummary = {
  n: number
  unscored: number
  correct_acceptance: number
  rescued: number
  over_reliance: number
  over_correction: number
  rescue_rate: number | null
  over_reliance_rate: number | null
  over_correction_rate: number | null
  reviewer_types: Record<string, number>
}

export type ReviewEffortSummary = {
  n: number
  action_counts: Record<string, number>
  decision_time_seconds: DistributionSummary
  fields_changed: DistributionSummary
  interactions: DistributionSummary
  information_request_rounds: DistributionSummary
  selected_candidate_rank: DistributionSummary
}

export type OutcomeSuite = {
  summary: OutcomeSummary
  by_workflow: Record<string, OutcomeSummary>
  by_scenario: Record<string, OutcomeSummary>
  by_condition: Record<string, OutcomeSummary>
  by_workflow_condition: Record<string, Record<string, OutcomeSummary>>
  cases: OutcomeCase[]
  case_context: CaseContext[]
  review_value: ReviewValueSummary
  review_effort: ReviewEffortSummary
  review_value_by_workflow: Record<string, ReviewValueSummary>
  review_effort_by_workflow: Record<string, ReviewEffortSummary>
  review_value_by_condition: Record<string, ReviewValueSummary>
  review_effort_by_condition: Record<string, ReviewEffortSummary>
}

export type AuditResult = {
  metrics: {
    total: number
    approved: number
    rejected: number
    edit_rate: number
    override_rate: number
    purpose_refined_rate: number
    flag_influence: {
      with_flag_approve_rate: number
      without_flag_approve_rate: number
      n_with_flag: number
      n_without_flag: number
    }
  }
  charts: Record<string, { label: string; value: number }[]>
  rows: Record<string, unknown>[]
}

export type HumanEvalProtocol = {
  schema_version: string
  title: string
  draft_mode: 'frozen_actual_agent_replay'
  text_model: 'openai/gpt-oss-120b'
  vision_model: 'qwen/qwen3.6-27b'
  seed: number
  manifest_sha256: string
  reviewer_count: 1
  formal_case_count: number
  pilot_case_count: number
  protocol_status: 'pre_freeze_implementation' | 'frozen_pre_collection'
  frozen_at: string | null
  ready_for_collection: boolean
  cache_cases: number
  required_cache_cases: number
  agent_cache_sha256: string | null
  sources_sha256: string
  gold_sha256: string
  temporal_contract: Record<string, string>
  scoring_contract: string
  conditions: Record<'manual' | 'agent_assisted', string>
  analysis_boundary: string
  ethics_gate: string
}

export type HumanEvalSession = {
  session_id: string
  status: 'in_progress' | 'complete'
  created_at: string
  updated_at: string
  ethics_confirmed: boolean
  draft_mode: 'frozen_actual_agent_replay'
  next_case_id: string | null
  counts: Record<string, number>
  pilot_completed: number
  pilot_total: number
  formal_completed: number
  formal_total: number
  final_result?: Record<string, unknown> | null
}

export type HumanEvalCase = {
  case_id: string
  workflow: 'wf1' | 'wf2' | 'wf3'
  condition: 'manual' | 'agent_assisted'
  pilot: boolean
  input: {
    kind: string
    text?: string
    image_url?: string
    claimant_note?: string
    attachments?: Array<Record<string, unknown>>
  }
  reference: Record<string, unknown>
  agent_assistance: Record<string, unknown> | null
  reviewer_visible_checks: Array<Record<string, unknown>>
  form_defaults: Record<string, unknown>
  allowed_decisions: Array<'route' | 'no_action' | 'approve' | 'reject' | 'request_information'>
  draft_mode: 'frozen_actual_agent_replay'
  server_started_at: string
  server_draft_ready_at: string
}

export type HumanInteraction = {
  kind: string
  at?: string
  target?: string
  value?: string | number | boolean | null
}

export type HumanCaseSubmission = {
  decision: 'route' | 'no_action' | 'approve' | 'reject' | 'request_information'
  actions?: Array<{
    action_type: 'schedule_meeting' | 'expense_claim'
    fields: Record<string, unknown>
    attachment_ids: string[]
  }>
  final_fields: Record<string, unknown>
  reason?: string | null
  acknowledge_warnings?: boolean
  interactions: HumanInteraction[]
  timing: {
    case_visible_at: string
    generation_started_at?: string | null
    draft_ready_at?: string | null
    review_started_at: string
    first_interaction_at?: string | null
    decision_at: string
    case_completed_at: string
    hidden_duration_ms: number
  }
  operational_failure?: string | null
}

export type HumanPolicyAlert = {
  rule: string
  severity: 'soft' | 'hard'
  title: string
  message: string
  required_decision?: 'reject' | 'request_information' | null
}

export type HumanPolicyPreflight = {
  case_id: string
  alerts: HumanPolicyAlert[]
  approve_blocked: boolean
  soft_warning_rules: string[]
  suggested_alternatives: Array<{ date?: string; start?: string; end?: string }>
  instruction: string
}

export type HumanEvalHistory = {
  items: Array<{
    at: string
    sha256: string
    result_status: string
    session_id: string
    summary: Record<string, unknown>
  }>
}

export const evalApi = {
  last: () => fetch('/api/eval/last').then((r) => unwrap<Record<string, EvalRecord>>(r)),
  formalOutcomes: () =>
    fetch('/api/eval/part-a/final/latest').then((r) => unwrap<OutcomeSuite>(r)),
  replayFinalPartA: () =>
    postJSON<OutcomeSuite>('/api/eval/part-a/final/replay', {}),
  audit: () => fetch('/api/eval/audit').then((r) => unwrap<AuditResult>(r)),
  receipts: (n: number) => postJSON<Record<string, unknown>>('/api/eval/receipts', { n }),
  triage: (n: number, dataset = 'template') =>
    postJSON<Record<string, unknown>>('/api/eval/triage', { n, dataset }),
  position: (n: number) => postJSON<Record<string, unknown>>('/api/eval/position', { n }),
  pairs: (n: number) => postJSON<Record<string, unknown>>('/api/eval/pairs', { n }),
  retraction: (n: number) => postJSON<Record<string, unknown>>('/api/eval/retraction', { n }),
  underspecified: (n: number) =>
    postJSON<Record<string, unknown>>('/api/eval/underspecified', { n }),
  dateResolution: () => postJSON<Record<string, unknown>>('/api/eval/date_resolution', {}),
  summary: (n: number, judge = 'gemini') =>
    postJSON<Record<string, unknown>>('/api/eval/summary', { n, judge }),
  scheduling: (n: number, dataset = 'template') =>
    postJSON<Record<string, unknown>>('/api/eval/scheduling', { n, dataset }),
  m4: (n: number, error_rate = 0.5) =>
    postJSON<Record<string, unknown>>('/api/eval/m4', { n, error_rate }),
  content: (n: number, judge = 'gemini') =>
    postJSON<Record<string, unknown>>('/api/eval/content', { n, judge }),
  humanProtocol: () =>
    fetch('/api/eval/v5/human/protocol').then((r) => unwrap<HumanEvalProtocol>(r)),
  createHumanSession: (ethics_confirmed: boolean) =>
    postJSON<HumanEvalSession>('/api/eval/v5/human/sessions', {
      reviewer_id: 'evaluation-reviewer',
      ethics_confirmed,
    }),
  humanSession: (sessionId: string) =>
    fetch(`/api/eval/v5/human/sessions/${encodeURIComponent(sessionId)}`).then((r) =>
      unwrap<HumanEvalSession>(r),
    ),
  confirmHumanEthics: (sessionId: string) =>
    postJSON<HumanEvalSession>(
      `/api/eval/v5/human/sessions/${encodeURIComponent(sessionId)}/confirm-ethics`,
      {},
    ),
  startHumanCase: (sessionId: string, caseId: string) =>
    postJSON<HumanEvalCase>(
      `/api/eval/v5/human/sessions/${encodeURIComponent(sessionId)}/cases/${encodeURIComponent(caseId)}/start`,
      {},
    ),
  completeHumanCase: (sessionId: string, caseId: string, body: HumanCaseSubmission) =>
    postJSON<HumanEvalSession>(
      `/api/eval/v5/human/sessions/${encodeURIComponent(sessionId)}/cases/${encodeURIComponent(caseId)}/complete`,
      body,
    ),
  preflightHumanCase: (sessionId: string, caseId: string, final_fields: Record<string, unknown>) =>
    postJSON<HumanPolicyPreflight>(
      `/api/eval/v5/human/sessions/${encodeURIComponent(sessionId)}/cases/${encodeURIComponent(caseId)}/preflight`,
      { final_fields },
    ),
  finalizeHumanSession: (sessionId: string) =>
    postJSON<Record<string, unknown>>(
      `/api/eval/v5/human/sessions/${encodeURIComponent(sessionId)}/finalize`,
      {},
    ),
  humanHistory: () =>
    fetch('/api/eval/v5/human/history').then((r) => unwrap<HumanEvalHistory>(r)),
}

export const scheduleApi = {
  run: (
    input_text: string,
    organizer?: string | null,
    hints?: { date_hint?: string; time_hint?: string },
  ) =>
    postJSON<RunSchedResult>('/api/schedule/run', {
      input_text,
      organizer: organizer ?? null,
      date_hint: hints?.date_hint || null,
      time_hint: hints?.time_hint || null,
    }),
  decide: (body: {
    event: SchedEvent
    decision: 'approve' | 'reject'
    reason?: string
    changed_fields?: string[]
    override_soft_flags?: boolean
    override_reason?: string
  }) => postJSON<DecideSchedResult>('/api/schedule/decide', body),
  calendar: (actor?: string | null) =>
    fetch('/api/schedule/calendar' + (actor ? `?actor=${encodeURIComponent(actor)}` : '')).then((r) =>
      unwrap<{ events: CalEvent[] }>(r),
    ),
  drafts: () =>
    fetch('/api/schedule/drafts').then((r) => unwrap<{ items: RoutedDraft[] }>(r)),
  draft: (draftId: string) =>
    fetch(`/api/schedule/drafts/${encodeURIComponent(draftId)}`).then((r) =>
      unwrap<RoutedDraftReview>(r),
    ),

  decideDraft: (
    draftId: string,
    body: {
      event: SchedEvent
      decision: 'approve' | 'reject'
      reason?: string
      changed_fields?: string[]
      reviewed_by?: string | null
      override_soft_flags?: boolean
      override_reason?: string
    },
  ) =>
    postJSON<DecideSchedResult & {
      draft_id: string
      draft_status: string
    }>(
      `/api/schedule/drafts/${encodeURIComponent(draftId)}/decide`,
      body,
    ),
}
/** PATCH JSON to a full API path. */
function patchJSON<T>(path: string, body: unknown): Promise<T> {
  return fetch(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => unwrap<T>(r))
}


export type SmartSpec = {
  operation?: 'CREATE' | 'UPDATE' | 'RESCHEDULE' | 'CANCEL' | 'REUSE'
  target_event_id?: string
  context_id?: string
  title?: string
  participants?: string[]
  duration_minutes?: number
  date_window?: { start?: string; end?: string }
  exact_time?: string
  location?: string
  mode?: string
  agenda?: string
  soft_preferences?: Record<string, unknown>
  hard_constraints?: Record<string, unknown>
  provenance?: Record<string, string>
}

export type SmartCandidate = {
  candidate_id: string
  date: string
  start: string
  end: string
  label: string
  score: number
  reason_codes: string[]
  warning_codes: string[]
  score_components: Record<string, number>
}

export type SmartWarning = {
  code: string
  message: string
  date?: string | null
  start?: string | null
  end?: string | null
  reason_codes: string[]
}

export type SmartCandidatesResult = {
  spec: SmartSpec
  candidates: SmartCandidate[]
  missing: string[]
  blockers: string[]
  warnings: SmartWarning[]
  validation_token?: string | null
  calendar_version?: string | null
}

export const smartScheduleApi = {
  candidates: (spec: SmartSpec, actor?: string | null) =>
    postJSON<SmartCandidatesResult>('/api/schedule/smart/candidates', { spec, actor: actor ?? 'alice' }),
  execute: (body: {
    spec: SmartSpec
    candidate?: SmartCandidate
    actor?: string | null
    idempotency_key: string
    validation_token?: string | null
    calendar_version?: string | null
    reason?: string
  }) => postJSON<{
    status: string
    record_id?: string
    event?: SchedEvent
    message?: string
    calendar_backend?: { status: string; html_link?: string; error?: string }
  }>(
    '/api/schedule/smart/execute',
    { ...body, actor: body.actor ?? 'alice' },
  ),
  reuse: (eventId: string) =>
    postJSON<{ spec: SmartSpec }>(`/api/schedule/events/${encodeURIComponent(eventId)}/reuse`, {}),
}
