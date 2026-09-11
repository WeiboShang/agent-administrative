import { useEffect, useState } from 'react'
import { evalApi, type HumanEvalHistory } from '@/lib/api'
import { Card, CardHeader, Empty, Pill } from '@/components/ui'
import { fmtAt } from './parts'

const record = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
const show = (value: unknown) => typeof value === 'number' ? String(value) : '—'

export default function RunHistory() {
  const [history, setHistory] = useState<HumanEvalHistory | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    evalApi.humanHistory().then(setHistory).catch((cause) => setError((cause as Error).message))
  }, [])

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="Part B formal run history" right={<Pill tone="neutral">append-only</Pill>} />
        <div className="px-4 py-3 text-[12.5px] leading-5 text-ink-2">Only finalised 36-case author runs appear here. Pilot cases are excluded from every headline result; each row retains its manifest hash and SHA-256 wrapper.</div>
      </Card>
      {error && <div className="rounded-lg border border-bad/30 bg-bad-soft px-4 py-3 text-[12.5px] text-bad">{error}</div>}
      {!history?.items.length ? <Card><Empty>No finalised single-reviewer run yet.</Empty></Card> : history.items.map((item) => {
        const summary = record(item.summary)
        const outcomes = record(summary.outcomes)
        const byCondition = record(outcomes.by_condition)
        const manual = record(byCondition.manual)
        const agent = record(byCondition.agent_assisted)
        const timeSaving = record(summary.time_saving)
        return (
          <Card key={item.sha256}>
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3">
              <div><b className="text-[13.5px]">{item.session_id}</b><p className="mt-0.5 text-[11px] text-ink-3">{fmtAt(item.at)} · one reviewer · descriptive evidence</p></div>
              <Pill tone="ok">{item.result_status}</Pill>
            </div>
            <div className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-lg bg-surface-2 p-3"><span className="text-[11px] text-ink-3">Manual task outcome</span><div className="mt-1 text-[19px] font-semibold">{show(manual.task_outcome_rate)}</div></div>
              <div className="rounded-lg bg-surface-2 p-3"><span className="text-[11px] text-ink-3">Agent task outcome</span><div className="mt-1 text-[19px] font-semibold">{show(agent.task_outcome_rate)}</div></div>
              <div className="rounded-lg bg-surface-2 p-3"><span className="text-[11px] text-ink-3">Agent unsafe outcome</span><div className="mt-1 text-[19px] font-semibold">{show(agent.unsafe_outcome_rate)}</div></div>
              <div className="rounded-lg bg-surface-2 p-3"><span className="text-[11px] text-ink-3">Relative time saving</span><div className="mt-1 text-[19px] font-semibold">{show(timeSaving.relative_rate)}</div></div>
            </div>
            <details className="border-t border-line"><summary className="cursor-pointer px-4 py-2.5 text-[11.5px] font-medium text-ink-2">Provenance and complete summary</summary><pre className="max-h-96 overflow-auto border-t border-line p-4 text-[10px] leading-4 text-ink-2">{JSON.stringify(item, null, 2)}</pre></details>
          </Card>
        )
      })}
    </div>
  )
}
