import { useMemo, useState } from 'react'
import type { Thread } from '@/lib/api'
import { useThemeColors } from '@/lib/useThemeColors'
import { Button, Card, CardHeader, Empty, Pill } from '@/components/ui'
import { HBar, StatTile, type Bucket } from '@/components/charts'

type Attention = 'all' | 'review' | 'evidence' | 'memos' | 'dates'
const REVIEWABLE = new Set(['pending', 'proposed', 'edited'])

function buckets(entries: Array<[string, number]>): Bucket[] {
  return entries.filter(([, value]) => value > 0).map(([label, value]) => ({ label, value }))
}

export default function InboxOperationalAnalysis({
  threads,
  onOpenThread,
}: {
  threads: Thread[]
  onOpenThread: (threadId: string) => void
}) {
  const colors = useThemeColors()
  const [attention, setAttention] = useState<Attention>('all')
  const actions = threads.flatMap((thread) => thread.detected_actions.map((action) => ({ thread, action })))
  const supported = actions.filter(({ action }) => action.action_type !== 'none')
  const memos = threads.flatMap((thread) => thread.memo_items.map((memo) => ({ thread, memo })))
  const now = new Date()
  const weekEnd = new Date(now); weekEnd.setDate(weekEnd.getDate() + 7)
  const upcoming = memos.filter(({ memo }) => {
    if (memo.status !== 'active' || !memo.resolved_date) return false
    const date = new Date(`${memo.resolved_date}T23:59:59`)
    return date >= now && date <= weekEnd
  })
  const awaiting = supported.filter(({ action }) => REVIEWABLE.has(action.status))
  const needsEvidence = supported.filter(({ action }) => action.downstream_status === 'needs_evidence')
  const openMemos = memos.filter(({ memo }) => memo.status === 'active')

  const filtered = useMemo(() => threads.filter((thread) => {
    if (attention === 'review') return thread.detected_actions.some((action) => REVIEWABLE.has(action.status))
    if (attention === 'evidence') return thread.detected_actions.some((action) => action.downstream_status === 'needs_evidence')
    if (attention === 'memos') return thread.memo_items.some((memo) => memo.status === 'active')
    if (attention === 'dates') return upcoming.some((item) => item.thread.id === thread.id)
    return true
  }), [attention, threads, upcoming])

  const newThreads = threads.filter((thread) => !thread.last_triaged_message_id).length
  const analysed = threads.length - newThreads
  const routedThreads = threads.filter((thread) => thread.detected_actions.some((action) => action.status === 'routed')).length
  const archived = threads.filter((thread) => thread.status === 'archived').length
  const funnel = buckets([
    ['new', newThreads], ['analysed', analysed], ['awaiting review', threads.filter((thread) => thread.detected_actions.some((action) => REVIEWABLE.has(action.status))).length],
    ['routed (distinct threads)', routedThreads], ['archived', archived],
  ])
  const actionMix = buckets([
    ['meeting actions', supported.filter(({ action }) => action.action_type === 'schedule_meeting').length],
    ['expense actions', supported.filter(({ action }) => action.action_type === 'expense_claim').length],
  ])
  const memoOnlyThreads = threads.filter((thread) => thread.memo_items.length > 0 && !thread.detected_actions.some((action) => action.action_type !== 'none')).length
  const resolution = buckets([
    ['routed unchanged', supported.filter(({ action }) => action.status === 'routed' && !(action.previous_versions?.length)).length],
    ['modified then routed', supported.filter(({ action }) => action.status === 'routed' && Boolean(action.previous_versions?.length)).length],
    ['dismissed', supported.filter(({ action }) => action.status === 'dismissed').length],
    ['pending', awaiting.length],
  ])

  return <div className="flex flex-col gap-4">
    <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-4">
      <button type="button" onClick={() => setAttention('review')} className="text-left"><StatTile label="Awaiting review" value={awaiting.length} dot="bg-warn" note="workflow actions" /></button>
      <button type="button" onClick={() => setAttention('evidence')} className="text-left"><StatTile label="Needs evidence" value={needsEvidence.length} dot="bg-bad" note="WF3 drafts" /></button>
      <button type="button" onClick={() => setAttention('memos')} className="text-left"><StatTile label="Open memo items" value={openMemos.length} dot="bg-accent" note="user-controlled" /></button>
      <button type="button" onClick={() => setAttention('dates')} className="text-left"><StatTile label="Next 7 days" value={upcoming.length} dot="bg-ok" note="resolved memo dates" /></button>
    </div>

    <div className="flex flex-wrap items-center gap-2"><span className="text-[12px] text-ink-3">Queue filter:</span>{(['all', 'review', 'evidence', 'memos', 'dates'] as Attention[]).map((value) => <Button key={value} size="sm" variant={attention === value ? 'primary' : 'secondary'} onClick={() => setAttention(value)}>{value}</Button>)}</div>

    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card><CardHeader title="Work-queue funnel · thread denominator" /><HBar data={funnel} color={colors['--accent']} format={String} unitLabel="distinct thread(s)" /></Card>
      <Card><CardHeader title="Workflow action mix · action denominator" /><HBar data={actionMix} color={colors['--accent']} format={String} unitLabel="action(s)" /><p className="px-4 pb-4 text-[11.5px] text-ink-3">Memo-only threads: {memoOnlyThreads} distinct thread(s). Kept separate from action counts.</p></Card>
    </div>
    <Card><CardHeader title="Human resolution · action denominator" /><HBar data={resolution} color={colors['--accent']} format={String} unitLabel="action(s)" /></Card>

    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card><CardHeader title={`Attention queue · ${filtered.length} thread(s)`} />{filtered.length === 0 ? <Empty>No records for this filter.</Empty> : <div className="divide-y divide-line">{filtered.map((thread) => <button type="button" key={thread.id} onClick={() => onOpenThread(thread.id)} className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-surface-2"><div><p className="text-[13px] font-medium text-ink">{thread.subject}</p><p className="mt-0.5 text-[11px] text-ink-3">{thread.detected_actions.length} action(s) · {thread.memo_items.filter((memo) => memo.status === 'active').length} open memo(s)</p></div><Pill tone={thread.status === 'resolved' ? 'ok' : 'warn'}>{thread.status}</Pill></button>)}</div>}</Card>
      <Card><CardHeader title="Upcoming memo dates · next 7 days" />{upcoming.length === 0 ? <Empty>No resolved memo dates in this window.</Empty> : <div className="divide-y divide-line">{upcoming.sort((a, b) => String(a.memo.resolved_date).localeCompare(String(b.memo.resolved_date))).map(({ thread, memo }) => <button type="button" key={memo.memo_id} onClick={() => onOpenThread(thread.id)} className="block w-full px-4 py-3 text-left hover:bg-surface-2"><p className="text-[12px] font-semibold text-accent">{memo.resolved_date}</p><p className="mt-0.5 text-[13px] text-ink">{memo.current_text}</p><p className="mt-0.5 text-[11px] text-ink-3">{thread.subject}</p></button>)}</div>}</Card>
    </div>
    <p className="text-[11px] text-ink-3">Operational counts only. Model confidence, extraction accuracy and baseline comparisons remain in the separate Evaluation workspace.</p>
  </div>
}
