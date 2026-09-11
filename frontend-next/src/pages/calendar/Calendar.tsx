import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react'
import { CalendarDays, Clock, Download, ExternalLink, X } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  scheduleApi,
  type CalEvent,
  type DecideSchedResult,
  type Flag,
  type RunSchedResult,
  type RoutedDraft,
  type SchedEvent,
} from '@/lib/api'
import { useAppData } from '@/context/AppData'
import { Button, Card, CardHeader, Empty, FlagChip, PageHeader, Pill, Segmented, Spinner } from '@/components/ui'
import { AgentReasoning, Trace } from '@/components/AgentReasoning'
import DateField, { TimeField } from '@/components/DateField'
import { labelOf } from '@/lib/format'
import { cn } from '@/lib/utils'

import WeekGrid from './WeekGrid'
import SmartSchedule from './SmartSchedule'

const CalendarAnalytics = lazy(() => import('./CalendarAnalytics'))

type Tab = 'work' | 'analytics'
type CalView = 'week' | 'list'

const FIELDS = ['title', 'date', 'time', 'duration_minutes', 'location', 'mode', 'agenda'] as const

// Synthetic examples (CLAUDE.md §3.1 — no real data), one per difficulty the evaluation
// harness tiers on (scheduling_data.py: clean / conflict / missing / ambiguous / noise /
// out_of_scope), so the demo mirrors what is measured.
const EXAMPLES: { label: string; text: string }[] = [
  {
    label: 'Clean — fully specified',
    text: 'Set up a 1 hour Q3 budget review with Bob and Chen next Tuesday at 14:00 in Orion.',
  },
  {
    label: 'Conflict — clashes with a booked slot',
    text: 'Book a 1 hour sync with Bob next Tuesday at 14:00 to go over the launch plan.',
  },
  {
    label: 'Missing time — no time given',
    text: 'Can we get Chen and Dana together next Wednesday to review the vendor contract?',
  },
  {
    label: 'Ambiguous date — "next Friday"',
    text: "Let's meet Bob about the sprint review next Friday at 11:30.",
  },
  {
    label: 'Vague — no resolvable day',
    text: 'We should sit down with Chen sometime soon to sort out the budget.',
  },
  {
    label: 'Buried in chatter (noise)',
    text:
      'Morning all! Coffee machine on 2 is broken again 😩. Oh — can Alice and Evan meet ' +
      'next Thursday at 10:00 about onboarding? Also the fire drill is Friday, heads up.',
  },
  {
    label: 'Out of scope — nothing to book',
    text: 'Great work on the demo yesterday everyone, the client seemed really happy!',
  },
]

const DAY_FMT = new Intl.DateTimeFormat('en-GB', { weekday: 'short', day: '2-digit', month: 'short' })
function fmtSlotDay(iso: string) {
  const [y, m, d] = iso.split('-').map(Number)
  return DAY_FMT.format(new Date(y, (m ?? 1) - 1, d ?? 1))
}

function addMinutes(t: string, m: number): string {
  const [h, mi] = t.split(':').map(Number)
  if (isNaN(h) || isNaN(mi)) return t
  const d = new Date(2000, 0, 1, h, mi + (m || 0))
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export default function Calendar() {
  const { actor, options } = useAppData()
  const [tab, setTab] = useState<Tab>('work')
  const [input, setInput] = useState('')
  // guided-entry structured hints: optional. When set, they override what the LLM reads for
  // that one field — the text still drives title/people/location.
  const [dateHint, setDateHint] = useState('')
  const [timeHint, setTimeHint] = useState('')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<RunSchedResult | null>(null)
  const [form, setForm] = useState<Record<string, string>>({})
  const [original, setOriginal] = useState<Record<string, string>>({})
  // participants become editable: the LLM's extraction seeds the list, then the human can
  // remove a wrong one or add someone from the roster (esp. to replace an unknown).
  const [parts, setParts] = useState<{ name: string; resolved: boolean }[]>([])
  const [origParts, setOrigParts] = useState('')
  const [decided, setDecided] = useState<DecideSchedResult | null>(null)
  const [overrideReason, setOverrideReason] = useState('')
  const [deciding, setDeciding] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [events, setEvents] = useState<CalEvent[]>([])
  const [loadingCal, setLoadingCal] = useState(true)
  const [calView, setCalView] = useState<CalView>('week')
  const [routedDrafts, setRoutedDrafts] = useState<RoutedDraft[]>([])
  const [selectedDraftId, setSelectedDraftId] = useState<string | null>(null)
  const [loadingDraftId, setLoadingDraftId] = useState<string | null>(null)
  const reviewRef = useRef<HTMLDivElement | null>(null)
  const [searchParams] = useSearchParams()
  const requestedDraft = searchParams.get('draft')

  const loadCalendar = useCallback(() => {
    setLoadingCal(true)
    scheduleApi
      .calendar(actor?.id)
      .then((d) => setEvents(d.events))
      .catch(() => setEvents([]))
      .finally(() => setLoadingCal(false))
  }, [actor])

  useEffect(loadCalendar, [loadCalendar])
  const loadRoutedDrafts = useCallback(() => {
    scheduleApi
      .drafts()
      .then((response) => setRoutedDrafts(response.items))
      .catch(() => setRoutedDrafts([]))
  }, [])

  useEffect(loadRoutedDrafts, [loadRoutedDrafts])

  const locked = decided?.status === 'booked' || decided?.status === 'rejected'

  function loadReviewResult(r: RunSchedResult) {
    const init: Record<string, string> = {}

    for (const k of FIELDS) {
      const value = r.event[k]
      init[k] = value === null || value === undefined ? '' : String(value)
    }

    const participantDetails = (r.event.participant_details ?? []).map((participant) => ({
      name: participant.name,
      resolved: !!participant.resolved,
    }))

    setResult(r)
    setForm(init)
    setOriginal(init)
    setParts(participantDetails)
    setOrigParts(participantDetails.map((participant) => participant.name).join('|'))
    setDecided(null)
    setOverrideReason('')
  }

  async function run() {
    if (!input.trim()) return
    setRunning(true)
    setError(null)
    setDecided(null)
    try {
      const r = await scheduleApi.run(input.trim(), actor?.id, {
        date_hint: dateHint || undefined,
        time_hint: timeHint || undefined,
      })
      setSelectedDraftId(null)
      loadReviewResult(r)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRunning(false)
    }
  }

  async function openRoutedDraft(draftId: string) {
    setLoadingDraftId(draftId)
    setError(null)

    try {
      const review = await scheduleApi.draft(draftId)

      setSelectedDraftId(draftId)
      loadReviewResult(review)

      window.setTimeout(() => {
        reviewRef.current?.scrollIntoView({
          behavior: 'smooth',
          block: 'start',
        })
      }, 50)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoadingDraftId(null)
    }
  }

  async function decide(decision: 'approve' | 'reject', overrideSoftFlags = false) {
    if (!result) return
    let reason: string | undefined
    if (decision === 'reject') reason = window.prompt('Reason for rejection?') ?? undefined

    const ev: SchedEvent = { ...result.event }
    const bag = ev as Record<string, unknown>
    const changed: string[] = []
    for (const k of FIELDS) {
      const raw = (form[k] ?? '').trim()
      const v: string | number | null =
        raw === '' ? null : k === 'duration_minutes' ? Number(raw) : raw
      bag[k] = v
      if ((form[k] ?? '') !== (original[k] ?? '')) changed.push(k)
    }
    bag.start = ev.time ?? null
    bag.end =
      ev.time && ev.duration_minutes
        ? addMinutes(String(ev.time), Number(ev.duration_minutes))
        : null
    // the (possibly edited) participant list — names only; the backend re-resolves ids &
    // details from these, so clear the stale ones to make the edit authoritative
    bag.participant_names = parts.map((p) => p.name)
    bag.participants = []
    if (parts.map((p) => p.name).join('|') !== origParts) changed.push('participants')

    setDeciding(true)
    setError(null)
    try {
      const body = {
        event: ev,
        decision,
        reason,
        changed_fields: changed,
        reviewed_by: actor?.id ?? null,
        override_soft_flags: overrideSoftFlags,
        override_reason: overrideSoftFlags ? overrideReason.trim() : undefined,
      }

      const d = selectedDraftId
        ? await scheduleApi.decideDraft(selectedDraftId, body)
        : await scheduleApi.decide(body)
      setDecided(d)
      if (d.flags || d.alternatives) {
        setResult((current) => current ? {
          ...current,
          flags: d.flags ?? current.flags,
          alternatives: d.alternatives ?? current.alternatives,
        } : current)
      }
      if (d.status === 'booked' || d.status === 'rejected') loadCalendar()
      if (selectedDraftId) {
        loadRoutedDrafts()

        if (d.status === 'booked' || d.status === 'rejected') {
          setSelectedDraftId(null)
        }
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setDeciding(false)
    }
  }

  const ev = result?.event
  const ex = result?.extraction as Record<string, unknown> | undefined
  const flags: Flag[] = result?.flags ?? []
  const missing = result?.missing ?? []
  const prov = ev?.slot_provenance ?? {}
  const conflict = flags.some((f) => f.rule === 'conflict' || f.rule === 'room_double_booked')
  const needsOverrideConfirmation =
    decided?.status === 'requires_override_confirmation' ||
    decided?.status === 'override_reason_required'
  const edited =
    FIELDS.some((k) => (form[k] ?? '') !== (original[k] ?? '')) ||
    parts.map((p) => p.name).join('|') !== origParts
  // roster people not already on the meeting — the "add from list" options
  const rosterToAdd = (options?.actors ?? []).filter(
    (a) => !parts.some((p) => p.name === a.name),
  )

  const byDate = events.reduce<Record<string, CalEvent[]>>((acc, e) => {
    const d = e.date ?? ''
    ;(acc[d] = acc[d] ?? []).push(e)
    return acc
  }, {})

  // one form field — shared by the grouped sections below so the review pane can read as a
  // single grouped form rather than a wall of inputs
  const renderField = (k: (typeof FIELDS)[number]) => {
    const isMissing = missing.includes(k)
    const isAmbiguousDate = k === 'date' && prov.date === 'ambiguous'
    const cls = cn(
      'h-9 w-full rounded-lg border bg-surface px-2.5 text-[13.5px] outline-none transition',
      'focus:border-accent focus:ring-[3px] focus:ring-accent-ring disabled:opacity-60',
      isMissing
        ? 'border-bad shadow-[inset_3px_0_0_var(--bad)]'
        : isAmbiguousDate
          ? 'border-warn shadow-[inset_3px_0_0_var(--warn)]'
          : 'border-line-strong',
    )
    const set = (v: string) => setForm((f) => ({ ...f, [k]: v }))
    return (
      <div key={k} className="flex flex-col gap-1.5">
        <label
          htmlFor={`s_${k}`}
          className="text-[11px] font-semibold uppercase tracking-[0.05em] text-ink-3"
        >
          {labelOf(k)}
        </label>
        {k === 'mode' ? (
          <select
            id={`s_${k}`}
            disabled={locked}
            value={form[k] ?? ''}
            onChange={(e) => set(e.target.value)}
            className={cls}
          >
            <option value="in_person">in_person</option>
            <option value="virtual">virtual</option>
          </select>
        ) : k === 'date' ? (
          <DateField id={`s_${k}`} value={form[k] ?? ''} onChange={set} disabled={locked} className={cls} />
        ) : k === 'time' ? (
          <TimeField id={`s_${k}`} value={form[k] ?? ''} onChange={set} disabled={locked} className={cls} />
        ) : (
          <input
            id={`s_${k}`}
            disabled={locked}
            value={form[k] ?? ''}
            onChange={(e) => set(e.target.value)}
            className={cls}
          />
        )}
        {isMissing && <span className="text-[11.5px] text-bad">⚠ required — please fill</span>}
        {isAmbiguousDate && !isMissing && (
          <span className="text-[11.5px] text-warn">⚠ ambiguous — pick the exact day above</span>
        )}
      </div>
    )
  }

  const SectionLabel = ({ children }: { children: React.ReactNode }) => (
    <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.07em] text-ink-3">
      {children}
    </div>
  )

  return (
    <div>
      <PageHeader
        title="Meeting scheduling"
        subtitle="Agent extracts the meeting · you verify &amp; resolve conflicts · code checks &amp; books the calendar."
        right={
          <Segmented
            value={tab}
            onChange={setTab}
            options={[
              { value: 'work', label: 'Work' },
              { value: 'analytics', label: 'Analytics' },
            ]}
          />
        }
      />

      {tab === 'analytics' ? (
        <div className="mt-6">
          <Suspense
            fallback={
              <div className="rounded-xl border border-line bg-surface p-12 text-center text-[13px] text-ink-3 shadow-sm">
                Loading charts…
              </div>
            }
          >
            <CalendarAnalytics events={events} />
          </Suspense>
        </div>
      ) : (
        <div className="mt-6 flex flex-col gap-4">
          {routedDrafts.length > 0 && (
            <Card>
              <CardHeader title="Routed meeting drafts" right={<Pill tone="warn">{routedDrafts.length} awaiting review</Pill>} />
              <div className="divide-y divide-line">
                {routedDrafts.map((draft) => (
                  <div key={draft.id} className={cn('flex flex-wrap items-center justify-between gap-2 px-4 py-3', requestedDraft === draft.id && 'bg-accent-soft')}>
                    <div><div className="font-mono text-[12px] font-semibold text-ink">{draft.id}</div><div className="mt-0.5 text-[12px] text-ink-3">{draft.title ?? 'Meeting draft'} · {draft.status}{draft.missing_required?.length ? ` · missing ${draft.missing_required.join(', ')}` : ''}</div></div>
                    <div className="flex items-center gap-2">
                    <Link
                      to={draft.origin?.source_path ?? '/inbox'}
                      className="text-[12px] font-medium text-accent hover:underline"
                    >
                      View source
                    </Link>

                    <Button
                      variant="primary"
                      disabled={loadingDraftId === draft.id}
                      onClick={() => openRoutedDraft(draft.id)}
                    >
                      {loadingDraftId === draft.id ? (
                        <>
                          <Spinner />
                          Loading…
                        </>
                      ) : (
                        'Review & Book'
                      )}
                    </Button>
                  </div>
                  </div>
                ))}
              </div>
            </Card>
          )}
          <SmartSchedule actor={actor?.id} roster={options?.actors ?? []} events={events} onExecuted={loadCalendar} />

          {/* request */}
          <Card>
            <div className="p-4">
              <div className="mb-1.5 flex items-center justify-between gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-[0.05em] text-ink-3">Request</span>
                <select
                  aria-label="Load an example"
                  value=""
                  onChange={(e) => {
                    const ex2 = EXAMPLES.find((x) => x.label === e.target.value)
                    if (ex2) setInput(ex2.text)
                  }}
                  className="max-w-[240px] rounded-md border border-line-strong bg-surface px-2 py-1 text-[11.5px] text-ink-2 outline-none focus:border-accent"
                >
                  <option value="" disabled>
                    Load an example…
                  </option>
                  {EXAMPLES.map((x) => (
                    <option key={x.label} value={x.label}>
                      {x.label}
                    </option>
                  ))}
                </select>
              </div>
              <textarea
                aria-label="Meeting request"
                rows={3}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="e.g. Set up a 1 hour Q3 budget review with Bob and Chen next Tuesday at 14:00 in Orion"
                className="w-full resize-y rounded-lg border border-line-strong bg-surface p-2.5 text-[13.5px] outline-none focus:border-accent focus:ring-[3px] focus:ring-accent-ring"
              />
              {/* Guided-entry hints (optional): the text still feeds the LLM; picking a date
                  or time here just pins that field, avoiding relative-date ambiguity. */}
              <div className="mt-2.5 flex flex-wrap items-center gap-3">
                <span className="text-[11px] font-medium text-ink-3">
                  Optionally pin a slot:
                </span>
                <div className="w-[150px]">
                  <DateField
                    ariaLabel="Pin a date"
                    value={dateHint}
                    onChange={setDateHint}
                    className="h-[26px] w-full rounded-md border border-line-strong bg-surface px-2 text-[12.5px] text-ink outline-none focus:border-accent"
                  />
                </div>
                <div className="flex items-center gap-1.5">
                  <Clock size={13} strokeWidth={1.7} className="text-ink-3" />
                  <TimeField
                    ariaLabel="Pin a time"
                    value={timeHint}
                    onChange={setTimeHint}
                    className="h-[26px] w-[92px] rounded-md border border-line-strong bg-surface px-2 text-[12.5px] text-ink outline-none focus:border-accent"
                  />
                </div>
                {(dateHint || timeHint) && (
                  <button
                    type="button"
                    onClick={() => {
                      setDateHint('')
                      setTimeHint('')
                    }}
                    className="text-[11.5px] text-ink-3 underline hover:text-ink"
                  >
                    clear
                  </button>
                )}
              </div>
              <Button variant="primary" className="mt-3" onClick={run} disabled={running || !input.trim()}>
                {running ? (
                  <>
                    <Spinner /> Extracting…
                  </>
                ) : (
                  'Extract meeting'
                )}
              </Button>
            </div>
          </Card>

          {error && (
            <div className="rounded-lg border border-bad bg-bad-soft px-4 py-3 text-[13px] text-bad">{error}</div>
          )}

          {/* review */}
          {result && (
            <div ref={reviewRef}>
            <Card>
              <CardHeader
                title="Review meeting — verify &amp; resolve conflicts"
                right={
                  flags.length > 0 ? (
                    <Pill tone={conflict ? 'warn' : 'neutral'}>{flags.length} checks</Pill>
                  ) : (
                    <Pill tone="ok">no conflicts</Pill>
                  )
                }
              />
              <div className="flex flex-col gap-4 p-4">
                {/* alerts — only what the human must act on, always visible */}
                {(flags.length > 0 || missing.length > 0) && (
                  <div className="flex flex-wrap gap-2">
                    {flags.map((f, i) => (
                      <FlagChip key={`${f.rule}-${i}`} severity={f.severity}>
                        {f.message}
                      </FlagChip>
                    ))}
                    {missing.length > 0 && (
                      <FlagChip severity="hard">missing: {missing.join(', ')}</FlagChip>
                    )}
                  </div>
                )}

                {/* agent reasoning — folded away by default; the model-vs-code transparency
                    is here on demand, in the shared panel WF3 also uses (same labels) */}
                <AgentReasoning>
                  <Trace label="date" read={ex?.date ? String(ex.date) : null} resolved={ev?.date} />
                  <Trace
                    label="time"
                    read={ex?.time ? String(ex.time) : null}
                    resolved={ev?.start ? `${ev.start}–${ev.end}` : null}
                  />
                  <Trace
                    label="people"
                    read={Array.isArray(ex?.participants) ? (ex.participants as string[]).join(', ') : null}
                    resolved={
                      ev?.participant_details?.length
                        ? ev.participant_details.map((p) => `${p.name}${p.resolved ? ' ✓' : ' (unresolved)'}`).join(', ')
                        : null
                    }
                  />
                  <Trace
                    label="checks"
                    read={null}
                    resolved={conflict ? '⚠ clash found' : 'no conflicts ✓'}
                    bad={conflict}
                  />
                </AgentReasoning>

                {/* the form — the main event now: full width, grouped by what/when/who/where */}
                <div>
                  <SectionLabel>What</SectionLabel>
                  {renderField('title')}
                </div>
                <div>
                  <SectionLabel>When</SectionLabel>
                  <div className="grid gap-3 sm:grid-cols-3">
                    {renderField('date')}
                    {renderField('time')}
                    {renderField('duration_minutes')}
                  </div>
                </div>
                <div>
                  <SectionLabel>Who</SectionLabel>
                  <div className="flex flex-wrap items-center gap-2">
                    {parts.map((p, i) => (
                      <span
                        key={`${p.name}-${i}`}
                        className={cn(
                          'inline-flex h-[26px] items-center gap-1.5 rounded-full pl-2.5 pr-1 text-[12px] font-medium',
                          p.resolved ? 'bg-ok-soft text-ok' : 'bg-bad-soft text-bad',
                        )}
                      >
                        <span className="size-1.5 rounded-full bg-current opacity-70" />
                        {p.name}
                        {!p.resolved && ' · unknown'}
                        {!locked && (
                          <button
                            type="button"
                            aria-label={`Remove ${p.name}`}
                            onClick={() => setParts((ps) => ps.filter((_, j) => j !== i))}
                            className="grid size-4 place-items-center rounded-full hover:bg-black/10"
                          >
                            <X size={11} strokeWidth={2.2} />
                          </button>
                        )}
                      </span>
                    ))}

                    {!locked && rosterToAdd.length > 0 && (
                      <select
                        aria-label="Add a participant from the roster"
                        value=""
                        onChange={(e) => {
                          const name = e.target.value
                          if (name) setParts((ps) => [...ps, { name, resolved: true }])
                        }}
                        className="h-[26px] rounded-full border border-dashed border-line-strong bg-surface px-2.5 text-[12px] text-ink-2 outline-none focus:border-accent"
                      >
                        <option value="" disabled>
                          + add from list
                        </option>
                        {rosterToAdd.map((a) => (
                          <option key={a.id} value={a.name}>
                            {a.name}
                          </option>
                        ))}
                      </select>
                    )}

                    {parts.length === 0 && (
                      <span className="text-[12.5px] text-bad">⚠ no participants — add someone</span>
                    )}
                  </div>
                </div>
                <div>
                  <SectionLabel>Where &amp; how</SectionLabel>
                  <div className="grid gap-3 sm:grid-cols-2">
                    {renderField('location')}
                    {renderField('mode')}
                  </div>
                </div>
                <div>
                  <SectionLabel>Notes</SectionLabel>
                  {renderField('agenda')}
                </div>

                {(result.alternatives?.length ?? 0) > 0 && !locked && (
                    <div className="mt-3 rounded-lg border border-line bg-surface-2 p-3">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.05em] text-ink-3">
                        Free slots the code found
                      </div>
                      <p className="mt-1 text-[11.5px] text-ink-3">
                        Everyone and the room are free in these. Picking one fills the form —
                        the checks re-run against your choice when you book.
                      </p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {result.alternatives!.map((s2) => (
                          <button
                            key={`${s2.date}-${s2.start}`}
                            type="button"
                            onClick={() => setForm((f) => ({ ...f, date: s2.date, time: s2.start }))}
                            className="rounded-lg border border-line-strong bg-surface px-2.5 py-1.5 text-[12.5px] tabular-nums transition-colors hover:border-accent hover:text-accent"
                          >
                            {fmtSlotDay(s2.date)} · {s2.start}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {edited && !locked && (
                    <p className="mt-3 rounded-lg border border-warn bg-warn-soft px-3 py-2 text-[11.5px] text-warn">
                      ⟳ Fields changed — the code re-runs the conflict &amp; policy checks against your edits when you book.
                    </p>
                  )}

                  {decided?.status === 'booked' && (
                    <div className="mt-3 rounded-lg border border-ok bg-ok-soft px-3.5 py-3 text-[13px] text-ok">
                      <b>Booked.</b> Event <code>{decided.record_id}</code> is on the calendar
                      {decided.overridden_flags?.length
                        ? ` · overrode ${decided.overridden_flags.length} soft flag(s)`
                        : ''}
                      {' · '}
                      {decided.notifications?.length ?? 0} notification(s).
                      {decided.ics && (
                        <a
                          className="ml-2 inline-flex items-center gap-1 font-medium underline"
                          download="meeting.ics"
                          href={'data:text/calendar;charset=utf-8,' + encodeURIComponent(decided.ics)}
                        >
                          <Download size={12} strokeWidth={1.8} /> Download .ics
                        </a>
                      )}
                      {decided.calendar_backend?.status === 'booked' && decided.calendar_backend.html_link && (
                        <a
                          className="ml-2 inline-flex items-center gap-1 font-medium underline"
                          href={decided.calendar_backend.html_link}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <ExternalLink size={12} strokeWidth={1.8} /> View in Google Calendar
                        </a>
                      )}
                    </div>
                  )}
                  {/* Real-calendar sync failed but the booking itself succeeded — must never
                      read as if the meeting wasn't booked. Muted, not an error banner. */}
                  {decided?.status === 'booked' && decided.calendar_backend?.status === 'error' && (
                    <p className="mt-1.5 text-[11.5px] text-ink-3">
                      Google Calendar sync failed (local booking still succeeded).
                    </p>
                  )}
                  {decided?.status === 'rejected' && (
                    <div className="mt-3 rounded-lg border border-line bg-surface-2 px-3.5 py-3 text-[13px] text-ink-2">
                      <b>Rejected</b> — logged as <code>{decided.record_id}</code>.
                    </div>
                  )}
                  {decided?.status === 'blocked_missing_required' && (
                    <div className="mt-3 rounded-lg border border-warn bg-warn-soft px-3.5 py-3 text-[13px] text-warn">
                      <b>Blocked</b> — missing: {(decided.missing ?? []).join(', ')}.
                    </div>
                  )}

                  {needsOverrideConfirmation && (
                    <div className="mt-3 rounded-lg border border-warn bg-warn-soft px-3.5 py-3 text-[13px] text-warn">
                      <b>Not booked — live conflicts still exist.</b>
                      <p className="mt-1 text-[12px]">
                        Pick one of the free slots above and recheck, or explicitly justify
                        why this clash should be overridden.
                      </p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {(decided.flags ?? []).map((flag, index) => (
                          <FlagChip key={`live-${flag.rule}-${index}`} severity={flag.severity}>
                            {flag.message}
                          </FlagChip>
                        ))}
                      </div>
                      <label className="mt-3 block text-[11px] font-semibold uppercase tracking-[.05em]">
                        Override reason
                        <input
                          value={overrideReason}
                          onChange={(event) => setOverrideReason(event.target.value)}
                          placeholder="Required for the audit trail"
                          className="mt-1 h-9 w-full rounded-lg border border-warn bg-surface px-2.5 text-[13px] font-normal normal-case text-ink outline-none"
                        />
                      </label>
                      <div className="mt-2 flex justify-end">
                        <Button
                          variant="danger"
                          disabled={deciding || !overrideReason.trim()}
                          onClick={() => decide('approve', true)}
                        >
                          {deciding ? <Spinner /> : 'Override warnings & book'}
                        </Button>
                      </div>
                    </div>
                  )}

                <div className="mt-1 flex justify-end gap-2">
                  <Button variant="danger" disabled={deciding || locked} onClick={() => decide('reject')}>
                    Reject
                  </Button>
                  <Button variant="primary" disabled={deciding || locked} onClick={() => decide('approve')}>
                    {deciding ? <Spinner /> : needsOverrideConfirmation ? 'Recheck after edits →' : 'Book →'}
                  </Button>
                </div>
              </div>
            </Card>
            </div>
          )}
          

          {/* calendar */}
          <Card>
            <CardHeader
              title={actor ? `${actor.name}'s calendar` : 'Calendar'}
              right={
                <div className="flex items-center gap-2">
                  <Pill tone="neutral">{events.length} events</Pill>
                  <Segmented
                    value={calView}
                    onChange={setCalView}
                    options={[
                      { value: 'week', label: 'Week' },
                      { value: 'list', label: 'List' },
                    ]}
                  />
                </div>
              }
            />
            {loadingCal ? (
              <Empty>
                <Spinner /> Loading…
              </Empty>
            ) : calView === 'week' ? (
              <WeekGrid events={events} />
            ) : events.length === 0 ? (
              <Empty>No meetings booked.</Empty>
            ) : (
              Object.keys(byDate)
                .sort()
                .map((date) => (
                  <div key={date} className="border-t border-line first:border-t-0">
                    <div className="flex items-center gap-2 bg-surface-2 px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">
                      <CalendarDays size={12} strokeWidth={1.8} />
                      {date}
                    </div>
                    {byDate[date].map((e) => (
                      <div key={e.id} className="flex gap-4 border-t border-line px-4 py-3">
                        <div className="w-28 shrink-0 text-[12.5px] font-semibold tabular-nums text-accent">
                          {e.start}–{e.end}
                        </div>
                        <div className="min-w-0">
                          <div className="text-[13.5px] font-medium text-ink">{e.title}</div>
                          <div className="mt-0.5 text-[12px] text-ink-3">
                            {e.participants.join(', ')}
                            {e.location ? ` · ${e.location}` : ''}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ))
            )}
          </Card>
        </div>
      )}
    </div>
  )
}
