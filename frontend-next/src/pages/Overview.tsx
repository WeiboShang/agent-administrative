import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Calendar, Inbox, ReceiptText, type LucideIcon } from 'lucide-react'
import { api, inboxApi, scheduleApi, type CalEvent, type LedgerResult, type QueueItem, type Thread } from '@/lib/api'
import { Card, Empty, PageHeader, Pill, Spinner, Stepper } from '@/components/ui'
import { fmtGBP } from '@/lib/format'

type Data = { threads: Thread[]; events: CalEvent[]; queue: QueueItem[]; ledger: LedgerResult }

function Kpi({ label, value, unit, note, tone }: {
  label: string
  value: string | number
  unit?: string
  note: string
  tone?: string
}) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4 shadow-sm">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">{label}</div>
      <div className="text-[27px] font-[640] leading-none tracking-[-0.02em] tabular-nums text-ink">
        {value}
        {unit && <span className="text-[14px] text-ink-3">{unit}</span>}
      </div>
      <div className={`mt-2 text-[11.5px] font-medium ${tone ?? 'text-ink-3'}`}>{note}</div>
    </div>
  )
}

function WfCard({ to, icon: Icon, title, count, desc }: {
  to: string
  icon: LucideIcon
  title: string
  count: string | number
  desc: string
}) {
  return (
    <Link
      to={to}
      className="rounded-xl border border-line bg-surface p-4 shadow-sm transition-colors hover:border-accent"
    >
      <div className="flex items-center gap-2.5">
        <Icon size={16} strokeWidth={1.6} className="text-ink-3" />
        <span className="text-[14px] font-[640]">{title}</span>
        <span className="ml-auto text-[24px] font-[640] leading-none tabular-nums">{count}</span>
      </div>
      <p className="mt-2 text-[12.5px] text-ink-3">{desc}</p>
    </Link>
  )
}

export default function Overview() {
  const [d, setD] = useState<Data | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([inboxApi.threads(), scheduleApi.calendar(), api.evidenceQueue(), api.ledger()])
      .then(([t, c, q, l]) => setD({ threads: t.threads, events: c.events, queue: q.items, ledger: l }))
      .catch(() => setD(null))
      .finally(() => setLoading(false))
  }, [])

  const openThreads = d?.threads.filter((t) => t.status !== 'archived' && t.status !== 'resolved').length ?? 0
  const budgets = Object.values(d?.ledger.budgets ?? {})
  const total = budgets.reduce((s, b) => s + b.total, 0)
  const remaining = budgets.reduce((s, b) => s + b.remaining, 0)
  const usedPct = total > 0 ? Math.round(((total - remaining) / total) * 100) : 0
  const flagged = d?.queue.filter((q) => (q.policy_flags?.length ?? 0) > 0).length ?? 0

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        title="Overview"
        subtitle="The agent drafts · you decide · code executes."
      />

      <Card>
        <div className="p-5">
          <Stepper
            steps={[
              { label: 'Messy input', sub: 'threads · requests · receipts' },
              { label: 'Agent drafts', sub: 'reads & proposes' },
              { label: 'Code checks', sub: 'dates · people · policy' },
              { label: 'You decide', sub: 'approve · edit · reject', state: 'active' },
              { label: 'It happens', sub: 'events · claims · notes' },
            ]}
          />
        </div>
      </Card>

      {loading ? (
        <Card>
          <Empty>
            <Spinner /> Loading workspace…
          </Empty>
        </Card>
      ) : !d ? (
        <Card>
          <Empty>Could not reach the backend.</Empty>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-4">
            <Kpi label="Open threads" value={openThreads} note={`${d.threads.length} total`} />
            <Kpi label="Meetings booked" value={d.events.length} note="on the shared calendar" />
            <Kpi
              label="Pending approvals"
              value={d.queue.length}
              note={flagged ? `${flagged} carry policy flags` : 'none flagged'}
              tone={flagged ? 'text-warn' : undefined}
            />
            <Kpi
              label="Budget used"
              value={usedPct}
              unit="%"
              note={`${fmtGBP(total - remaining)} of ${fmtGBP(total)}`}
              tone={usedPct >= 90 ? 'text-warn' : undefined}
            />
          </div>

          <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-3">
            <WfCard
              to="/inbox"
              icon={Inbox}
              title="Inbox"
              count={openThreads}
              desc="WF1 — detect actionable intents in a thread and route them"
            />
            <WfCard
              to="/calendar"
              icon={Calendar}
              title="Calendar"
              count={d.events.length}
              desc="WF2 — resolve dates & people, check conflicts against a stateful calendar"
            />
            <WfCard
              to="/expenses"
              icon={ReceiptText}
              title="Expenses"
              count={d.queue.length}
              desc="WF3 — read the receipt, check policy & arithmetic, post to the ledger"
            />
          </div>

          <Card>
            <div className="flex flex-wrap items-center gap-3 px-4 py-3.5 text-[12.5px] text-ink-3">
              <Pill tone="neutral">{d.ledger.records.length} claims</Pill>
              <Pill tone="neutral">approved {fmtGBP(d.ledger.approved_total_gbp)}</Pill>
              <span>
                Evaluation numbers live in the{' '}
                <Link to="/eval" className="font-medium text-accent hover:underline">
                  Evaluation section
                </Link>{' '}
                — per workflow, with the judge and sample size attached to every figure.
              </span>
            </div>
          </Card>
        </>
      )}
    </div>
  )
}
