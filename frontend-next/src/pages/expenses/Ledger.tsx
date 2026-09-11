import { useEffect, useState } from 'react'
import { FileSpreadsheet, Mail } from 'lucide-react'
import { api, type LedgerResult, type NoteResult } from '@/lib/api'
import { Button, BudgetTile, Card, CardHeader, Empty, Pill, Spinner } from '@/components/ui'
import { fmtGBP, fmtMoney } from '@/lib/format'

const STATUS_TONE: Record<string, 'ok' | 'bad' | 'neutral'> = {
  approved: 'ok',
  rejected: 'bad',
}

export default function Ledger({ tick }: { tick: number }) {
  const [data, setData] = useState<LedgerResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [note, setNote] = useState<NoteResult | null>(null)
  // per-record, so drafting one note doesn't disable the button on every other row
  const [noteBusy, setNoteBusy] = useState<string | null>(null)
  const [noteSaved, setNoteSaved] = useState<string | null>(null)
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    api
      .ledger()
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [tick])

  async function draft(id: string) {
    setNoteBusy(id)
    setNoteSaved(null)
    setNote(null)
    try {
      const n = await api.draftNote(id)
      setNote(n)
      setSubject(n.subject ?? '')
      setBody(n.body ?? '')
    } catch (e) {
      setNote({ status: 'error', detail: (e as Error).message })
    } finally {
      setNoteBusy(null)
    }
  }

  async function save() {
    if (!note?.note_id) return
    setNoteSaved(null)
    try {
      const r = await api.saveNote({ note_id: note.note_id, subject, body })
      setNoteSaved(r.status === 'saved' ? `Saved as ${note.note_id} (draft — stored, not sent).` : 'Save failed.')
    } catch (error) {
      setNoteSaved(`Save failed: ${(error as Error).message}`)
    }
  }

  async function exportExcel() {
    setExporting(true)
    setExportError(null)
    try {
      const { blob, filename } = await api.exportLedger()
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = filename
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      URL.revokeObjectURL(url)
    } catch (error) {
      setExportError((error as Error).message || 'Excel export failed.')
    } finally {
      setExporting(false)
    }
  }

  const records = data?.records ?? []
  // most-consumed first: the departments with movement lead, the untouched ones sink
  const budgets = Object.entries(data?.budgets ?? {}).sort(
    (a, b) => (b[1].total - b[1].remaining) / b[1].total - (a[1].total - a[1].remaining) / a[1].total,
  )
  const budgetTotal = budgets.reduce((s, [, b]) => s + b.total, 0)
  const budgetUsed = budgets.reduce((s, [, b]) => s + (b.total - b.remaining), 0)
  const overallPct = budgetTotal > 0 ? Math.round((budgetUsed / budgetTotal) * 100) : 0

  return (
    <>
      <Card>
      <CardHeader
        title="Ledger"
        right={
          <div className="flex items-center gap-2">
            <Pill tone="neutral">{records.length} records</Pill>
            <Button size="sm" disabled={exporting} onClick={() => void exportExcel()}>
              {exporting ? <Spinner /> : <FileSpreadsheet size={13} strokeWidth={1.7} />}
              {exporting ? 'Exporting…' : 'Export Excel'}
            </Button>
          </div>
        }
      />

      {exportError && (
        <div className="border-b border-line bg-bad-soft px-4 py-2 text-[12.5px] text-bad">
          Export failed: {exportError}
        </div>
      )}

      {loading ? (
        <Empty>
          <Spinner /> Loading…
        </Empty>
      ) : records.length === 0 ? (
        <Empty>No claims yet.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse tabular-nums">
            <thead>
              <tr>
                {['ID', 'Employee', 'Vendor', 'Amount', 'In GBP', 'Category', 'Status', ''].map((h) => (
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
              {[...records].reverse().map((r) => {
                const nonGbp = (r.currency || 'GBP').toUpperCase() !== 'GBP'
                const decided = r.status === 'approved' || r.status === 'rejected'
                return (
                  <tr key={r.id} className="hover:bg-surface-2">
                    <td className="border-b border-line px-4 py-3 font-mono text-[12px] text-ink-3">{r.id}</td>
                    <td className="border-b border-line px-4 py-3 text-[13.5px] font-medium text-ink">
                      {r.employee_name}
                    </td>
                    <td className="border-b border-line px-4 py-3 text-[13.5px] text-ink">{r.vendor}</td>
                    <td className="border-b border-line px-4 py-3 text-right text-[13.5px] font-medium text-ink">
                      {fmtMoney(r.amount, r.currency)}
                    </td>
                    <td className="border-b border-line px-4 py-3 text-right text-[13.5px] text-ink-3">
                      {nonGbp ? fmtGBP(r.amount_gbp) : ''}
                    </td>
                    <td className="border-b border-line px-4 py-3 text-[13.5px] text-ink">{r.category}</td>
                    <td className="border-b border-line px-4 py-3">
                      <Pill tone={STATUS_TONE[r.status] ?? 'neutral'}>{r.status}</Pill>
                    </td>
                    <td className="border-b border-line px-4 py-3">
                      {decided && (
                        <Button size="sm" variant="ghost" disabled={noteBusy === r.id} onClick={() => draft(r.id)}>
                          <Mail size={13} strokeWidth={1.7} /> {noteBusy === r.id ? '…' : 'Note'}
                        </Button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
            {data?.approved_total_gbp !== undefined && (
              <tfoot>
                <tr>
                  <td colSpan={3} className="px-4 py-3 text-right text-[12.5px] text-ink-3">
                    Approved total
                  </td>
                  <td colSpan={5} className="px-4 py-3 text-[13.5px] font-semibold text-ink">
                    {fmtGBP(data.approved_total_gbp)}
                  </td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}

      {note && (
        <div className="border-t border-line p-4">
          {note.status === 'draft' ? (
            <>
              <div className="mb-2 text-[12.5px] font-semibold text-ink-2">
                Decision note — draft
                <span className="ml-2 font-normal text-ink-3">
                  generated from the record + its policy flags · edit &amp; save; never sent
                </span>
              </div>
              <input
                aria-label="Decision note subject"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                className="mb-2 h-9 w-full rounded-lg border border-line-strong bg-surface px-2.5 text-[13.5px] outline-none focus:border-accent focus:ring-[3px] focus:ring-accent-ring"
              />
              <textarea
                aria-label="Decision note body"
                rows={6}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                className="w-full resize-y rounded-lg border border-line-strong bg-surface p-2.5 text-[13.5px] outline-none focus:border-accent focus:ring-[3px] focus:ring-accent-ring"
              />
              <div className="mt-2 flex items-center gap-3">
                <Button size="sm" variant="primary" onClick={save}>
                  Save draft
                </Button>
                {noteSaved && <span className="text-[12px] text-ink-3">{noteSaved}</span>}
              </div>
            </>
          ) : note.status === 'not_decided' ? (
            <div className="text-[13px] text-ink-3">Only decided (approved/rejected) claims get a note.</div>
          ) : (
            <div className="text-[13px] text-bad">Error: {note.detail ?? note.raw ?? 'generation failed'}</div>
          )}
        </div>
      )}
      </Card>

      {budgets.length > 0 && (
        <Card>
          <CardHeader
            title="Budget utilisation"
            right={
              <Pill tone={overallPct >= 90 ? 'warn' : 'neutral'}>
                {overallPct}% of £{Math.round(budgetTotal).toLocaleString('en-GB')}
              </Pill>
            }
          />
          <div className="grid grid-cols-1 gap-2.5 p-4 sm:grid-cols-2 lg:grid-cols-3">
            {budgets.map(([dept, b]) => (
              <BudgetTile key={dept} label={dept} remaining={b.remaining} total={b.total} />
            ))}
          </div>
        </Card>
      )}
    </>
  )
}
