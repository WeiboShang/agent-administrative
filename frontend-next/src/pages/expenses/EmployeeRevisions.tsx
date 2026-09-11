import { useCallback, useEffect, useState } from 'react'
import { api, type ExpenseFields, type QueueItem } from '@/lib/api'
import { useAppData } from '@/context/AppData'
import { Button, Card, CardHeader, Empty, Pill, Spinner } from '@/components/ui'
import DateField from '@/components/DateField'

const EDITABLE = ['vendor', 'date', 'amount', 'currency', 'business_purpose'] as const

export default function EmployeeRevisions({ tick, reload }: { tick: number; reload: () => void }) {
  const { actor } = useAppData()
  const [items, setItems] = useState<QueueItem[]>([])
  const [forms, setForms] = useState<Record<string, Record<string, string>>>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)

  const load = useCallback(() => {
    if (!actor) return
    api.evidenceQueue().then(({ items: rows }) => {
      const mine = rows.filter((row) => row.type === 'expense_claim' && row.status === 'needs_information' && row.submitted_by === actor.id)
      setItems(mine)
      setForms(Object.fromEntries(mine.map((row) => [row.id, Object.fromEntries(EDITABLE.map((key) => [key, String(row.submitted_snapshot?.[key] ?? '')]))])))
    }).catch(() => setItems([]))
  }, [actor])

  useEffect(load, [load, tick])
  if (!actor || !items.length) return null
  const actorId = actor.id

  async function resubmit(item: QueueItem) {
    const current = forms[item.id] ?? {}
    const fields: ExpenseFields = { ...item.submitted_snapshot }
    for (const key of EDITABLE) {
      const value = (current[key] ?? '').trim()
      if (key === 'amount') fields.amount = value ? Number(value) : null
      else (fields as Record<string, unknown>)[key] = value || null
    }
    const changed = EDITABLE.filter((key) => String(item.submitted_snapshot?.[key] ?? '') !== (current[key] ?? ''))
    setBusy(item.id)
    setNote(null)
    try {
      const result = await api.resubmitExpense(item.id, {
        fields,
        submitted_by: actorId,
        expected_version: item.version ?? 1,
        changed_fields: [...changed],
        idempotency_key: `${item.id}:${item.version ?? 1}:resubmit:${actorId}`,
      })
      if (!['resubmitted', 'idempotent_replay'].includes(result.status)) setNote(`Resubmission not completed: ${result.status.replaceAll('_', ' ')}`)
      else reload()
    } catch (e) {
      setNote((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <Card>
      <CardHeader title="Information requested — revise and resubmit" right={<Pill tone="warn">{items.length} returned</Pill>} />
      {note && <div className="border-b border-line bg-warn-soft px-4 py-2.5 text-[13px] text-warn">{note}</div>}
      {!items.length ? <Empty>No returned claims.</Empty> : items.map((item) => (
        <div key={item.id} className="border-t border-line p-4">
          <div className="rounded-lg border border-warn bg-warn-soft p-3 text-[13px]">
            <b>Approver request:</b> {item.information_request?.text}
            <ul className="mt-1 list-disc pl-5">{item.information_request?.issues.map((issue) => <li key={issue}>{issue}</li>)}</ul>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {EDITABLE.map((key) => <label key={key} className="text-[11px] font-semibold uppercase text-ink-3">{key.replace('_', ' ')}
              {key === 'date' ? <DateField value={forms[item.id]?.[key] ?? ''} onChange={(value) => setForms((old) => ({ ...old, [item.id]: { ...old[item.id], [key]: value } }))} expectedTiming="past" className="mt-1 h-9 w-full rounded-lg border border-line-strong bg-surface px-2.5 text-[13px]" /> : <input value={forms[item.id]?.[key] ?? ''} onChange={(e) => setForms((old) => ({ ...old, [item.id]: { ...old[item.id], [key]: e.target.value } }))} className="mt-1 h-9 w-full rounded-lg border border-line-strong bg-surface px-2.5 text-[13px] font-normal normal-case" />}
            </label>)}
          </div>
          <div className="mt-3 flex justify-end"><Button variant="primary" disabled={busy === item.id} onClick={() => resubmit(item)}>{busy === item.id ? <Spinner /> : 'Resubmit to approver'}</Button></div>
        </div>
      ))}
    </Card>
  )
}
