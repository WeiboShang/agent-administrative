import { useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { CalEvent } from '@/lib/api'
import { cn } from '@/lib/utils'

// Working-hours window the grid renders. Matches policy.WORKING_HOURS on the backend.
const OPEN_H = 9
const CLOSE_H = 18
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

// Dates here are plain YYYY-MM-DD (no timezone), so format from local Date parts rather
// than `toISOString()`, which can shift the day for non-UTC viewers.
const isoLocal = (d: Date): string =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const minutes = (hhmm?: string): number => {
  if (!hhmm) return OPEN_H * 60
  const [h, m] = hhmm.split(':').map(Number)
  return (h || 0) * 60 + (m || 0)
}
function weekMonday(d: Date): Date {
  const x = new Date(d)
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7)) // Mon = 0
  x.setHours(0, 0, 0, 0)
  return x
}

/**
 * A stateful week grid — see the calendar, don't just read a list. Booked meetings are laid
 * out by time; a meeting that overlaps another on the same day is flagged amber (the same
 * clash the conflict check detects). Deliberately a plain CSS grid, not a calendar library.
 */
export default function WeekGrid({ events }: { events: CalEvent[] }) {
  // A workspace calendar should open where the user is working now. Historical/future
  // events remain reachable with the arrows and List view, but must not move the initial
  // week away from today merely because they are the earliest stored records.
  const [monday, setMonday] = useState(() => weekMonday(new Date()))

  const days = useMemo(
    () => Array.from({ length: 7 }, (_, i) => {
      const d = new Date(monday)
      d.setDate(d.getDate() + i)
      return d
    }),
    [monday],
  )

  // group events by local ISO day, and mark overlaps within a day
  const byDay = useMemo(() => {
    const map = new Map<string, (CalEvent & { clash?: boolean })[]>()
    for (const e of events) {
      if (!e.date) continue
      const arr = map.get(e.date) ?? []
      arr.push({ ...e })
      map.set(e.date, arr)
    }
    for (const arr of map.values()) {
      for (let i = 0; i < arr.length; i++) {
        for (let j = i + 1; j < arr.length; j++) {
          const a = arr[i]
          const b = arr[j]
          if (minutes(a.start) < minutes(b.end) && minutes(b.start) < minutes(a.end)) {
            a.clash = b.clash = true
          }
        }
      }
    }
    return map
  }, [events])

  const hours = Array.from({ length: CLOSE_H - OPEN_H }, (_, i) => OPEN_H + i)
  const spanMin = (CLOSE_H - OPEN_H) * 60
  const shift = (n: number) => {
    const m = new Date(monday)
    m.setDate(m.getDate() + n * 7)
    setMonday(m)
  }
  const label = `${days[0].toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })} – ${days[6].toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}`

  return (
    <div>
      <div className="flex items-center justify-between px-4 py-3">
        <span className="text-[13px] font-medium text-ink">{label}</span>
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => shift(-1)}
            className="grid size-7 place-items-center rounded-md border border-line-strong text-ink-2 hover:bg-surface-2"
          >
            <ChevronLeft size={15} />
          </button>
          <button
            type="button"
            onClick={() => setMonday(weekMonday(new Date()))}
            className="rounded-md border border-line-strong px-2.5 text-[12px] text-ink-2 hover:bg-surface-2"
          >
            Today
          </button>
          <button
            type="button"
            onClick={() => shift(1)}
            className="grid size-7 place-items-center rounded-md border border-line-strong text-ink-2 hover:bg-surface-2"
          >
            <ChevronRight size={15} />
          </button>
        </div>
      </div>

      <div className="overflow-x-auto border-t border-line">
        <div className="grid min-w-[880px] grid-cols-[48px_repeat(7,1fr)]">
          {/* header row */}
          <div className="border-b border-line" />
          {days.map((d) => {
            const isToday = isoLocal(d) === isoLocal(new Date())
            const isWeekend = d.getDay() === 0 || d.getDay() === 6
            return (
              <div
                key={isoLocal(d)}
                className={cn(
                  'border-b border-l border-line px-2 py-1.5 text-center',
                  isWeekend && 'bg-surface-2/70',
                )}
              >
                <div className="text-[10px] uppercase tracking-[0.06em] text-ink-3">
                  {WEEKDAYS[(d.getDay() + 6) % 7]}
                </div>
                <div className={cn('text-[13px] font-semibold', isToday ? 'text-accent' : 'text-ink')}>
                  {d.getDate()}
                </div>
              </div>
            )
          })}

          {/* hour-labels column */}
          <div className="relative" style={{ height: `${hours.length * 44}px` }}>
            {hours.map((h) => (
              <div
                key={h}
                className="absolute right-1.5 -translate-y-1/2 text-[10px] tabular-nums text-ink-3"
                style={{ top: `${((h - OPEN_H) * 60 * 100) / spanMin}%` }}
              >
                {h}:00
              </div>
            ))}
          </div>

          {/* day columns */}
          {days.map((d) => {
            const iso = isoLocal(d)
            const dayEvents = byDay.get(iso) ?? []
            const isWeekend = d.getDay() === 0 || d.getDay() === 6
            return (
              <div
                key={iso}
                className={cn(
                  'relative border-l border-line',
                  isWeekend && 'bg-surface-2/40',
                )}
                style={{ height: `${hours.length * 44}px` }}
              >
                {hours.map((h) => (
                  <div
                    key={h}
                    className="absolute inset-x-0 border-b border-line/60"
                    style={{ top: `${((h - OPEN_H) * 60 * 100) / spanMin}%`, height: `${(60 * 100) / spanMin}%` }}
                  />
                ))}
                {dayEvents.map((e) => {
                  const durMin = minutes(e.end) - minutes(e.start)
                  const top = ((minutes(e.start) - OPEN_H * 60) * 100) / spanMin
                  const height = Math.max(4, (durMin * 100) / spanMin)
                  // a 30-min block is too short for two lines — show the time only when the
                  // block is tall enough (≥45 min); the time is always in the hover tooltip
                  const showTime = durMin >= 45
                  return (
                    <div
                      key={e.id}
                      title={`${e.title} · ${e.start}–${e.end}${e.clash ? ' · overlaps another meeting' : ''}`}
                      className={cn(
                        'absolute inset-x-1 flex flex-col overflow-hidden rounded-md border px-1.5 py-0.5 text-[10.5px] leading-tight',
                        e.clash
                          ? 'border-warn bg-warn-soft text-warn'
                          : 'border-accent/40 bg-accent-soft text-ink',
                      )}
                      style={{ top: `${top}%`, height: `${height}%` }}
                    >
                      <div className="truncate font-medium">{e.title || 'Untitled'}</div>
                      {showTime && (
                        <div className="truncate tabular-nums opacity-80">
                          {e.start}–{e.end}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )
          })}
        </div>
      </div>

      {events.length === 0 && (
        <div className="px-4 py-6 text-center text-[13px] text-ink-3">No meetings booked.</div>
      )}
    </div>
  )
}
