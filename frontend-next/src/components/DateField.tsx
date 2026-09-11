import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react'
import { isIsoDate } from '@/lib/format'
import { cn } from '@/lib/utils'

/**
 * Date field with an English calendar popup.
 *
 * Why not `<input type="date">`: Chrome renders that control's placeholder AND its whole
 * picker panel in the BROWSER's UI locale — a Chinese-locale browser shows 年/月/日 and a
 * fully Chinese panel. The page cannot override it: `lang` on the document and on the element
 * are both ignored (verified). So the picker is ours, and it is English by construction.
 *
 * The value contract is unchanged — plain ISO `YYYY-MM-DD` in, same out — so callers,
 * validation and the backend are untouched. Typing stays possible (keyboard + paste); the
 * popup is the mouse path.
 */

/**
 * Time field, locale-proof for the same reason: `<input type="time">` renders an AM/PM
 * segment in the browser's locale (上午/下午 on a Chinese browser). A plain text input with a
 * 24h `HH:MM` placeholder plus a datalist of half-hour slots keeps the quick-pick affordance
 * and stays English by construction. Value contract unchanged: `HH:MM`.
 */
export function TimeField({
  id,
  value,
  onChange,
  disabled,
  className,
  ariaLabel,
}: {
  id?: string
  value: string
  onChange: (hhmm: string) => void
  disabled?: boolean
  className?: string
  ariaLabel?: string
}) {
  const listId = useId()
  return (
    <>
      <input
        id={id}
        aria-label={ariaLabel}
        disabled={disabled}
        value={value}
        placeholder="HH:MM"
        list={listId}
        inputMode="numeric"
        onChange={(e) => onChange(e.target.value)}
        className={cn('min-w-0 w-full', className)}
      />
      <datalist id={listId}>
        {TIME_SLOTS.map((t) => (
          <option key={t} value={t} />
        ))}
      </datalist>
    </>
  )
}

// half-hour slots across a working day — the quick-pick list behind the time input
const TIME_SLOTS = Array.from({ length: 24 }, (_, i) => {
  const h = 8 + Math.floor(i / 2)
  return `${String(h).padStart(2, '0')}:${i % 2 ? '30' : '00'}`
}).filter((t) => Number(t.slice(0, 2)) <= 19)

const WEEKDAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
                'July', 'August', 'September', 'October', 'November', 'December']
const PANEL_W = 250
const PANEL_H = 310

// Dates are plain YYYY-MM-DD with no timezone. Parse/format in LOCAL time — `new Date(iso)`
// and `toISOString()` both round-trip through UTC and shift the day for non-UTC viewers.
const parseLocal = (iso: string): Date => {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, (m ?? 1) - 1, d ?? 1)
}
const isoLocal = (d: Date): string =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

export default function DateField({
  id,
  value,
  onChange,
  disabled,
  className,
  ariaLabel,
  expectedTiming = 'future',
}: {
  id?: string
  value: string
  onChange: (iso: string) => void
  disabled?: boolean
  className?: string
  ariaLabel?: string
  /** Which side of today is normal for this business field. Dates remain selectable. */
  expectedTiming?: 'past' | 'future' | 'any'
}) {
  const [open, setOpen] = useState(false)
  const [view, setView] = useState<Date>(() => (isIsoDate(value) ? parseLocal(value) : new Date()))
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null)
  const wrapRef = useRef<HTMLDivElement>(null)

  // follow the value when it changes from outside (e.g. picking a suggested free slot)
  useEffect(() => {
    if (isIsoDate(value)) setView(parseLocal(value))
  }, [value])

  // The Card that usually contains this field is `overflow-hidden`, so an absolutely
  // positioned panel would be clipped — the panel is portalled to <body> and positioned
  // against the trigger's viewport rect instead.
  const place = useCallback(() => {
    const r = wrapRef.current?.getBoundingClientRect()
    if (!r) return
    const flipUp = window.innerHeight - r.bottom < PANEL_H && r.top > PANEL_H
    setPos({
      left: Math.min(Math.max(8, r.left), Math.max(8, window.innerWidth - PANEL_W - 8)),
      top: flipUp ? r.top - PANEL_H - 4 : r.bottom + 4,
    })
  }, [])

  useEffect(() => {
    if (!open) return
    place()
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (!wrapRef.current?.contains(t) && !(t as Element).closest?.('[data-datefield-panel]')) {
        setOpen(false)
      }
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    window.addEventListener('scroll', place, true)
    window.addEventListener('resize', place)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', place, true)
      window.removeEventListener('resize', place)
    }
  }, [open, place])

  // 6 rows × 7 days, Monday-first (matches the week grid and the density heatmap)
  const grid = useMemo(() => {
    const y = view.getFullYear()
    const m = view.getMonth()
    const lead = (new Date(y, m, 1).getDay() + 6) % 7
    return Array.from({ length: 42 }, (_, i) => {
      const d = new Date(y, m, 1 - lead + i)
      return { d, iso: isoLocal(d), inMonth: d.getMonth() === m }
    })
  }, [view])

  const todayIso = isoLocal(new Date())
  const shift = (n: number) => setView((v) => new Date(v.getFullYear(), v.getMonth() + n, 1))
  const pick = (iso: string) => {
    onChange(iso)
    setOpen(false)
  }

  return (
    <div ref={wrapRef} className="relative min-w-0">
      <input
        id={id}
        aria-label={ariaLabel}
        disabled={disabled}
        value={value}
        placeholder="YYYY-MM-DD"
        onChange={(e) => onChange(e.target.value)}
        className={cn('min-w-0 w-full pr-8', className)}
      />
      <button
        type="button"
        disabled={disabled}
        aria-label="Open calendar"
        onClick={() => setOpen((o) => !o)}
        className="absolute right-1.5 top-1/2 grid size-6 -translate-y-1/2 place-items-center rounded text-ink-3 hover:bg-surface-2 hover:text-ink disabled:opacity-50"
      >
        <CalendarDays size={14} strokeWidth={1.7} />
      </button>

      {/* Scheduling normally points forward; receipts normally point backward. Keep this
          presentation hint aligned with the field's business meaning. */}
      {isIsoDate(value) && expectedTiming === 'future' && value < todayIso && (
        <p className="mt-1 text-[11.5px] text-warn">⚠ that date is in the past</p>
      )}
      {isIsoDate(value) && expectedTiming === 'past' && value > todayIso && (
        <p className="mt-1 text-[11.5px] text-warn">⚠ that date is in the future</p>
      )}

      {open && !disabled && pos &&
        createPortal(
          <div
            data-datefield-panel
            style={{ position: 'fixed', left: pos.left, top: pos.top, width: PANEL_W }}
            className="z-50 rounded-lg border border-line-strong bg-surface p-2.5 shadow-lg"
          >
            <div className="mb-1.5 flex items-center justify-between">
              <button
                type="button"
                aria-label="Previous month"
                onClick={() => shift(-1)}
                className="grid size-6 place-items-center rounded text-ink-2 hover:bg-surface-2"
              >
                <ChevronLeft size={15} />
              </button>
              <span className="text-[12.5px] font-medium text-ink">
                {MONTHS[view.getMonth()]} {view.getFullYear()}
              </span>
              <button
                type="button"
                aria-label="Next month"
                onClick={() => shift(1)}
                className="grid size-6 place-items-center rounded text-ink-2 hover:bg-surface-2"
              >
                <ChevronRight size={15} />
              </button>
            </div>

            <div className="grid grid-cols-7 gap-0.5">
              {WEEKDAYS.map((w) => (
                <div key={w} className="grid h-6 place-items-center text-[10px] font-semibold uppercase text-ink-3">
                  {w}
                </div>
              ))}
              {grid.map((c) => {
                const selected = c.iso === value
                // Unexpected dates stay clickable: the human can still make a deliberate
                // exception, while ordinary receipt history is not visually de-emphasised.
                const unexpected = expectedTiming === 'future'
                  ? c.iso < todayIso
                  : expectedTiming === 'past' && c.iso > todayIso
                return (
                  <button
                    key={c.iso}
                    type="button"
                    onClick={() => pick(c.iso)}
                    className={cn(
                      'grid h-7 place-items-center rounded text-[12px] tabular-nums transition-colors',
                      selected
                        ? 'bg-accent font-semibold text-accent-ink'
                        : c.inMonth
                          ? 'text-ink hover:bg-surface-2'
                          : 'text-ink-3 hover:bg-surface-2',
                      !selected && unexpected && 'text-ink-3 opacity-50',
                      !selected && c.iso === todayIso && 'ring-1 ring-accent',
                    )}
                  >
                    {c.d.getDate()}
                  </button>
                )
              })}
            </div>

            <div className="mt-2 flex items-center justify-between border-t border-line pt-2 text-[12px]">
              <button
                type="button"
                onClick={() => pick('')}
                className="rounded px-1.5 py-0.5 text-ink-3 hover:bg-surface-2 hover:text-ink"
              >
                Clear
              </button>
              <button
                type="button"
                onClick={() => pick(todayIso)}
                className="rounded px-1.5 py-0.5 font-medium text-accent hover:bg-surface-2"
              >
                Today
              </button>
            </div>
          </div>,
          document.body,
        )}
    </div>
  )
}
