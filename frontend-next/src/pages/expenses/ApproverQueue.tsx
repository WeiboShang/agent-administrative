import { useCallback, useEffect, useState } from 'react'
import { api, type QueueItem } from '@/lib/api'
import { useAppData } from '@/context/AppData'
import { Button, Card, CardHeader, Empty, FlagChip, Pill, Spinner } from '@/components/ui'
import { fmtGBP, fmtMoney } from '@/lib/format'

const CRITICAL = ['vendor', 'date', 'amount', 'currency'] as const

export default function ApproverQueue({ tick, reload }: { tick: number; reload: () => void }) {
  const { actor } = useAppData()
  const [items, setItems] = useState<QueueItem[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [issues, setIssues] = useState('')
  const [requestText, setRequestText] = useState('')
  const [acks, setAcks] = useState<string[]>([])
  const [note, setNote] = useState<string | null>(null)

  const load = useCallback(() => {
    if (!actor?.is_approver) return
    setLoading(true)
    api.evidenceQueue()
      .then((d) => setItems(d.items.filter((item) => item.type === 'expense_claim' && item.status !== 'needs_information')))
      .catch(() => setItems([]))
      .finally(() => setLoading(false))
  }, [actor])

  useEffect(load, [load, tick])
  if (!actor?.is_approver) return null

  function begin(id: string) {
    setOpen((current) => current === id ? null : id)
    setReason('')
    setIssues('')
    setRequestText('')
    setAcks([])
    setNote(null)
  }

  async function decide(item: QueueItem, decision: 'approve' | 'reject') {
    setBusy(item.id)
    setNote(null)
    try {
      const r = await api.decideEvidence(item.id, {
        decision,
        reviewed_by: actor!.id,
        expected_version: item.version ?? 1,
        reason: reason.trim() || undefined,
        acknowledged_flags: acks,
        idempotency_key: `${item.id}:${item.version ?? 1}:${decision}:${actor!.id}`,
      })
      if (!['approved', 'rejected', 'idempotent_replay'].includes(r.status)) {
        setNote(`Decision not completed: ${r.status.replaceAll('_', ' ')}`)
        return
      }
      setOpen(null)
      reload()
    } catch (e) {
      setNote((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  async function requestInformation(item: QueueItem) {
    const issueList = issues.split('\n').map((v) => v.trim()).filter(Boolean)
    if (!issueList.length || !requestText.trim()) {
      setNote('List at least one concrete issue and write the request to the employee.')
      return
    }
    setBusy(item.id)
    setNote(null)
    try {
      const r = await api.requestExpenseInformation(item.id, {
        reviewed_by: actor!.id,
        expected_version: item.version ?? 1,
        issues: issueList,
        request_text: requestText.trim(),
        idempotency_key: `${item.id}:${item.version ?? 1}:request-information:${actor!.id}`,
      })
      if (!['needs_information', 'idempotent_replay'].includes(r.status)) setNote(`Request not completed: ${r.status.replaceAll('_', ' ')}`)
      else {
        setOpen(null)
        reload()
      }
    } catch (e) {
      setNote((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <Card>
      <CardHeader title="Evidence-based approval workspace" right={<Pill tone={items.length ? 'warn' : 'neutral'}>{items.length} pending</Pill>} />
      {note && <div className="border-b border-line bg-warn-soft px-4 py-2.5 text-[13px] text-warn">{note}</div>}
      {loading && items.length === 0 ? <Empty><Spinner /> Loading…</Empty> : items.length === 0 ? <Empty>Nothing awaiting approval.</Empty> : items.map((it) => {
        const own = it.submitted_by === actor.id
        const nonGbp = (it.currency || 'GBP').toUpperCase() !== 'GBP'
        const softFlags = (it.policy_flags ?? []).filter((flag) => flag.severity === 'soft')
        const expanded = open === it.id
        return (
          <div key={it.id} className="border-t border-line px-4 py-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-[13.5px]"><b>{it.employee_name || it.submitted_by}</b> · <b className="tabular-nums">{fmtMoney(it.amount, it.currency)}</b>{nonGbp && <span className="text-ink-3"> ({fmtGBP(it.amount_gbp)})</span>} · {it.vendor} · {it.category}</div>
                <div className="mt-1 text-[12px] text-ink-3">{it.business_purpose} · version {it.version ?? 1} · {it.status}</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {(it.policy_flags ?? []).map((f, i) => <FlagChip key={`${f.rule}-${i}`} severity={f.severity}>{f.rule}</FlagChip>)}
                  {!it.policy_flags?.length && <Pill tone="ok">no flags</Pill>}
                  {Object.entries(it.verification_states ?? {}).map(([field, state]) => (
                    <Pill key={field} tone={state.state === 'verified' ? 'ok' : state.state === 'unresolved' ? 'bad' : 'warn'}>{field}: {state.state.replace('_', ' ')}</Pill>
                  ))}
                </div>
                {own && <div className="mt-2 text-[11.5px] text-bad">Segregation of duties blocks self-approval.</div>}
              </div>
              <Button size="sm" variant="secondary" onClick={() => begin(it.id)}>{expanded ? 'Close evidence' : 'Review evidence'}</Button>
            </div>

            {expanded && (
              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                {it.receipt_ref ? (
                  <a href={api.receiptUrl(it.id)} target="_blank" rel="noreferrer" className="block max-h-[520px] overflow-auto rounded-lg border border-line bg-surface-2">
                    <img src={api.receiptUrl(it.id)} alt={`Receipt evidence for ${it.id}`} className="w-full" />
                  </a>
                ) : (
                  <div className="grid min-h-48 place-items-center rounded-lg border border-warn bg-warn-soft p-6 text-center text-[13px] text-warn">
                    <div><b>Receipt image unavailable</b><br />This legacy claim has no recoverable source image.</div>
                  </div>
                )}
                <div className="flex flex-col gap-3">
                  {it.evidence_origin === 'legacy_synthetic_archive_backfill' && (
                    <div className="rounded-lg border border-warn bg-warn-soft px-3 py-2 text-[12px] text-warn">
                      Original image recovered from the verified local receipt archive; the legacy model-read snapshot was not stored.
                    </div>
                  )}
                  <div className="overflow-hidden rounded-lg border border-line">
                    <div className="grid grid-cols-3 bg-surface-2 px-3 py-2 text-[11px] font-semibold uppercase text-ink-3"><span>Field</span><span>Model read</span><span>Employee submitted</span></div>
                    {CRITICAL.map((field) => {
                      const state = it.verification_states?.[field]
                      const reasons = state?.reasons.map((reason) => reason.replaceAll('_', ' ')).join(', ')
                      const fallback = it.receipt_ref ? 'matches evidence' : 'evidence unavailable'
                      return <div key={field} className="grid grid-cols-3 border-t border-line px-3 py-2 text-[12px]"><b>{field}</b><span>{String(it.extraction_snapshot?.[field] ?? '—')}</span><span>{String(it.submitted_snapshot?.[field] ?? '—')}<small className="block text-ink-3">{reasons || fallback}</small></span></div>
                    })}
                  </div>

                  {softFlags.map((flag) => <label key={flag.rule} className="flex gap-2 rounded-lg border border-warn bg-warn-soft p-2.5 text-[12px]"><input type="checkbox" checked={acks.includes(flag.rule)} onChange={(e) => setAcks((old) => e.target.checked ? [...new Set([...old, flag.rule])] : old.filter((v) => v !== flag.rule))} /><span><b>Acknowledge {flag.rule}</b><br />{flag.message}</span></label>)}

                  <textarea aria-label="Decision reason" value={reason} onChange={(e) => setReason(e.target.value)} rows={2} placeholder={softFlags.length ? 'Required override reason; also used as rejection reason' : 'Decision reason (required for rejection)'} className="rounded-lg border border-line-strong bg-surface px-3 py-2 text-[13px]" />
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" variant="danger" disabled={busy === it.id || !reason.trim()} onClick={() => decide(it, 'reject')}>Reject</Button>
                    <Button size="sm" variant="primary" disabled={own || busy === it.id || softFlags.some((f) => !acks.includes(f.rule)) || (softFlags.length > 0 && !reason.trim())} onClick={() => decide(it, 'approve')}>{busy === it.id ? <Spinner /> : 'Approve'}</Button>
                  </div>

                  <div className="rounded-lg border border-line bg-surface-2 p-3">
                    <div className="text-[11px] font-semibold uppercase text-ink-3">Request information</div>
                    <textarea aria-label="Revision issues" value={issues} onChange={(e) => setIssues(e.target.value)} rows={2} placeholder="Concrete issues — one per line" className="mt-2 w-full rounded-lg border border-line-strong bg-surface px-3 py-2 text-[13px]" />
                    <textarea aria-label="Revision request message" value={requestText} onChange={(e) => setRequestText(e.target.value)} rows={2} placeholder="Editable message to the employee" className="mt-2 w-full rounded-lg border border-line-strong bg-surface px-3 py-2 text-[13px]" />
                    <Button size="sm" variant="secondary" disabled={busy === it.id} onClick={() => requestInformation(it)}>Send request</Button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )
      })}
    </Card>
  )
}
