import { Fragment, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { CalEvent } from '@/lib/api'
import { useThemeColors } from '@/lib/useThemeColors'
import { Card, CardHeader, Empty } from '@/components/ui'
import { HBar, StatTile, type Bucket } from '@/components/charts'
import { cn } from '@/lib/utils'

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

// Calendar dates are plain YYYY-MM-DD (no timezone). Parsing them with `new Date(iso)`
// treats them as UTC midnight, and `toISOString()` converts back through UTC — either step
// shifts the day by one for any non-UTC viewer (BST puts every meeting in the wrong cell).
// So dates stay LOCAL end-to-end, and day arithmetic uses setDate (also DST-safe).
const parseLocal = (iso: string): Date => {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, (m ?? 1) - 1, d ?? 1)
}
const isoLocal = (d: Date): string =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

function tally(values: string[]): Bucket[] {
  const m = new Map<string, number>()
  for (const v of values) m.set(v, (m.get(v) ?? 0) + 1)
  return [...m.entries()].map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value)
}

/** Monday-of-week for an ISO date. */
function weekStart(d: Date): Date {
  const x = new Date(d)
  const dow = (x.getDay() + 6) % 7 // Mon=0
  x.setDate(x.getDate() - dow)
  x.setHours(0, 0, 0, 0)
  return x
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
// How wide the viewport is. This is the knob for "the card looks empty on the right": grid
// width ≈ RAIL + weeks × (MAX_CELL + GAP), so at 30px cells 6 months ≈ 950px and 9 months
// ≈ 1390px (a full-width card). Raise it rather than growing the cells — the day grid stops
// reading as a calendar once the squares get chunky.
const MONTHS_VISIBLE = 6

const monthStart = (d: Date, offset = 0) => new Date(d.getFullYear(), d.getMonth() + offset, 1)
const monthEnd = (d: Date) => new Date(d.getFullYear(), d.getMonth() + 1, 0)

/** Default viewport: one month back, the rest ahead.
 *
 * A contribution graph looks backwards because commits are past. A booking calendar's
 * interesting data is the opposite — meetings are scheduled INTO the future — so a window
 * that ends at today buries the thing you just booked against the right edge. */
const defaultAnchor = () => monthStart(new Date(), -1)
const GAP = 4          // px — surface gap BETWEEN marks (never a border; see dataviz spec)
const RAIL = 32        // px — weekday-label column
const MAX_CELL = 30    // px — cells fill the card width, but stop growing here
const MONTH_ROW = 18   // px — height reserved for the month-label row

// Explicit en-GB so the tooltip date reads the same regardless of the viewer's browser locale.
const TIP_FMT = new Intl.DateTimeFormat('en-GB',
  { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' })

/**
 * Booking-density calendar heatmap (the GitHub "contribution graph" layout): one column per
 * week, one row per weekday, ~5 months wide. Magnitude over a date grid ⇒ a **sequential
 * single hue** (light→dark), never a categorical ramp. Recharts has no calendar heatmap, so
 * this is a plain CSS grid — lighter than pulling another library.
 *
 * Month labels along the top are what make a cell locatable: without them the reader can only
 * discover *when* a meeting is by hovering, which makes the tooltip the sole way to read the
 * chart. Weekday labels (Mon/Wed/Fri) and a ring on today complete the orientation.
 */
function Heatmap({ counts, anchor }: { counts: Map<string, number>; anchor: Date }) {
  // The window is a VIEWPORT the reader pans, not a crop derived from the data: always
  // MONTHS_VISIBLE whole months starting at `anchor`. Deriving it from the data is what
  // produced half-months and windows that opened on empty stretches.
  const first = weekStart(anchor)
  const lastWeek = weekStart(monthEnd(monthStart(anchor, MONTHS_VISIBLE - 1)))
  // whole days between the two Mondays, so the span is exact regardless of DST
  const weeks = Math.round((lastWeek.getTime() - first.getTime()) / 86_400_000 / 7) + 1

  const max = Math.max(1, ...counts.values())
  const todayIso = isoLocal(new Date())

  // 5 sequential steps of one hue: 0 → surface-3, then 25/45/70/100% of the accent
  const step = (n: number) => {
    if (n === 0) return 'var(--surface-3)'
    const r = n / max
    const pct = r <= 0.25 ? 28 : r <= 0.5 ? 48 : r <= 0.75 ? 72 : 100
    return `color-mix(in srgb, var(--accent) ${pct}%, transparent)`
  }

  const cells: { iso: string; n: number }[][] = []
  const cursor = new Date(first)
  let inWindow = 0
  for (let w = 0; w < weeks; w++) {
    const col: { iso: string; n: number }[] = []
    for (let d = 0; d < 7; d++) {
      const iso = isoLocal(cursor)
      const n = counts.get(iso) ?? 0
      inWindow += n
      col.push({ iso, n })
      cursor.setDate(cursor.getDate() + 1)
    }
    cells.push(col)
  }

  // Label each month at its first column. A month with only ONE visible column (the partial
  // month the window happens to open or close on) has no room for a label without colliding
  // with its neighbour's — drop that one, never the full month after it. Keeping the partial
  // instead is what silently loses a month from the axis.
  const monthAt: (string | null)[] = new Array(weeks).fill(null)
  const monthCols = new Map<string, number[]>()
  for (let w = 0; w < weeks; w++) {
    const d = parseLocal(cells[w][0].iso)
    const key = `${d.getFullYear()}-${d.getMonth()}`
    monthCols.set(key, [...(monthCols.get(key) ?? []), w])
  }
  for (const [key, cols] of monthCols) {
    if (cols.length < 2) continue
    monthAt[cols[0]] = MONTHS[Number(key.split('-')[1])]
  }

  return (
    <div className="p-4">
      {/* One grid for rail + month row + days, so the three always line up: column 1 is the
          weekday rail, the rest are equal fractions of the width (cells grow with the card
          instead of leaving it half empty), capped so they never become absurd. */}
      <div
        className="grid"
        style={{
          gridTemplateColumns: `${RAIL}px repeat(${weeks}, minmax(0, 1fr))`,
          gap: GAP,
          maxWidth: RAIL + weeks * (MAX_CELL + GAP),
        }}
      >
        <div />
        {monthAt.map((m, w) => (
          <div key={`m${w}`} className="relative" style={{ height: MONTH_ROW }}>
            {m && (
              <span className="absolute left-0 top-0 whitespace-nowrap text-[11px] text-ink-3">
                {m}
              </span>
            )}
          </div>
        ))}

        {WEEKDAYS.map((wd, r) => (
          <Fragment key={wd}>
            <div className="flex items-center pr-1 text-[11px] text-ink-3">
              {r % 2 === 0 ? wd : ''}
            </div>
            {cells.map((col, w) => {
              const c = col[r]
              return (
                <div
                  key={`${w}-${r}`}
                  title={`${TIP_FMT.format(parseLocal(c.iso))} — ${c.n} meeting${c.n === 1 ? '' : 's'}`}
                  className={cn(
                    'aspect-square rounded-[4px]',
                    c.iso === todayIso && 'ring-2 ring-accent ring-offset-1 ring-offset-surface',
                  )}
                  style={{ background: step(c.n) }}
                />
              )
            })}
          </Fragment>
        ))}
      </div>
      {/* Say it, rather than leaving the reader to wonder whether a silent grid of grey means
          "nothing booked" or "failed to load". */}
      {inWindow === 0 && (
        <p className="mt-3 text-[12px] text-ink-3">No meetings in this range.</p>
      )}

      {/* The scale legend only earns its space once a day can hold MORE than one meeting.
          At max=1 the ramp is just "booked or not", which the grid already shows — and the
          running total is already the "Meetings booked" tile above, so repeating either here
          would be duplication. */}
      {inWindow > 0 && max >= 2 && (
        <div className="mt-3 flex items-center gap-1.5 text-[11px] text-ink-3">
          Less
          {[0, 0.25, 0.5, 0.75, 1].map((r) => (
            <span
              key={r}
              className="size-3 rounded-[3px]"
              style={{ background: step(Math.ceil(r * max)) }}
            />
          ))}
          More
        </div>
      )}
    </div>
  )
}

export default function CalendarAnalytics({ events }: { events: CalEvent[] }) {
  const c = useThemeColors()
  // first day of the leftmost visible month — the reader pans this, nothing derives it
  const [anchor, setAnchor] = useState(defaultAnchor)
  const windowEnd = monthEnd(monthStart(anchor, MONTHS_VISIBLE - 1))

  const counts = new Map<string, number>()
  for (const e of events) if (e.date) counts.set(e.date, (counts.get(e.date) ?? 0) + 1)

  const byRoom = tally(events.map((e) => e.location || 'unassigned'))
  const byPerson = tally(events.flatMap((e) => e.participants))

  // How the human answered the code's warnings (WF2 scheduling flags are all soft by design,
  // so booking with one still attached IS the override).
  const SLOT_FIELDS = ['date', 'time', 'duration_minutes', 'location']
  const byResponse = tally(
    events.map((e) => {
      const flagged = (e.overridden_flags?.length ?? 0) > 0
      const movedSlot = (e.changed_fields ?? []).some((f) => SLOT_FIELDS.includes(f))
      if (flagged) return 'booked over a flag'
      if (movedSlot) return 'edited the slot, then booked clean'
      return 'no flags raised'
    }),
  )
  const days = counts.size
  const busiest = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]

  const totalMinutes = events.reduce((s, e) => {
    if (!e.start || !e.end) return s
    const [h1, m1] = e.start.split(':').map(Number)
    const [h2, m2] = e.end.split(':').map(Number)
    return s + Math.max(0, h2 * 60 + m2 - (h1 * 60 + m1))
  }, 0)

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-4">
        <StatTile label="Meetings booked" value={events.length} dot="bg-accent" />
        <StatTile label="Days with meetings" value={days} dot="bg-ink-3" />
        <StatTile
          label="Busiest day"
          value={busiest ? busiest[1] : 0}
          dot="bg-ink-3"
          note={busiest ? busiest[0] : 'nothing booked'}
        />
        <StatTile
          label="Time committed"
          value={`${Math.round((totalMinutes / 60) * 10) / 10}h`}
          dot="bg-ink-3"
          note="across all booked meetings"
        />
      </div>

      <Card>
        <CardHeader
          title="Booking density"
          right={
            <div className="flex items-center gap-1.5">
              <span className="mr-1 text-[12px] tabular-nums text-ink-3">
                {MONTHS[anchor.getMonth()]}
                {' – '}
                {MONTHS[windowEnd.getMonth()]} {windowEnd.getFullYear()}
              </span>
              <button
                type="button"
                aria-label="Earlier months"
                onClick={() => setAnchor((a) => monthStart(a, -1))}
                className="grid size-7 place-items-center rounded-md border border-line-strong text-ink-2 hover:bg-surface-2"
              >
                <ChevronLeft size={15} />
              </button>
              <button
                type="button"
                onClick={() => setAnchor(defaultAnchor)}
                className="rounded-md border border-line-strong px-2.5 py-1 text-[12px] text-ink-2 hover:bg-surface-2"
              >
                Today
              </button>
              <button
                type="button"
                aria-label="Later months"
                onClick={() => setAnchor((a) => monthStart(a, 1))}
                className="grid size-7 place-items-center rounded-md border border-line-strong text-ink-2 hover:bg-surface-2"
              >
                <ChevronRight size={15} />
              </button>
            </div>
          }
        />
        <Heatmap counts={counts} anchor={anchor} />
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Room utilisation" />
          <HBar data={byRoom} color={c['--accent']} format={(v) => String(v)} unitLabel="meeting(s)" />
        </Card>
        <Card>
          <CardHeader title="Meeting load by participant" />
          <HBar data={byPerson} color={c['--accent']} format={(v) => String(v)} unitLabel="meeting(s)" />
        </Card>
      </div>

      <Card>
        <CardHeader title="What the human did with a flagged meeting" />
        <div className="border-b border-line px-4 py-3 text-[12.5px] text-ink-3">
          Every booked meeting carries the checks that were live when it was booked. Booking
          anyway is an <b className="text-ink-2">override</b>; changing the date/time/room first
          is <b className="text-ink-2">editing around</b> the warning. This is the WF2 half of
          the RQ3 control story.
        </div>
        {byResponse.length ? (
          <HBar data={byResponse} color={c['--accent']} format={(v) => String(v)} unitLabel="meeting(s)" />
        ) : (
          <Empty>No booked meetings yet.</Empty>
        )}
      </Card>
    </div>
  )
}
