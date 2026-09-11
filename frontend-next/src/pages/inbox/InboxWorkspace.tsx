import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import { Archive, Edit3, Mail, MessageSquare, Paperclip, Plus, Save, Sparkles, X } from 'lucide-react'
import {
  inboxApi,
  type MemoItem,
  type RouteResult,
  type Thread,
  type ThreadAction,
  type ThreadAttachment,
} from '@/lib/api'
import { useAppData } from '@/context/AppData'
import { Button, Card, CardHeader, Empty, FlagChip, PageHeader, Pill, Segmented, Spinner } from '@/components/ui'
import { cn } from '@/lib/utils'
import { Link, useSearchParams } from 'react-router-dom'

const InboxAnalytics = lazy(() => import('./InboxOperationalAnalysis'))
type Tab = 'work' | 'analytics'

const STATUS_TONE: Record<string, 'ok' | 'warn' | 'bad' | 'neutral'> = {
  unread: 'warn', analysed: 'neutral', in_review: 'warn', partially_routed: 'warn',
  resolved: 'ok', archived: 'neutral',
}

function fmtWhen(iso?: string | null) {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return `${date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}, ${date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}`
}

function Transcript({ thread }: { thread: Thread }) {
  return (
    <div className="flex max-h-80 flex-col gap-2 overflow-y-auto" aria-label="Thread messages">
      {thread.messages.map((message) => (
        <article id={message.message_id} key={message.message_id} className="rounded-lg border border-line bg-surface-2 px-3 py-2.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-[12px] font-semibold text-accent">{message.sender}</span>
            <span className="font-mono text-[10.5px] text-ink-3">{message.message_id} · {fmtWhen(message.sent_at)}</span>
          </div>
          <p className="mt-1 whitespace-pre-wrap text-[13px] leading-relaxed text-ink-2">{message.body}</p>
          {message.attachment_ids.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {message.attachment_ids.map((id) => <span key={id} className="rounded bg-surface-3 px-2 py-1 font-mono text-[10.5px] text-ink-3"><Paperclip size={11} className="mr-1 inline" />{id}</span>)}
            </div>
          )}
        </article>
      ))}
    </div>
  )
}

function ActionReviewCard({
  action, attachments, busy, onRoute, onDismiss, onSave,
}: {
  action: ThreadAction
  attachments: ThreadAttachment[]
  busy: boolean
  onRoute: () => void
  onDismiss: () => void
  onSave: (fields: Record<string, unknown>, operation: ThreadAction['operation'], target: string | null, attachmentIds: string[]) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [fieldsText, setFieldsText] = useState(JSON.stringify(action.current_seed_fields, null, 2))
  const [operation, setOperation] = useState(action.operation)
  const [target, setTarget] = useState(action.target_action_id ?? '')
  const [selectedAttachments, setSelectedAttachments] = useState(action.attachment_ids)
  const [error, setError] = useState<string | null>(null)
  const reviewable = ['pending', 'proposed', 'edited'].includes(action.status)
  const changed = JSON.stringify(action.model_seed_fields) !== JSON.stringify(action.current_seed_fields)
  const tone = action.status === 'routed' ? 'ok' : action.status === 'dismissed' ? 'neutral' : 'warn'

  async function save() {
    try {
      const parsed = JSON.parse(fieldsText) as Record<string, unknown>
      setError(null)
      await onSave(parsed, operation, target || null, selectedAttachments)
      setEditing(false)
    } catch (cause) {
      setError(cause instanceof SyntaxError ? 'Fields must be valid JSON.' : (cause as Error).message)
    }
  }

  return (
    <article className="rounded-xl border border-line bg-surface-2 p-3.5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[13px] font-semibold leading-snug text-ink">{action.action_type}</span>
          <Pill tone={tone}>{action.status}</Pill>
          <span className="rounded bg-surface-3 px-2 py-1 text-[11px] text-ink-2">{action.operation} · v{action.version}</span>
          {changed && <span className="rounded bg-accent-soft px-2 py-1 text-[11px] text-accent">human modified</span>}
        </div>
        {action.routed_to && <Link to={action.action_type === 'schedule_meeting' ? `/calendar?draft=${action.routed_to}` : `/expenses?draft=${action.routed_to}`} className="font-mono text-[11px] text-accent hover:underline">Open {action.routed_to} · {action.downstream_status}</Link>}
      </div>

      {action.rationale && <p className="mt-2 text-[12.5px] text-ink-2">{action.rationale}</p>}
      {action.source_evidence.length > 0 && (
        <div className="mt-2 space-y-1">
          {action.source_evidence.map((evidence, index) => (
            <a key={`${evidence.message_id}-${index}`} href={`#${evidence.message_id}`} className="block border-l-2 border-line-strong pl-2 text-[12px] italic text-ink-3 hover:text-ink">
              {evidence.grounded ? 'Grounded' : 'Review evidence'} · {evidence.message_id}: “{evidence.span}”
            </a>
          ))}
        </div>
      )}
      {action.missing_fields.length > 0 && <p className="mt-2 text-[12px] text-warn">Missing: {action.missing_fields.join(', ')}</p>}
      {action.flags?.map((flag, index) => <div key={`${flag.rule}-${index}`} className="mt-2"><FlagChip severity={flag.severity}>{flag.rule.replace(/_/g, ' ')} · {flag.message}</FlagChip></div>)}

      {editing ? (
        <div className="mt-3 space-y-2 rounded-lg border border-line bg-surface p-3">
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="text-[11.5px] text-ink-3">Operation
              <select value={operation} onChange={(event) => setOperation(event.target.value as ThreadAction['operation'])} className="mt-1 h-9 w-full rounded-lg border border-line bg-surface px-2 text-[13px] text-ink">
                <option value="create">create</option><option value="amend">amend</option><option value="cancel">cancel</option>
              </select>
            </label>
            <label className="text-[11.5px] text-ink-3">Target action ID
              <input value={target} onChange={(event) => setTarget(event.target.value)} placeholder="required for amend/cancel" className="mt-1 h-9 w-full rounded-lg border border-line bg-surface px-2 font-mono text-[12px] text-ink" />
            </label>
          </div>
          <label className="block text-[11.5px] text-ink-3">Current workflow fields
            <textarea value={fieldsText} onChange={(event) => setFieldsText(event.target.value)} rows={9} className="mt-1 w-full rounded-lg border border-line bg-surface p-2 font-mono text-[12px] text-ink" />
          </label>
          {attachments.length > 0 && <fieldset><legend className="text-[11.5px] text-ink-3">Evidence attachments</legend><div className="mt-1 flex flex-wrap gap-2">{attachments.map((attachment) => <label key={attachment.attachment_id} className="flex items-center gap-1.5 rounded border border-line px-2 py-1.5 text-[11.5px] text-ink-2"><input type="checkbox" checked={selectedAttachments.includes(attachment.attachment_id)} onChange={(event) => setSelectedAttachments((current) => event.target.checked ? [...current, attachment.attachment_id] : current.filter((id) => id !== attachment.attachment_id))} />{attachment.filename}</label>)}</div></fieldset>}
          {error && <p className="text-[12px] text-bad">{error}</p>}
          <div className="flex gap-2"><Button size="sm" variant="primary" disabled={busy} onClick={save}><Save size={13} />Save changes</Button><Button size="sm" onClick={() => setEditing(false)}>Cancel</Button></div>
        </div>
      ) : (
        <details className="mt-2"><summary className="cursor-pointer text-[11.5px] text-ink-3">Current fields and provenance</summary><pre className="mt-1.5 overflow-x-auto rounded-md border border-line bg-surface p-2 font-mono text-[11px] text-ink-2">{JSON.stringify(action.current_seed_fields, null, 2)}</pre></details>
      )}

      {reviewable && !editing && <div className="mt-3 flex flex-wrap gap-2"><Button size="sm" variant="primary" disabled={busy} onClick={onRoute}>{busy ? <Spinner /> : action.operation === 'cancel' ? 'Route cancellation →' : action.operation === 'amend' ? 'Route amendment →' : 'Route draft →'}</Button><Button size="sm" disabled={busy} onClick={() => setEditing(true)}><Edit3 size={13} />Modify</Button><Button size="sm" disabled={busy} onClick={onDismiss}>Dismiss</Button></div>}
    </article>
  )
}

function MemoChecklist({ thread, actorId, reload, notify }: { thread: Thread; actorId: string; reload: () => Promise<void>; notify: (message: string) => void }) {
  const [text, setText] = useState('')
  const [date, setDate] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingText, setEditingText] = useState('')
  const visible = thread.memo_items.filter((memo) => memo.status !== 'dismissed')

  async function update(memo: MemoItem, body: Record<string, unknown>) {
    try {
      await inboxApi.editMemo(thread.id, memo.memo_id, { ...body, expected_version: memo.version, acting_user: actorId })
      await reload()
    } catch (error) { notify((error as Error).message) }
  }

  async function add() {
    if (!text.trim()) return
    if (date && !/^\d{4}-\d{2}-\d{2}$/.test(date)) { notify('Use date format YYYY-MM-DD.'); return }
    try {
      await inboxApi.addMemo(thread.id, { text: text.trim(), item_type: date ? 'important_date' : 'todo', resolved_date: date || null, acting_user: actorId })
      setText(''); setDate(''); await reload()
    } catch (error) { notify((error as Error).message) }
  }

  return (
    <section>
      <div className="mb-2 flex items-center justify-between"><h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">Memo checklist</h3><span className="text-[11px] text-ink-3">{visible.filter((memo) => !memo.is_completed).length} open</span></div>
      <div className="space-y-2">
        {visible.map((memo) => <div key={memo.memo_id} className="rounded-lg border border-line bg-surface-2 p-2.5"><div className="flex items-start gap-2"><input aria-label={`Complete ${memo.current_text}`} type="checkbox" checked={memo.is_completed} onChange={(event) => void update(memo, { is_completed: event.target.checked })} className="mt-1" />{editingId === memo.memo_id ? <div className="flex flex-1 gap-2"><input aria-label="Edit memo text" value={editingText} onChange={(event) => setEditingText(event.target.value)} className="h-8 min-w-0 flex-1 rounded border border-line bg-surface px-2 text-[12.5px] text-ink" /><Button size="sm" onClick={() => { void update(memo, { text: editingText }); setEditingId(null) }}>Save</Button></div> : <div className="min-w-0 flex-1"><p className={cn('text-[13px] font-semibold leading-snug text-ink', memo.is_completed && 'line-through opacity-60')}>{memo.current_text}</p>{(memo.resolved_date || memo.date_phrase) && <p className="mt-1 font-mono text-[10.5px] font-medium text-accent">{memo.date_relation ?? 'on'} {memo.resolved_date ?? memo.date_phrase}</p>}{memo.source_evidence.map((evidence) => <a key={`${memo.memo_id}-${evidence.message_id}`} href={`#${evidence.message_id}`} className="mt-1 block text-[10.5px] text-ink-3 hover:text-ink">Source: {evidence.message_id}</a>)}</div>}<Button aria-label="Edit memo" size="sm" variant="ghost" onClick={() => { setEditingId(memo.memo_id); setEditingText(memo.current_text) }}><Edit3 size={13} /></Button><Button aria-label="Dismiss memo" size="sm" variant="ghost" onClick={() => void update(memo, { dismissed: true })}><X size={13} /></Button></div></div>)}
        {visible.length === 0 && <p className="rounded-lg border border-dashed border-line px-3 py-4 text-center text-[12px] text-ink-3">No memo items.</p>}
        <div className="grid gap-2 rounded-lg border border-line bg-surface p-2.5 sm:grid-cols-[1fr_145px_auto]"><input aria-label="New memo text" value={text} onChange={(event) => setText(event.target.value)} placeholder="Add a grounded follow-up…" className="h-9 rounded-lg border border-line bg-surface px-2.5 text-[13px] text-ink" /><input aria-label="Memo date in YYYY-MM-DD format" type="text" inputMode="numeric" autoComplete="off" placeholder="YYYY-MM-DD" pattern="[0-9]{4}-[0-9]{2}-[0-9]{2}" value={date} onChange={(event) => setDate(event.target.value)} className="h-9 rounded-lg border border-line bg-surface px-2 text-[12px] text-ink" /><Button size="sm" onClick={add}><Plus size={13} />Add</Button></div>
      </div>
    </section>
  )
}

export default function InboxWorkspace() {
  const { actor } = useAppData()
  const [searchParams] = useSearchParams()
  const [tab, setTab] = useState<Tab>('work')
  const [threads, setThreads] = useState<Thread[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [sender, setSender] = useState('Alice')
  const [messageBody, setMessageBody] = useState('')

  const load = useCallback(async (keep?: string) => {
    try { const data = await inboxApi.threads(); setThreads(data.threads); setSelected((current) => keep ?? current ?? data.threads[0]?.id ?? null) }
    catch (error) { setNote((error as Error).message); setThreads([]) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    const threadId = searchParams.get('thread')
    if (threadId) setSelected(threadId)
  }, [searchParams])
  const current = useMemo(() => threads.find((thread) => thread.id === selected) ?? null, [threads, selected])
  const open = threads.filter((thread) => !['archived', 'resolved'].includes(thread.status))

  async function triage() {
    if (!current) return
    setBusy('triage'); setNote(null)
    try { const result = await inboxApi.triage(current.id); setNote(result.status === 'no_new_messages' ? 'No new messages to analyse.' : 'Thread analysis updated.'); await load(current.id) }
    catch (error) { setNote((error as Error).message) }
    finally { setBusy(null) }
  }

  async function act(action: ThreadAction, kind: 'route' | 'dismiss') {
    if (!current || !actor) return
    setBusy(action.action_id); setNote(null)
    try {
      const result: RouteResult = kind === 'route' ? await inboxApi.route(current.id, action.action_id, action.version, actor.id) : await inboxApi.dismiss(current.id, action.action_id, action.version, actor.id)
      if (result.status === 'already_handled') setNote(`Already ${result.action_status}.`)
      else if (result.routed === 'calendar') setNote(`WF2 draft ${result.record_id} saved as ${result.status}; calendar unchanged.`)
      else if (result.routed === 'expenses') setNote(`WF3 draft ${result.record_id} saved as ${result.status}; no claim submitted.`)
      else setNote(kind === 'dismiss' ? 'Action dismissed.' : `Draft ${result.record_id} created.`)
      await load(current.id)
    } catch (error) { setNote((error as Error).message) }
    finally { setBusy(null) }
  }

  async function saveAction(action: ThreadAction, fields: Record<string, unknown>, operation: ThreadAction['operation'], target: string | null, attachmentIds: string[]) {
    if (!current || !actor) return
    setBusy(action.action_id)
    try { await inboxApi.editAction(current.id, action.action_id, { expected_version: action.version, fields, operation, target_action_id: target, attachment_ids: attachmentIds, acting_user: actor.id }); setNote('Action changes saved and revalidated.'); await load(current.id) }
    finally { setBusy(null) }
  }

  async function addMessage() {
    if (!current || !actor || !messageBody.trim()) return
    setBusy('message')
    try { await inboxApi.addMessage(current.id, { sender, body: messageBody.trim(), acting_user: actor.id }); setMessageBody(''); setNote('Message added. Analyse new messages when ready.'); await load(current.id) }
    catch (error) { setNote((error as Error).message) }
    finally { setBusy(null) }
  }

  async function archive() {
    if (!current || !actor) return
    try { await inboxApi.archive(current.id, actor.id); await load(current.id) }
    catch (error) { setNote((error as Error).message) }
  }

  return <div><PageHeader title="Thread action intake" subtitle="Agent proposes grounded workflow drafts and memo items · you edit, route or dismiss · downstream approval still executes." right={<Segmented value={tab} onChange={setTab} options={[{ value: 'work', label: 'Work' }, { value: 'analytics', label: 'Analysis' }]} />} />
    {tab === 'analytics' ? <div className="mt-6"><Suspense fallback={<Empty>Loading Analysis…</Empty>}><InboxAnalytics threads={threads} onOpenThread={(threadId) => { setSelected(threadId); setTab('work') }} /></Suspense></div> :
      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr]"><Card><CardHeader title="Threads" right={<Pill>{open.length} open</Pill>} />{loading ? <Empty><Spinner /> Loading…</Empty> : <div className="max-h-[75vh] overflow-y-auto">{threads.map((thread) => <button key={thread.id} type="button" onClick={() => setSelected(thread.id)} className={cn('w-full border-t border-line px-4 py-3 text-left first:border-t-0 hover:bg-surface-2', selected === thread.id && 'bg-accent-soft')}><div className="flex items-center gap-2">{thread.source === 'email' ? <Mail size={13} /> : <MessageSquare size={13} />}<span className="truncate text-[13px] font-medium text-ink">{thread.subject}</span>{thread.has_untriaged_messages && <span className="size-2 rounded-full bg-accent" title="New messages" />}</div><div className="mt-1 flex items-center justify-between"><span className="text-[11px] text-ink-3">{fmtWhen(thread.received_at)}</span><Pill tone={STATUS_TONE[thread.status] ?? 'neutral'}>{thread.status}</Pill></div></button>)}</div>}</Card>
        <Card>{!current ? <Empty>Select a thread.</Empty> : <><CardHeader title={current.subject ?? current.id} right={<div className="flex gap-2"><Button size="sm" variant="primary" disabled={busy !== null || (!current.has_untriaged_messages && current.detected_actions.length > 0)} onClick={triage}>{busy === 'triage' ? <Spinner /> : <Sparkles size={13} />}{current.detected_actions.length ? 'Analyse new messages' : 'Analyse thread'}</Button><Button size="sm" disabled={current.detected_actions.some((action) => ['pending', 'proposed', 'edited'].includes(action.status))} onClick={archive}><Archive size={13} />Archive</Button></div>} /><div className="space-y-5 p-4">{note && <div className="rounded-lg border border-warn bg-warn-soft px-3 py-2 text-[12.5px] text-warn">{note}</div>}<Transcript thread={current} />
          <div className="grid gap-2 rounded-lg border border-line bg-surface p-3 sm:grid-cols-[140px_1fr_auto]"><input value={sender} onChange={(event) => setSender(event.target.value)} aria-label="Message sender" className="h-9 rounded-lg border border-line bg-surface px-2 text-[13px] text-ink" /><input aria-label="New thread message" value={messageBody} onChange={(event) => setMessageBody(event.target.value)} placeholder="Append a new thread message…" className="h-9 rounded-lg border border-line bg-surface px-2 text-[13px] text-ink" /><Button size="sm" disabled={busy !== null || !messageBody.trim()} onClick={addMessage}><Plus size={13} />Add message</Button></div>
          {(current.summary || current.key_points.length > 0) && <section className="rounded-lg border border-line bg-surface-2 p-3"><h3 className="text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">Supporting summary</h3>{current.summary && <p className="mt-1 text-[13px] text-ink-2">{current.summary}</p>}</section>}
          {current.detected_actions.length > 0 && <section><h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">Workflow actions — human review required</h3><div className="space-y-2.5">{current.detected_actions.map((action) => <ActionReviewCard key={`${action.action_id}-${action.version}`} action={action} attachments={current.attachments} busy={busy === action.action_id} onRoute={() => void act(action, 'route')} onDismiss={() => void act(action, 'dismiss')} onSave={(fields, operation, target, attachmentIds) => saveAction(action, fields, operation, target, attachmentIds)} />)}</div></section>}
          {actor && <MemoChecklist thread={current} actorId={actor.id} reload={() => load(current.id)} notify={setNote} />}
          {current.audit_events.length > 0 && <details><summary className="cursor-pointer text-[11.5px] text-ink-3">Audit history ({current.audit_events.length})</summary><div className="mt-2 space-y-1">{[...current.audit_events].reverse().map((event) => <div key={event.event_id} className="rounded border border-line px-2.5 py-2 text-[11.5px] text-ink-2"><span className="font-medium">{event.action}</span> · {event.actor} · {fmtWhen(event.timestamp)} · {event.reason_code}</div>)}</div></details>}
        </div></>}</Card></div>}
  </div>
}
