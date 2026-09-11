import { useMemo, useState } from 'react'
import { AlertTriangle, CalendarSearch, CheckCircle2, RefreshCw } from 'lucide-react'
import { smartScheduleApi, type Actor, type CalEvent, type SmartCandidate, type SmartCandidatesResult, type SmartSpec } from '@/lib/api'
import { Button, Card, CardHeader, Pill, Spinner } from '@/components/ui'
import DateField, { TimeField } from '@/components/DateField'

type Props = {
  actor?: string | null
  roster: Actor[]
  events: CalEvent[]
  onExecuted: () => void
}

const reasonText: Record<string, string> = {
  all_participants_available: 'All participants are available',
  preferred_afternoon: 'Matches your afternoon preference',
  preferred_morning: 'Matches your morning preference',
  preferred_room_available: 'Preferred room is available',
  lunch_avoided: 'Avoids the lunch period',
  earliest_preference: 'Prioritises an earlier slot',
  same_day_minimal_disruption: 'Keeps the meeting on the same day',
}

const warningText: Record<string, string> = {
  requested_time_unavailable: 'The originally requested time is unavailable',
  requested_slot_occupied: 'The originally requested slot is occupied',
}

const makeKey = () => `wf2-${Date.now()}-${Math.random().toString(36).slice(2)}`

function ParticipantPicker({
  actor,
  roster,
  selected,
  onChange,
}: {
  actor?: string | null
  roster: Actor[]
  selected: string[]
  onChange: (ids: string[]) => void
}) {
  const invitees = roster.filter((person) => person.id !== actor)
  const names = selected.map((id) => roster.find((person) => person.id === id)?.name ?? id)
  return (
    <details className="min-w-0 rounded-lg border border-line-strong bg-surface text-[13px] text-ink">
      <summary className="flex min-h-9 cursor-pointer list-none items-center justify-between gap-2 px-2.5 marker:hidden [&::-webkit-details-marker]:hidden">
        <span className={names.length ? 'truncate' : 'text-ink-3'}>
          {names.length ? names.join(', ') : 'Select participants…'}
        </span>
        <span className="shrink-0 text-[11px] text-ink-3">{names.length || ''} ▾</span>
      </summary>
      <fieldset className="border-t border-line px-2.5 py-2">
        <legend className="sr-only">Participants</legend>
        <div className="grid gap-1 sm:grid-cols-2">
          {invitees.map((person) => (
            <label key={person.id} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 hover:bg-surface-2">
              <input
                type="checkbox"
                checked={selected.includes(person.id)}
                onChange={(event) => onChange(event.target.checked
                  ? [...selected, person.id]
                  : selected.filter((id) => id !== person.id))}
              />
              <span>{person.name}</span>
            </label>
          ))}
        </div>
      </fieldset>
    </details>
  )
}

export default function SmartSchedule({ actor, roster, events, onExecuted }: Props) {
  const [operation, setOperation] = useState<NonNullable<SmartSpec['operation']>>('CREATE')
  const [target, setTarget] = useState('')
  const [title, setTitle] = useState('')
  const [people, setPeople] = useState<string[]>([])
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [flexibleDates, setFlexibleDates] = useState(false)
  const [time, setTime] = useState('')
  const [duration, setDuration] = useState('30')
  const [location, setLocation] = useState('')
  const [period, setPeriod] = useState('')
  const [result, setResult] = useState<SmartCandidatesResult | null>(null)
  const [selected, setSelected] = useState<SmartCandidate | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [idempotencyKey, setIdempotencyKey] = useState(makeKey)
  const [executed, setExecuted] = useState(false)

  const targetEvent = useMemo(() => events.find((event) => event.id === target), [events, target])
  const needsTarget = operation === 'UPDATE' || operation === 'RESCHEDULE' || operation === 'CANCEL' || operation === 'REUSE'

  function selectTarget(eventId: string) {
    setTarget(eventId)
    const event = events.find((item) => item.id === eventId)
    if (!event) return
    setTitle(event.title ?? '')
    setPeople(event.participants.map((value) => {
      const normalised = value.trim().toLowerCase()
      return roster.find((person) =>
        person.id === normalised
        || person.name.toLowerCase() === normalised
        || person.name.split(' ')[0].toLowerCase() === normalised)?.id ?? value
    }).filter((value) => value !== actor))
    setStart(event.date ?? '')
    setTime(event.start ?? '')
    setDuration(String(event.duration_minutes ?? 30))
    setLocation(event.location ?? '')
    setResult(null)
    setSelected(null)
    setExecuted(false)
  }

  const spec = (): SmartSpec => ({
    operation,
    target_event_id: target || undefined,
    title: title || targetEvent?.title || 'Untitled meeting',
    // The acting user is the organiser and participates in availability checks even when
    // they do not explicitly select themselves in the picker.
    participants: [...new Set([...(actor ? [actor] : []), ...people])],
    duration_minutes: Number(duration) || 30,
    date_window: {
      start: start || undefined,
      end: flexibleDates && end ? end : start || undefined,
    },
    exact_time: time || undefined,
    location: location || undefined,
    mode: 'virtual',
    soft_preferences: { preferred_period: period || undefined },
    provenance: { title: title ? 'manual_edit' : 'current_request' },
  })

  async function findCandidates() {
    setBusy(true)
    setMessage(null)
    setSelected(null)
    setExecuted(false)
    setIdempotencyKey(makeKey())
    try {
      const response = await smartScheduleApi.candidates(spec(), actor)
      setResult(response)
      const hardBlockers = response.blockers.filter((code) => code !== 'requested_time_unavailable')
      setMessage(response.missing.length
        ? `Please provide: ${response.missing.join(', ').replaceAll('_', ' ')}`
        : hardBlockers.length
          ? hardBlockers.join(', ').replaceAll('_', ' ')
          : null)
    } catch (error) {
      setMessage((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function reuse() {
    if (!target) return
    setBusy(true)
    try {
      const response = await smartScheduleApi.reuse(target)
      const draft = response.spec
      setTitle(draft.title ?? '')
      setPeople((draft.participants ?? []).map((value) => {
        const normalised = value.trim().toLowerCase()
        return roster.find((person) =>
          person.id === normalised
          || person.name.toLowerCase() === normalised
          || person.name.split(' ')[0].toLowerCase() === normalised)?.id ?? value
      }).filter((value) => value !== actor))
      setDuration(String(draft.duration_minutes ?? 30))
      setLocation(draft.location ?? '')
      setOperation('REUSE')
      setMessage('Previous meeting details loaded. Choose a new date window.')
    } catch (error) {
      setMessage((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function approve() {
    if (!result || executed || (operation !== 'CANCEL' && !selected)) return
    setBusy(true)
    try {
      const execute = (activeResult: SmartCandidatesResult, candidate?: SmartCandidate) =>
        smartScheduleApi.execute({
          spec: activeResult.spec,
          candidate,
          actor,
          idempotency_key: idempotencyKey,
          validation_token: activeResult.validation_token,
          calendar_version: activeResult.calendar_version,
        })

      let response = await execute(result, selected ?? undefined)
      if (response.status === 'stale_validation' && selected) {
        const refreshed = await smartScheduleApi.candidates(result.spec, actor)
        setResult(refreshed)
        const replacement = refreshed.candidates.find((candidate) =>
          candidate.date === selected.date
          && candidate.start === selected.start
          && candidate.end === selected.end)
        if (!replacement) {
          setSelected(null)
          setMessage('The calendar changed and this slot is no longer available. Options have been refreshed; choose another slot.')
          return
        }
        setSelected(replacement)
        response = await execute(refreshed, replacement)
      }
      setMessage(response.status === 'booked'
        ? response.calendar_backend?.status === 'booked'
          ? `Booked ${response.record_id} · synced to Google Calendar`
          : response.calendar_backend?.status === 'error'
            ? `Booked ${response.record_id} · Google Calendar sync failed`
            : `Booked ${response.record_id}`
        : response.message ?? response.status.replaceAll('_', ' '))
      if (response.status === 'booked' || response.status === 'cancelled' || response.status === 'update' || response.status === 'reschedule' || response.status === 'idempotent_replay') {
        setExecuted(true)
        onExecuted()
      }
    } catch (error) {
      setMessage((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader
        title="Smart Schedule"
        right={<Pill tone="neutral">Top 3 · review required</Pill>}
      />
      <div className="flex flex-col gap-3 p-4">
        <p className="text-[12.5px] text-ink-3">
          Search a time window, compare deterministic options, then select one for approval.
        </p>
        <div className="grid gap-3 md:grid-cols-3">
          <label className="text-[11px] font-semibold uppercase tracking-[.05em] text-ink-3">
            Operation
            <select value={operation} onChange={(e) => setOperation(e.target.value as NonNullable<SmartSpec['operation']>)} className="mt-1.5 h-9 w-full rounded-lg border border-line-strong bg-surface px-2 text-[13px] text-ink">
              {['CREATE', 'UPDATE', 'RESCHEDULE', 'CANCEL', 'REUSE'].map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
          {needsTarget && (
            <label className="text-[11px] font-semibold uppercase tracking-[.05em] text-ink-3">
              Existing event
              <select value={target} onChange={(e) => selectTarget(e.target.value)} className="mt-1.5 h-9 w-full rounded-lg border border-line-strong bg-surface px-2 text-[13px] text-ink">
                <option value="">Select an event…</option>
                {events.map((event) => <option key={event.id} value={event.id}>{event.title} · {event.date} {event.start}</option>)}
              </select>
            </label>
          )}
          {operation === 'REUSE' && <Button variant="secondary" className="self-end" disabled={!target || busy} onClick={reuse}>Load previous context</Button>}
        </div>

        {operation !== 'CANCEL' && (
          <>
            <div className="grid gap-3 md:grid-cols-2">
              <input aria-label="Meeting title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Meeting title" className="h-9 rounded-lg border border-line-strong bg-surface px-2.5 text-[13px]" />
              <ParticipantPicker actor={actor} roster={roster} selected={people} onChange={setPeople} />
            </div>
            <p className="text-[11px] text-ink-3">
              The acting user is included automatically as organiser; select one or more additional participants.
            </p>
            <div className="grid min-w-0 gap-3 md:grid-cols-3">
              <label className="min-w-0 text-[11px] font-semibold uppercase tracking-[.05em] text-ink-3">
                Meeting date
                <DateField ariaLabel="Meeting date" value={start} onChange={setStart} className="mt-1 h-9 rounded-lg border border-line-strong bg-surface px-2.5 text-[13px] font-normal normal-case text-ink" />
              </label>
              <label className="min-w-0 text-[11px] font-semibold uppercase tracking-[.05em] text-ink-3">
                Exact time <span className="font-normal normal-case">(optional)</span>
                <TimeField ariaLabel="Optional exact time" value={time} onChange={setTime} className="mt-1 h-9 rounded-lg border border-line-strong bg-surface px-2.5 text-[13px] font-normal normal-case text-ink" />
              </label>
              <label className="min-w-0 text-[11px] font-semibold uppercase tracking-[.05em] text-ink-3">
                Duration (minutes)
                <input value={duration} type="number" min="15" step="15" onChange={(e) => setDuration(e.target.value)} className="mt-1 h-9 w-full min-w-0 rounded-lg border border-line-strong bg-surface px-2.5 text-[13px] font-normal normal-case text-ink" />
              </label>
              <label className="min-w-0 text-[11px] font-semibold uppercase tracking-[.05em] text-ink-3">
                Room / location
                <input value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Optional" className="mt-1 h-9 w-full min-w-0 rounded-lg border border-line-strong bg-surface px-2.5 text-[13px] font-normal normal-case text-ink" />
              </label>
              <label className="min-w-0 text-[11px] font-semibold uppercase tracking-[.05em] text-ink-3">
                Time preference
                <select value={period} onChange={(e) => setPeriod(e.target.value)} className="mt-1 h-9 w-full min-w-0 rounded-lg border border-line-strong bg-surface px-2.5 text-[13px] font-normal normal-case text-ink">
                  <option value="">No preference</option><option value="morning">Prefer morning</option><option value="afternoon">Prefer afternoon</option>
                </select>
              </label>
              <label className="flex min-h-14 cursor-pointer items-center gap-2 self-end rounded-lg border border-line bg-surface-2 px-3 text-[12px] font-medium text-ink-2">
                <input type="checkbox" checked={flexibleDates} onChange={(event) => { setFlexibleDates(event.target.checked); if (!event.target.checked) setEnd('') }} />
                Search across multiple days
              </label>
              {flexibleDates && (
                <label className="min-w-0 text-[11px] font-semibold uppercase tracking-[.05em] text-ink-3">
                  Latest acceptable date
                  <DateField ariaLabel="Latest acceptable date" value={end} onChange={setEnd} className="mt-1 h-9 rounded-lg border border-line-strong bg-surface px-2.5 text-[13px] font-normal normal-case text-ink" />
                </label>
              )}
            </div>
          </>
        )}

        <div className="flex justify-end">
          <Button variant="primary" disabled={busy || (needsTarget && !target)} onClick={operation === 'CANCEL' ? () => { setExecuted(false); setIdempotencyKey(makeKey()); setResult({ spec: spec(), candidates: [], missing: [], blockers: [], warnings: [], validation_token: null, calendar_version: null }) } : findCandidates}>
            {busy ? <Spinner /> : <CalendarSearch size={15} />} {operation === 'CANCEL' ? 'Review cancellation' : 'Find options'}
          </Button>
        </div>

        {result?.warnings.map((warning) => (
          <div key={`${warning.code}-${warning.date ?? ''}-${warning.start ?? ''}`} role="alert" className="flex gap-2.5 rounded-lg border border-warn bg-warn-soft px-3.5 py-3 text-[13px] text-warn">
            <AlertTriangle aria-hidden="true" size={17} className="mt-0.5 shrink-0" />
            <div>
              <b>Selected time conflict</b>
              <p className="mt-0.5">{warning.message}</p>
            </div>
          </div>
        ))}

        {result && operation !== 'CANCEL' && (
          <div className="grid gap-3 lg:grid-cols-3">
            {result.candidates.map((candidate) => (
              <button key={candidate.candidate_id} type="button" onClick={() => setSelected(candidate)} className={"rounded-xl border p-3 text-left transition " + (selected?.candidate_id === candidate.candidate_id ? 'border-accent bg-accent-soft' : 'border-line hover:border-accent')}>
                <div className="flex items-center justify-between gap-2"><b className="text-[13px]">{candidate.label.replaceAll('_', ' ')}</b><CheckCircle2 size={15} className={selected?.candidate_id === candidate.candidate_id ? 'text-accent' : 'text-ink-3'} /></div>
                <div className="mt-2 text-[13px] font-medium tabular-nums">{candidate.date} · {candidate.start}–{candidate.end}</div>
                <ul className="mt-2 space-y-1 text-[11.5px] text-ink-3">{candidate.reason_codes.map((reason) => <li key={reason}>• {reasonText[reason] ?? reason.replaceAll('_', ' ')}</li>)}</ul>
                {candidate.warning_codes.length > 0 && (
                  <ul className="mt-2 space-y-1 text-[11.5px] text-warn">
                    {candidate.warning_codes.map((warning) => <li key={warning}>⚠ {warningText[warning] ?? warning.replaceAll('_', ' ')}</li>)}
                  </ul>
                )}
              </button>
            ))}
          </div>
        )}

        {result && (
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={findCandidates} disabled={busy || executed || operation === 'CANCEL'}><RefreshCw size={14} /> Revalidate</Button>
            <Button variant="primary" onClick={approve} disabled={busy || executed || (operation !== 'CANCEL' && !selected)}>{executed ? 'Executed' : `Approve ${operation.toLowerCase()} →`}</Button>
          </div>
        )}
        {message && <p className="text-[12.5px] text-ink-3">{message}</p>}
      </div>
    </Card>
  )
}
