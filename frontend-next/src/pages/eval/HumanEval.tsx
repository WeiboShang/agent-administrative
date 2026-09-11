import { useEffect, useMemo, useRef, useState } from 'react'
import { CheckCircle2, ClipboardCheck, Eye, Plus, Play, ShieldCheck, Trash2 } from 'lucide-react'
import {
  evalApi,
  type HumanCaseSubmission,
  type HumanEvalCase,
  type HumanEvalProtocol,
  type HumanEvalSession,
  type HumanInteraction,
  type HumanPolicyPreflight,
} from '@/lib/api'
import { Button, Card, CardHeader, Empty, Pill, Spinner } from '@/components/ui'

const SESSION_KEY = 'administrative-agent-human-eval-v51-conflict-rescue-session'
const now = () => new Date().toISOString()
const display = (value: unknown) => Array.isArray(value) ? value.join(', ') : value == null ? '' : String(value)

type ActionType = 'schedule_meeting' | 'expense_claim'
type ReviewedAction = { action_type: ActionType; fields: Record<string, unknown>; attachment_ids: string[] }

const scheduleFields = [
  ['title', 'Title', 'text'], ['participants', 'Participants (comma separated)', 'text'],
  ['date', 'Date', 'date'], ['time', 'Time', 'time'],
  ['duration_minutes', 'Duration (minutes)', 'number'], ['location', 'Location', 'text'],
] as const
const expenseFields = [
  ['vendor', 'Vendor', 'text'], ['date', 'Date', 'date'], ['amount', 'Amount', 'number'],
  ['currency', 'Currency', 'text'], ['category', 'Category', 'text'],
  ['business_purpose', 'Business purpose', 'text'],
] as const

function Field({ label, name, value, type, onChange, onEdited }: {
  label: string
  name: string
  value: unknown
  type: 'text' | 'number' | 'date' | 'time'
  onChange: (value: string) => void
  onEdited: () => void
}) {
  return <label className="block">
    <span className="mb-1 block text-[11px] font-semibold uppercase tracking-[0.055em] text-ink-3">{label}</span>
    <input name={name} type={type} value={display(value)} onChange={(event) => {
      onEdited(); onChange(event.target.value)
    }} className="h-9 w-full rounded-lg border border-line-strong bg-surface px-3 text-[13px] text-ink outline-none focus:border-accent focus:ring-2 focus:ring-accent-ring" />
  </label>
}

function JsonPanel({ title, value }: { title: string; value: unknown }) {
  return <details className="rounded-lg border border-line bg-surface-2">
    <summary className="cursor-pointer px-3 py-2 text-[12px] font-semibold text-ink-2">{title}</summary>
    <pre className="max-h-72 overflow-auto border-t border-line p-3 text-[10.5px] leading-4 text-ink-2">{JSON.stringify(value, null, 2)}</pre>
  </details>
}

function Progress({ session }: { session: HumanEvalSession }) {
  const total = session.pilot_total + session.formal_total
  const done = session.pilot_completed + session.formal_completed
  const percentage = total ? Math.round(done / total * 100) : 0
  return <div className="min-w-[250px]">
    <div className="flex justify-between text-[11.5px] text-ink-3"><span>{done}/{total} completed</span><span>{percentage}%</span></div>
    <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-surface-3"><div className="h-full rounded-full bg-accent" style={{ width: `${percentage}%` }} /></div>
    <div className="mt-1 text-[10.5px] text-ink-3">Pilot {session.pilot_completed}/6 · Formal {session.formal_completed}/36</div>
  </div>
}

export default function HumanEval() {
  const [protocol, setProtocol] = useState<HumanEvalProtocol | null>(null)
  const [session, setSession] = useState<HumanEvalSession | null>(null)
  const [current, setCurrent] = useState<HumanEvalCase | null>(null)
  const [form, setForm] = useState<Record<string, unknown>>({})
  const [actions, setActions] = useState<ReviewedAction[]>([])
  const [decision, setDecision] = useState<HumanCaseSubmission['decision'] | ''>('')
  const [reason, setReason] = useState('')
  const [acknowledge, setAcknowledge] = useState(false)
  const [ethicsConfirmed, setEthicsConfirmed] = useState(false)
  const [receiptOpen, setReceiptOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [finalResult, setFinalResult] = useState<Record<string, unknown> | null>(null)
  const [preflight, setPreflight] = useState<HumanPolicyPreflight | null>(null)
  const [visibleAt, setVisibleAt] = useState<string | null>(null)
  const [reviewStartedAt, setReviewStartedAt] = useState<string | null>(null)
  const interactions = useRef<HumanInteraction[]>([])
  const editedTargets = useRef(new Set<string>())
  const hiddenAt = useRef<number | null>(null)
  const hiddenDuration = useRef(0)

  useEffect(() => {
    evalApi.humanProtocol().then(setProtocol).catch((cause) => setError((cause as Error).message))
    const saved = localStorage.getItem(SESSION_KEY)
    if (saved) evalApi.humanSession(saved).then(setSession).catch(() => localStorage.removeItem(SESSION_KEY))
  }, [])

  useEffect(() => {
    const onVisibility = () => {
      if (document.hidden) hiddenAt.current = Date.now()
      else if (hiddenAt.current !== null) {
        hiddenDuration.current += Date.now() - hiddenAt.current
        hiddenAt.current = null
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
  }, [])

  const candidates = useMemo(() => {
    if (!current) return [] as Array<Record<string, unknown>>
    const check = current.reviewer_visible_checks.find((item) => item.type === 'candidate_search')
    return Array.isArray(check?.candidates) ? check.candidates as Array<Record<string, unknown>> : []
  }, [current])

  useEffect(() => {
    if (!session || !current || current.workflow === 'wf1') {
      setPreflight(null)
      return
    }
    const timer = window.setTimeout(() => {
      evalApi.preflightHumanCase(session.session_id, current.case_id, form)
        .then((value) => { setPreflight(value); setError(null) })
        .catch((cause) => setError(`Policy check failed: ${(cause as Error).message}`))
    }, 250)
    return () => window.clearTimeout(timer)
  }, [session, current, form])

  function addInteraction(kind: string, target?: string, value?: HumanInteraction['value']) {
    if ((kind === 'field_edit' || kind === 'reason_edit') && target) {
      if (editedTargets.current.has(target)) return
      editedTargets.current.add(target)
    }
    interactions.current.push({ kind, target, value, at: now() })
  }

  async function createSession() {
    setBusy(true); setError(null)
    try {
      const value = await evalApi.createHumanSession(ethicsConfirmed)
      localStorage.setItem(SESSION_KEY, value.session_id)
      setSession(value)
    } catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }

  async function startNext() {
    if (!session?.next_case_id) return
    setBusy(true); setError(null)
    try {
      const value = await evalApi.startHumanCase(session.session_id, session.next_case_id)
      const opened = now()
      const initialActions = Array.isArray(value.form_defaults.actions)
        ? value.form_defaults.actions as ReviewedAction[] : []
      const defaults = { ...value.form_defaults }
      delete defaults.actions
      setCurrent(value); setForm(defaults); setActions(initialActions)
      setDecision(value.workflow === 'wf1' && value.condition === 'agent_assisted' ? (initialActions.length ? 'route' : 'no_action') : '')
      setReason(''); setAcknowledge(false); setReceiptOpen(false)
      setPreflight(null)
      setVisibleAt(opened); setReviewStartedAt(opened)
      interactions.current = []; editedTargets.current = new Set(); hiddenDuration.current = 0; hiddenAt.current = null
    } catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }

  async function confirmEthics() {
    if (!session || !ethicsConfirmed) return
    setBusy(true); setError(null)
    try { setSession(await evalApi.confirmHumanEthics(session.session_id)) }
    catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }

  function addAction(actionType: ActionType) {
    if (actions.some((item) => item.action_type === actionType)) return
    const requester = actionType === 'schedule_meeting'
      ? String(current?.reference.default_meeting_participant ?? '') : ''
    setActions((old) => [...old, {
      action_type: actionType,
      fields: requester ? { participants: requester } : {},
      attachment_ids: [],
    }])
    setDecision('route'); addInteraction('action_type_select', actionType)
  }

  function updateAction(index: number, name: string, value: string) {
    setActions((old) => old.map((action, actionIndex) => actionIndex === index
      ? { ...action, fields: { ...action.fields, [name]: value } } : action))
  }

  function removeAction(index: number) {
    setActions((old) => old.filter((_, actionIndex) => actionIndex !== index))
    addInteraction('action_type_select', `remove-${index}`)
  }

  async function complete() {
    if (!session || !current || !decision || !visibleAt || !reviewStartedAt) return
    if (current.workflow === 'wf1' && decision === 'route' && actions.length === 0) {
      setError('Route requires at least one reviewed action draft.'); return
    }
    if ((decision === 'reject' || decision === 'request_information') && !reason.trim()) {
      setError('Add a decision reason or describe the information required.'); return
    }
    setBusy(true); setError(null)
    const decidedAt = now()
    const submittedInteractions: HumanInteraction[] = [...interactions.current, { kind: 'submit', target: 'final_state', value: decision, at: decidedAt }]
    interactions.current = submittedInteractions
    try {
      const next = await evalApi.completeHumanCase(session.session_id, current.case_id, {
        decision, actions, final_fields: form, reason: reason || null,
        acknowledge_warnings: acknowledge, interactions: submittedInteractions,
        timing: {
          case_visible_at: visibleAt,
          generation_started_at: current.condition === 'agent_assisted' ? current.server_started_at : null,
          draft_ready_at: current.condition === 'agent_assisted' ? current.server_draft_ready_at : null,
          review_started_at: reviewStartedAt,
          first_interaction_at: submittedInteractions[0]?.at ?? null,
          decision_at: decidedAt, case_completed_at: now(), hidden_duration_ms: hiddenDuration.current,
        },
      })
      setSession(next); setCurrent(null); setForm({}); setActions([]); setDecision('')
    } catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }

  async function finalize() {
    if (!session) return
    setBusy(true); setError(null)
    try {
      const result = await evalApi.finalizeHumanSession(session.session_id)
      setFinalResult(result); setSession(await evalApi.humanSession(session.session_id))
    } catch (cause) { setError((cause as Error).message) } finally { setBusy(false) }
  }

  return <div className="space-y-4">
    <Card className="border-line-strong"><div className="flex flex-wrap items-start justify-between gap-5 bg-surface-2 px-5 py-4">
      <div className="max-w-[760px]">
        <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.075em] text-accent"><ClipboardCheck size={15} /> Part B · Evaluation V5.1</div>
        <h2 className="mt-1 text-[20px] font-[660] tracking-[-0.02em] text-ink">Controlled Single-Reviewer Evaluation</h2>
        <p className="mt-1 text-[12.5px] leading-5 text-ink-2">Manual versus actual-Agent draft replay on 36 counterbalanced formal cases. Decision, hard fields and executed final state are scored together.</p>
      </div>{session && <Progress session={session} />}
    </div></Card>

    {protocol && <Card>
      <CardHeader title="Frozen protocol and readiness" right={<Pill tone={protocol.ready_for_collection ? 'ok' : 'warn'}>{protocol.ready_for_collection ? 'ready' : 'freeze pending'}</Pill>} />
      <div className="grid gap-3 p-4 md:grid-cols-3">
        <div className="rounded-lg bg-surface-2 p-3"><b className="text-[12.5px]">42 fixed cases</b><p className="mt-1 text-[11.5px] text-ink-3">6 pilots + 36 formal; 12 per workflow; 6/6 by condition.</p></div>
        <div className="rounded-lg bg-surface-2 p-3"><b className="text-[12.5px]">Actual frozen outputs</b><p className="mt-1 text-[11.5px] text-ink-3">{protocol.cache_cases}/{protocol.required_cache_cases} outputs frozen. No gold-derived drafts.</p></div>
        <div className="rounded-lg bg-surface-2 p-3"><b className="text-[12.5px]">Gold physically separated</b><p className="mt-1 text-[11.5px] text-ink-3">Reviewer API contains no expected decision or expected field.</p></div>
      </div>
      <div className="border-t border-line px-4 py-2.5 font-mono text-[10px] text-ink-3">manifest {protocol.manifest_sha256} · cache {protocol.agent_cache_sha256 ?? 'not frozen'}</div>
    </Card>}

    {!session && <Card><CardHeader title="Start a new V5.1 walkthrough" /><div className="space-y-4 p-4">
      {!protocol?.ready_for_collection && <div className="rounded-lg border border-warn bg-warn-soft p-3 text-[12.5px] text-ink-2">Collection is intentionally locked until every actual Agent output is frozen and the protocol hashes are sealed.</div>}
      <label className="flex items-start gap-3 rounded-lg border border-warn bg-warn-soft p-3 text-[12.5px] text-ink-2">
        <input type="checkbox" checked={ethicsConfirmed} onChange={(event) => setEthicsConfirmed(event.target.checked)} className="mt-0.5" />
        <span><b className="text-ink">Institutional pathway confirmation.</b> I have confirmed that this author-only synthetic-data evaluation may proceed. Without this confirmation, pilots remain available but formal collection is locked.</span>
      </label>
      <Button variant="primary" onClick={createSession} disabled={busy || !protocol?.ready_for_collection}>{busy ? <Spinner /> : <Play size={14} />} Create V5.1 session</Button>
    </div></Card>}

    {session && !current && session.status === 'in_progress' && !(session.pilot_completed === 6 && !session.ethics_confirmed) && <Card>
      <CardHeader title={session.next_case_id ? 'Next blinded case' : 'Collection complete'} right={<Pill tone={session.next_case_id ? 'neutral' : 'ok'}>{session.next_case_id ? (session.pilot_completed < 6 ? 'pilot' : 'formal') : 'ready to finalise'}</Pill>} />
      <div className="p-4">{session.next_case_id
        ? <><p className="mb-3 text-[12.5px] text-ink-2">The timer starts when the case opens. No correctness feedback is shown during collection.</p><Button variant="primary" onClick={startNext} disabled={busy}>{busy ? <Spinner /> : <Play size={14} />} Open next case</Button></>
        : <><p className="mb-3 text-[12.5px] text-ink-2">Finalisation scores 36 formal cases, excludes all six pilots and appends one immutable V5 result.</p><Button variant="primary" onClick={finalize} disabled={busy}>{busy ? <Spinner /> : <ShieldCheck size={14} />} Finalise and reveal results</Button></>}
      </div>
    </Card>}

    {session && !current && session.status === 'in_progress' && session.pilot_completed === 6 && !session.ethics_confirmed && <Card className="border-warn">
      <CardHeader title="Formal collection gate" right={<Pill tone="warn">confirmation required</Pill>} />
      <div className="space-y-3 p-4"><label className="flex items-start gap-3 text-[12.5px] text-ink-2"><input type="checkbox" checked={ethicsConfirmed} onChange={(event) => setEthicsConfirmed(event.target.checked)} className="mt-0.5" /><span>I confirm that the approved/exempt institutional pathway permits this author-only synthetic-data formal run.</span></label><Button variant="primary" disabled={!ethicsConfirmed || busy} onClick={confirmEthics}>{busy ? <Spinner /> : <ShieldCheck size={14} />} Unlock formal cases</Button></div>
    </Card>}

    {current && <>
      <Card><div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
        <b className="text-[14px]">{current.workflow.toUpperCase()} · {current.pilot ? 'Pilot case' : 'Formal case'}</b>
        <div className="flex gap-2"><Pill tone={current.pilot ? 'warn' : 'neutral'}>{current.pilot ? 'pilot — excluded' : 'formal'}</Pill><Pill tone={current.condition === 'agent_assisted' ? 'ok' : 'neutral'}>{current.condition === 'agent_assisted' ? 'Agent-assisted' : 'Manual'}</Pill></div>
      </div><div className="space-y-3 p-4">
        {current.input.text && <div className="whitespace-pre-wrap rounded-lg border border-line bg-surface-2 p-4 text-[13px] leading-6 text-ink">{current.input.text}</div>}
        {current.input.claimant_note && <div className="rounded-lg border border-line bg-surface-2 p-3 text-[12.5px] text-ink-2"><b>Claimant note:</b> {String(current.input.claimant_note)}</div>}
        {current.input.image_url && <div><Button size="sm" onClick={() => { setReceiptOpen((value) => !value); addInteraction('evidence_open', 'receipt') }}><Eye size={14} /> {receiptOpen ? 'Hide receipt' : 'Open receipt evidence'}</Button>{receiptOpen && <img src={String(current.input.image_url)} alt="Synthetic receipt evidence" className="mt-3 max-h-[440px] rounded-lg border border-line bg-white object-contain" />}</div>}
        <JsonPanel title="Neutral task references" value={current.reference} />
      </div></Card>

      {current.condition === 'agent_assisted' && <Card><CardHeader title="Frozen actual Agent assistance" right={<Pill tone="neutral">replay</Pill>} /><div className="grid gap-3 p-4 lg:grid-cols-2"><JsonPanel title="Raw and normalised draft" value={current.agent_assistance} /><JsonPanel title="Reviewer-visible deterministic checks" value={current.reviewer_visible_checks} /></div></Card>}

      <Card><CardHeader title="Complete the final task state" /><div className="space-y-4 p-4">
        {current.workflow === 'wf1' && <>
          <div className="flex flex-wrap gap-2"><Button size="sm" onClick={() => addAction('schedule_meeting')} disabled={actions.some((item) => item.action_type === 'schedule_meeting')}><Plus size={13} /> Meeting draft</Button><Button size="sm" onClick={() => addAction('expense_claim')} disabled={actions.some((item) => item.action_type === 'expense_claim')}><Plus size={13} /> Expense draft</Button><Button size="sm" variant={decision === 'no_action' ? 'primary' : 'secondary'} onClick={() => { setActions([]); setDecision('no_action'); addInteraction('decision_select', 'decision', 'no_action') }}>No supported action</Button></div>
          {actions.map((action, index) => <div key={`${action.action_type}-${index}`} className="rounded-lg border border-line-strong p-3">
            <div className="mb-3 flex items-center justify-between"><b className="text-[12.5px]">{action.action_type.replaceAll('_', ' ')}</b><Button size="sm" onClick={() => removeAction(index)}><Trash2 size={13} /> Remove</Button></div>
            <div className="grid gap-3 md:grid-cols-2">{(action.action_type === 'schedule_meeting' ? scheduleFields : expenseFields).map(([name, label, type]) => <Field key={name} name={name} label={label} type={type} value={action.fields[name]} onChange={(value) => updateAction(index, name, value)} onEdited={() => addInteraction('field_edit', `action.${index}.${name}`)} />)}</div>
            {action.action_type === 'expense_claim' && <Field name="attachment_ids" label="Attachment IDs (comma separated)" type="text" value={action.attachment_ids} onChange={(value) => setActions((old) => old.map((item, actionIndex) => actionIndex === index ? { ...item, attachment_ids: value.split(',').map((part) => part.trim()).filter(Boolean) } : item))} onEdited={() => addInteraction('field_edit', `action.${index}.attachment_ids`)} />}
          </div>)}
        </>}

        {current.workflow !== 'wf1' && <>
          {current.workflow === 'wf2' && current.condition === 'agent_assisted' && (preflight?.suggested_alternatives.length || candidates.length > 0) && <div className="rounded-lg border border-warn bg-warn-soft p-3"><div className="text-[11px] font-semibold uppercase tracking-[0.055em] text-warn">Verified conflict-free alternatives</div><div className="mt-2 flex flex-wrap gap-2">{(preflight?.suggested_alternatives.length ? preflight.suggested_alternatives : candidates).map((candidate, index) => <Button key={`${String(candidate.date)}-${String(candidate.start)}-${index}`} size="sm" onClick={() => { setForm((old) => ({ ...old, date: candidate.date, time: candidate.start })); addInteraction('candidate_select', 'meeting_time', `${String(candidate.date)} ${String(candidate.start)}`) }}>{String(candidate.date)} {String(candidate.start)}</Button>)}</div><p className="mt-2 text-[11.5px] text-ink-2">Select an available option, verify that policy checks pass, then Approve.</p></div>}
          <div className="grid gap-3 md:grid-cols-2">{(current.workflow === 'wf3' ? expenseFields : scheduleFields).map(([name, label, type]) => <Field key={name} name={name} label={label} type={type} value={form[name]} onChange={(value) => setForm((old) => ({ ...old, [name]: value }))} onEdited={() => addInteraction('field_edit', name)} />)}</div>
          {preflight && <div className={`rounded-lg border p-3 ${preflight.alerts.length ? 'border-warn bg-warn-soft' : 'border-ok/30 bg-ok-soft'}`}><div className="text-[11px] font-semibold uppercase tracking-[0.055em]">Policy checks</div>{preflight.alerts.length ? <div className="mt-2 space-y-2">{preflight.alerts.map((alert, index) => <div key={`${alert.rule}-${index}`} className={alert.severity === 'hard' ? 'text-bad' : 'text-warn'}><b className="text-[12.5px]">{alert.title}</b><p className="text-[12px] leading-5">{alert.message}</p>{alert.required_decision && <p className="text-[11.5px] font-semibold">Required action: {alert.required_decision.replaceAll('_', ' ')}</p>}</div>)}</div> : <p className="mt-1 text-[12px] text-ink-2">No blocking policy issue detected.</p>}<p className="mt-2 border-t border-current/10 pt-2 text-[11.5px] text-ink-2">{preflight.instruction}</p></div>}
          <div><div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.055em] text-ink-3">Final decision</div><div className="flex flex-wrap gap-2">{current.allowed_decisions.map((value) => <Button key={value} size="sm" disabled={value === 'approve' && Boolean(preflight?.approve_blocked)} variant={decision === value ? 'primary' : 'secondary'} onClick={() => { setDecision(value as HumanCaseSubmission['decision']); addInteraction('decision_select', 'decision', value) }}>{value.replaceAll('_', ' ')}</Button>)}</div></div>
        </>}

        <label className="block"><span className="mb-1 block text-[11px] font-semibold uppercase tracking-[0.055em] text-ink-3">Decision reason / information request</span><textarea value={reason} onChange={(event) => { addInteraction('reason_edit', 'decision_reason'); setReason(event.target.value) }} className="min-h-20 w-full rounded-lg border border-line-strong bg-surface p-3 text-[13px] outline-none focus:border-accent focus:ring-2 focus:ring-accent-ring" /></label>
        {current.workflow !== 'wf1' && Boolean(preflight?.soft_warning_rules.length) && <label className="flex items-center gap-2 text-[12.5px] text-ink-2"><input type="checkbox" checked={acknowledge} onChange={(event) => { setAcknowledge(event.target.checked); addInteraction('policy_inspect', 'warning_acknowledgement', event.target.checked) }} /> I inspected the policy checks and explicitly acknowledge the displayed soft warning.</label>}
        {error && <div className="rounded-lg border border-bad/30 bg-bad-soft px-4 py-3 text-[12.5px] text-bad"><b>Submission not completed.</b><br />{error}</div>}
        <div className="flex items-center justify-between border-t border-line pt-4"><span className="text-[11px] text-ink-3">Gold and correctness remain hidden until finalisation.</span><Button variant="primary" onClick={complete} disabled={busy || !decision || (decision === 'approve' && Boolean(preflight?.approve_blocked))}>{busy ? <Spinner /> : <CheckCircle2 size={14} />} Submit final state</Button></div>
      </div></Card>
    </>}

    {error && !current && <div className="rounded-lg border border-bad/30 bg-bad-soft px-4 py-3 text-[12.5px] text-bad">{error}</div>}
    {finalResult && <Card><CardHeader title="Final descriptive result" right={<Pill tone="ok">formal saved</Pill>} /><pre className="max-h-[540px] overflow-auto p-4 text-[10.5px] leading-4 text-ink-2">{JSON.stringify(finalResult, null, 2)}</pre></Card>}
    {session?.status === 'complete' && !finalResult && <Card><Empty>This V5 session is complete. Its formal summary is available in Run History.</Empty></Card>}
  </div>
}
