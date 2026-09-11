import { useEffect, useState } from 'react'
import { api, evalApi, type LedgerResult } from '@/lib/api'
import { useThemeColors } from '@/lib/useThemeColors'
import { Card, CardHeader, Empty, Spinner } from '@/components/ui'
import { HBar, StatTile, type Bucket } from '@/components/charts'
import { fmtGBP } from '@/lib/format'

type Audit = {
  charts: Record<string, Bucket[]>
  spend_currency?: string
  spend_excluded_unconvertible?: number
}

export default function Analytics({ tick }: { tick: number }) {
  const c = useThemeColors()
  const [audit, setAudit] = useState<Audit | null>(null)
  const [ledger, setLedger] = useState<LedgerResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedDepartment, setSelectedDepartment] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      evalApi.audit() as Promise<Audit>,
      api.ledger(),
    ])
      .then(([a, l]) => {
        setAudit(a)
        setLedger(l)
      })
      .catch(() => {
        setAudit(null)
        setLedger(null)
      })
      .finally(() => setLoading(false))
  }, [tick])

  if (loading) {
    return (
      <Card>
        <Empty>
          <Spinner /> Loading analytics…
        </Empty>
      </Card>
    )
  }
  if (!audit || !ledger) {
    return (
      <Card>
        <Empty>Could not load analytics.</Empty>
      </Card>
    )
  }

  // Claims by status + flags by rule are derived from the ledger, so the reasoning-layer
  // flags (arithmetic_mismatch / similar_receipt) appear without a backend change.
  const byStatus = { approved: 0, submitted: 0, rejected: 0 } as Record<string, number>
  const flagCounts = new Map<string, number>()
  for (const r of ledger.records) {
    byStatus[r.status] = (byStatus[r.status] ?? 0) + 1
    const flags = (r as unknown as { policy_flags?: { rule: string }[] }).policy_flags ?? []
    for (const f of flags) flagCounts.set(f.rule, (flagCounts.get(f.rule) ?? 0) + 1)
  }
  const flagsByRule: Bucket[] = [...flagCounts.entries()]
    .map(([label, value]) => ({ label, value }))
    .sort((a, b) => b.value - a.value)

  const excluded = audit.spend_excluded_unconvertible ?? 0
  const handlingHours = ledger.records
    .filter((r) => r.submitted_at && r.decided_at)
    .map((r) => (new Date(r.decided_at!).getTime() - new Date(r.submitted_at!).getTime()) / 3_600_000)
    .sort((a, b) => a - b)
  const medianHours = handlingHours.length
    ? handlingHours.length % 2
      ? handlingHours[Math.floor(handlingHours.length / 2)]
      : (handlingHours[handlingHours.length / 2 - 1] + handlingHours[handlingHours.length / 2]) / 2
    : null
  const currencies = new Map<string, { count: number; gbp: number }>()
  for (const record of ledger.records) {
    const currency = (record.currency || 'GBP').toUpperCase()
    const row = currencies.get(currency) ?? { count: 0, gbp: 0 }
    row.count += 1
    row.gbp += Number(record.amount_gbp ?? (currency === 'GBP' ? record.amount ?? 0 : 0))
    currencies.set(currency, row)
  }
  const submittedTotal = ledger.records.filter((r) => r.submitted_at).length
  const returnedTotal = ledger.records.filter((r) => r.status === 'needs_information' || r.resubmitted_at).length
  const decidedTotal = (byStatus.approved ?? 0) + (byStatus.rejected ?? 0)
  const departmentNames = Object.keys(ledger.budgets).sort()
  const activeDepartment = selectedDepartment && ledger.budgets[selectedDepartment] ? selectedDepartment : departmentNames[0] ?? null
  const departmentClaims = activeDepartment
    ? ledger.records.filter((record) => record.status === 'approved' && record.department === activeDepartment)
    : []

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-5">
        <StatTile label="Submitted" value={submittedTotal} dot="bg-ink-3" />
        <StatTile label="Returned / resubmitted" value={returnedTotal} dot="bg-warn" />
        <StatTile label="Decided" value={decidedTotal} dot="bg-ok" />
        <StatTile label="Median handling" value={medianHours === null ? '—' : `${medianHours.toFixed(1)} h`} dot="bg-accent" />
        <StatTile label="Approved total" value={fmtGBP(ledger.approved_total_gbp)} dot="bg-accent" note={excluded ? `${excluded} excluded · unconvertible currency` : 'frozen FX converted to GBP'} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Spend by category" />
          <HBar
            data={audit.charts.spend_by_category ?? []}
            color={c['--accent']}
            format={(v) => `£${Math.round(v).toLocaleString('en-GB')}`}
            unitLabel="approved spend"
          />
        </Card>
        <Card>
          <CardHeader title="Spend by department (charged)" />
          <HBar
            data={audit.charts.spend_by_department ?? []}
            color={c['--accent']}
            format={(v) => `£${Math.round(v).toLocaleString('en-GB')}`}
            unitLabel="approved spend"
          />
        </Card>
      </div>

      <Card>
        <CardHeader title="Currency exposure — claim count and GBP equivalent" />
        <div className="divide-y divide-line">
          {[...currencies.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([currency, row]) => (
            <div key={currency} className="grid grid-cols-3 px-4 py-2.5 text-[13px]"><b>{currency}</b><span>{row.count} claim(s)</span><span className="text-right tabular-nums">{fmtGBP(row.gbp)}</span></div>
          ))}
        </div>
      </Card>

      <Card>
        <CardHeader title="Policy flags raised, by rule" />
        <HBar
          data={flagsByRule}
          color={c['--accent']}
          format={(v) => String(v)}
          unitLabel={flagsByRule.length ? 'claim(s)' : ''}
        />
      </Card>

      <Card>
        <CardHeader title="Department budget consumption" />
        <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
          {departmentNames.map((department) => {
            const budget = ledger.budgets[department]
            const used = budget.total - budget.remaining
            const percent = budget.total > 0 ? Math.round((used / budget.total) * 100) : 0
            return <button key={department} type="button" onClick={() => setSelectedDepartment(department)} className={`rounded-lg border p-3 text-left transition ${activeDepartment === department ? 'border-accent bg-accent-soft' : 'border-line bg-surface-2 hover:border-line-strong'}`}><div className="text-[12px] font-semibold text-ink">{department}</div><div className="mt-1 text-[20px] font-semibold tabular-nums text-ink">{percent}%</div><div className="mt-1 text-[11px] text-ink-3">{fmtGBP(used)} of {fmtGBP(budget.total)}</div><div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-3"><div className="h-full rounded-full bg-accent" style={{ width: `${Math.min(percent, 100)}%` }} /></div></button>
          })}
        </div>
        {activeDepartment && <div className="border-t border-line"><div className="px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">Approved claims charged to {activeDepartment}</div>{departmentClaims.length ? <div className="divide-y divide-line">{departmentClaims.map((record) => <div key={record.id} className="grid grid-cols-[1fr_auto] gap-3 px-4 py-2.5 text-[12px]"><div><span className="font-mono text-ink">{record.id}</span><span className="ml-2 text-ink-3">{record.vendor ?? 'Unknown vendor'} · {record.category ?? 'uncategorised'}</span></div><span className="tabular-nums text-ink">{fmtGBP(Number(record.amount_gbp ?? record.amount ?? 0))}</span></div>)}</div> : <Empty>No approved claims charged to this department.</Empty>}</div>}
      </Card>

      <div className="rounded-xl border border-line bg-surface px-4 py-3 text-[12px] text-ink-3 shadow-sm">
        Spend shown in {audit.spend_currency ?? 'GBP'} using frozen evaluation FX rates.
      </div>
    </div>
  )
}
