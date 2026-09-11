import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { evalApi, type EvalRecord } from '@/lib/api'
import { Button, Card, CardHeader, Empty, Pill, Spinner } from '@/components/ui'
import { cn } from '@/lib/utils'

/* ── last-results (persisted across restarts by results_store) ── */
type LastCtx = { last: Record<string, EvalRecord>; refresh: () => void }
// null default so misuse outside the provider throws instead of silently showing
// "not run yet" — same contract as AppData.
const Ctx = createContext<LastCtx | null>(null)

export function LastResultsProvider({ children }: { children: ReactNode }) {
  const [last, setLast] = useState<Record<string, EvalRecord>>({})
  const refresh = useCallback(() => {
    evalApi
      .last()
      .then(setLast)
      .catch(() => setLast({}))
  }, [])
  useEffect(refresh, [refresh])
  return <Ctx.Provider value={{ last, refresh }}>{children}</Ctx.Provider>
}
export function useLastResults(): LastCtx {
  const v = useContext(Ctx)
  if (!v) throw new Error('useLastResults must be used within LastResultsProvider')
  return v
}

export const pct = (v: unknown) =>
  typeof v === 'number' ? `${(v * 100).toFixed(0)}%` : '—'
export const num = (v: unknown) => (typeof v === 'number' ? String(v) : '—')

export function fmtAt(at?: string) {
  if (!at) return '—'
  const d = new Date(at)
  return isNaN(d.getTime()) ? at : d.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })
}

/**
 * One eval card, same skeleton everywhere: what it measures · how it's run · the run
 * button · provenance (model, judge, n, when) · the result.
 *
 * Provenance is not decoration — a number without its generator/judge and n cannot be read
 * (docs/workflow_design.md: always report which judge produced a number).
 */
export function EvalRunner({
  name,
  title,
  measures,
  method,
  cost,
  run,
  render,
  children,
}: {
  name: string
  title: string
  measures: string
  method?: string
  cost: string
  run: () => Promise<Record<string, unknown>>
  render: (result: Record<string, unknown>) => ReactNode
  children?: ReactNode
}) {
  const { last, refresh } = useLastResults()
  const [busy, setBusy] = useState(false)
  const [fresh, setFresh] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState<string | null>(null)

  const record = last[name]
  const result = fresh ?? (record?.result as Record<string, unknown> | undefined)

  async function go() {
    setBusy(true)
    setError(null)
    try {
      setFresh(await run())
      refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader
        title={title}
        right={
          <Button size="sm" variant="primary" onClick={go} disabled={busy}>
            {busy ? (
              <>
                <Spinner /> Running…
              </>
            ) : (
              `Run (${cost})`
            )}
          </Button>
        }
      />
      <div className="border-b border-line px-4 py-3">
        <p className="text-[13px] text-ink-2">
          <span className="font-medium text-ink">Measures:</span> {measures}
        </p>
        {method && <p className="mt-1 text-[12.5px] text-ink-3">{method}</p>}
        {children}
      </div>

      {(record || fresh) && (
        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface-2 px-4 py-2.5">
          {fresh ? (
            <Pill tone="ok">just run</Pill>
          ) : (
            <span className="text-[11.5px] text-ink-3">last run {fmtAt(record?.at)}</span>
          )}
          {record?.model && (
            <span className="rounded-md bg-surface-3 px-2 py-0.5 font-mono text-[11px] text-ink-2">
              {record.model}
            </span>
          )}
          {record?.params &&
            Object.entries(record.params).map(([k, v]) => (
              <span key={k} className="text-[11px] text-ink-3">
                {k}={String(v)}
              </span>
            ))}
        </div>
      )}

      {error && <div className="px-4 py-3 text-[13px] text-bad">Error: {error}</div>}
      {result ? <div className="overflow-x-auto">{render(result)}</div> : <Empty>Not run yet.</Empty>}
    </Card>
  )
}

/* ── result renderers ── */

export function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <table className="w-full border-collapse tabular-nums">
      <thead>
        <tr>
          {head.map((h) => (
            <th
              key={h}
              className="border-b border-line px-4 py-2.5 text-left text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3"
            >
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className="hover:bg-surface-2">
            {r.map((cell, j) => (
              <td
                key={j}
                className={cn(
                  'border-b border-line px-4 py-2.5 text-[13px]',
                  j === 0 ? 'font-medium text-ink' : 'text-ink-2',
                )}
              >
                {cell}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** A rate cell that goes red when it drops below 1.0 — the eye should land on the gaps. */
export function Rate({ v }: { v: unknown }) {
  if (typeof v !== 'number') return <span className="text-ink-3">—</span>
  return <span className={v < 1 ? 'font-semibold text-bad' : ''}>{(v * 100).toFixed(0)}%</span>
}

export function Tiles({ items }: { items: { label: string; value: ReactNode; note?: string }[] }) {
  return (
    <div className="grid grid-cols-2 gap-3.5 p-4 lg:grid-cols-3">
      {items.map((t) => (
        <div key={t.label} className="rounded-lg border border-line bg-surface-2 p-3.5">
          <div className="text-[24px] font-[640] leading-none tracking-[-0.02em] tabular-nums text-ink">
            {t.value}
          </div>
          <div className="mt-1.5 text-[11.5px] text-ink-3">{t.label}</div>
          {t.note && <div className="mt-1 text-[11px] text-ink-3">{t.note}</div>}
        </div>
      ))}
    </div>
  )
}

/** Per-tier metric table shared by triage / scheduling / receipts. */
export function TierTable({
  data,
  cols,
  order,
}: {
  data: Record<string, Record<string, unknown>>
  cols: [string, string][]
  order?: string[]
}) {
  const tiers = order
    ? order.filter((t) => data[t]).concat(Object.keys(data).filter((t) => !order.includes(t)))
    : Object.keys(data)
  return (
    <Table
      head={['Tier', 'n', ...cols.map((c) => c[1])]}
      rows={tiers.map((t) => [
        t,
        num(data[t].n),
        ...cols.map((c) => <Rate key={c[0]} v={data[t][c[0]]} />),
      ])}
    />
  )
}

export function JudgeNote({ generator, judge }: { generator?: unknown; judge?: unknown }) {
  if (!judge) return null
  return (
    <div className="flex flex-wrap items-center gap-2 px-4 pb-4 text-[12px] text-ink-3">
      <Pill tone="neutral">generator: {String(generator ?? '—')}</Pill>
      <Pill tone="neutral">judge: {String(judge)}</Pill>
      <span>cross-family — a same-family judge inflates the score by self-preference.</span>
    </div>
  )
}
