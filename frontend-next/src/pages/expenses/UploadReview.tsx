import { useState, type ReactNode } from 'react'
import { ReceiptText, PencilLine, Upload } from 'lucide-react'
import { api, type EvidenceExtractResult, type ExpenseFields, type LineItem, type Options, type SubmitResult } from '@/lib/api'
import { useAppData } from '@/context/AppData'
import { Button, Card, CardHeader, FlagChip, Pill, Spinner, Stepper, type Step } from '@/components/ui'
import { AgentReasoning, Trace } from '@/components/AgentReasoning'
import DateField from '@/components/DateField'
import { fmtGBP, fmtMoney, isIsoDate, labelOf, toGBP } from '@/lib/format'
import { cn } from '@/lib/utils'

const FORM_FIELDS = [
  'employee_name', 'department', 'vendor', 'date', 'amount',
  'currency', 'payment_method', 'category', 'business_purpose',
] as const
type FieldKey = (typeof FORM_FIELDS)[number]

// mirrors backend forms/registry.py expense_claim.required
const REQUIRED: FieldKey[] = [
  'employee_name', 'vendor', 'date', 'amount', 'currency', 'category', 'business_purpose',
]
// form field → the vision confidence key that covers it
const CONF_KEY: Partial<Record<FieldKey, string>> = {
  vendor: 'vendor', date: 'date', amount: 'amount', category: 'category_guess',
}
const LOW_CONF = 0.6

function optionsFor(k: FieldKey, o: Options | null): string[] | null {
  if (!o) return null
  if (k === 'department') return o.departments
  if (k === 'currency') return o.currencies
  if (k === 'payment_method') return o.payment_methods
  if (k === 'category') return o.categories
  return null
}

type FieldState = 'normal' | 'lowconf' | 'missing'

const FIELD_BORDER: Record<FieldState, string> = {
  normal: 'border-line-strong',
  lowconf: 'border-warn shadow-[inset_3px_0_0_var(--warn)]',
  missing: 'border-bad shadow-[inset_3px_0_0_var(--bad)]',
}

function PaneTitle({ icon, children, sub }: { icon: ReactNode; children: ReactNode; sub: string }) {
  return (
    <div className="mb-3">
      <div className="flex items-center gap-2 text-[12.5px] font-semibold text-ink-2">
        {icon}
        {children}
      </div>
      <p className="mt-0.5 text-[11.5px] text-ink-3">{sub}</p>
    </div>
  )
}

export default function UploadReview({ onSubmitted }: { onSubmitted: () => void }) {
  const { options, actor } = useAppData()
  const [file, setFile] = useState<File | null>(null)
  const [imgUrl, setImgUrl] = useState<string | null>(null)
  const [extracting, setExtracting] = useState(false)
  const [result, setResult] = useState<EvidenceExtractResult | null>(null)
  const [form, setForm] = useState<Record<string, string>>({})
  const [original, setOriginal] = useState<Record<string, string>>({})
  const [extra, setExtra] = useState<{ line_items?: LineItem[]; tax?: number | null; image_phash?: number | string | null }>({})
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState<SubmitResult | null>(null)
  const [problems, setProblems] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)

  const locked = submitted?.status === 'submitted'
  const fx = options?.fx_rates ?? {}

  async function doExtract() {
    if (!file || !actor) return
    setExtracting(true)
    setError(null)
    setSubmitted(null)
    setProblems([])
    try {
      const r = await api.extractEvidence(file, actor.name)
      const init: Record<string, string> = {}
      for (const k of FORM_FIELDS) {
        const v = r.fields[k]
        let s = v === null || v === undefined ? '' : String(v)
        // Keep malformed model output out of the editable calendar field. Manual typing is
        // still validated below because this is a custom control, not a native date input.
        if (k === 'date' && s !== '' && !isIsoDate(s)) s = ''
        init[k] = s
      }
      setResult(r)
      setForm(init)
      setOriginal(init)
      setExtra({ line_items: r.fields.line_items, tax: r.fields.tax, image_phash: r.fields.image_phash })
      if (imgUrl) URL.revokeObjectURL(imgUrl)
      setImgUrl(URL.createObjectURL(file))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setExtracting(false)
    }
  }

  function set(k: FieldKey, v: string) {
    setForm((f) => ({ ...f, [k]: v }))
  }

  function confOf(k: FieldKey): number | undefined {
    const ck = CONF_KEY[k]
    return ck ? result?.vision.field_confidence?.[ck] : undefined
  }

  function stateOf(k: FieldKey): FieldState {
    const v = (form[k] ?? '').trim()
    if (REQUIRED.includes(k) && v === '') return 'missing'
    if (k === 'date' && v !== '' && !isIsoDate(v)) return 'missing'
    const c = confOf(k)
    const edited = (form[k] ?? '') !== (original[k] ?? '')
    if (!edited && c !== undefined && c < LOW_CONF) return 'lowconf'
    return 'normal'
  }

  function hintOf(k: FieldKey): { text: string; tone: 'warn' | 'bad' | 'muted' } | null {
    const v = (form[k] ?? '').trim()
    if (k === 'date') {
      if (v === '') return { text: '⚠ required — pick the date', tone: 'bad' }
      if (!isIsoDate(v)) return { text: '⚠ enter a real date as YYYY-MM-DD', tone: 'bad' }
      return null
    }
    const st = stateOf(k)
    if (st === 'missing') return { text: '⚠ required — please fill', tone: 'bad' }
    if (st === 'lowconf') return { text: `low confidence (${confOf(k)}) — check against the image`, tone: 'warn' }
    return null
  }

  /** GBP readout beside the amount — the receipt's own amount is never overwritten. */
  function fxHint(): string | null {
    const cur = (form.currency || 'GBP').toUpperCase()
    const amt = (form.amount || '').trim()
    if (cur === 'GBP' || amt === '') return null
    const gbp = toGBP(amt, cur, fx)
    if (gbp === null) return `≈ — · no rate for ${cur} — the approver will see this flagged`
    const src = options?.fx_rate_source ? ` (${options.fx_rate_source}, ${options.fx_rate_date})` : ''
    return `≈ ${fmtGBP(gbp)} · rate ${fx[cur]}${src}`
  }

  function validate(): string[] {
    const p: string[] = []
    for (const k of REQUIRED) {
      const v = (form[k] ?? '').trim()
      if (v === '') p.push(`${labelOf(k)} is required`)
      else if (k === 'date' && !isIsoDate(v)) p.push('date must be a real date in YYYY-MM-DD format (e.g. 2025-10-21)')
    }
    const amt = (form.amount ?? '').trim()
    if (amt !== '' && (!Number.isFinite(Number(amt)) || Number(amt) <= 0)) {
      p.push('amount must be a positive number')
    }
    return p
  }

  async function submit() {
    if (!actor) return
    const p = validate()
    setProblems(p)
    if (p.length) return
    const fields: ExpenseFields = {}
    for (const k of FORM_FIELDS) {
      const v = (form[k] ?? '').trim()
      if (k === 'amount') fields.amount = v === '' ? null : parseFloat(v)
      else (fields as Record<string, unknown>)[k] = v === '' ? null : v
    }
    // evidence for the reasoning-layer checks (arithmetic_mismatch / similar_receipt) —
    // carried straight back so the flags survive to the stored record and the approver.
    fields.line_items = extra.line_items
    fields.tax = extra.tax ?? null
    fields.image_phash = extra.image_phash ?? null

    const changed = FORM_FIELDS.filter((k) => (form[k] ?? '') !== (original[k] ?? ''))
    setSubmitting(true)
    setError(null)
    try {
      const r = await api.submitEvidence({
        fields,
        submitted_by: actor.id,
        changed_fields: changed,
        extraction_snapshot: result!.extraction_snapshot,
        critical_second_read: result!.critical_second_read,
        evidence: result!.evidence,
        idempotency_key: `${result!.evidence.receipt_id}:${actor.id}:submit`,
      })
      setSubmitted(r)
      if (r.status === 'submitted') onSubmitted()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const steps: Step[] = [
    { label: 'Receipt', state: result ? 'done' : undefined },
    { label: 'Vision extract', state: result ? 'done' : undefined },
    { label: 'Policy check', sub: 'code', state: result ? 'done' : undefined },
    { label: 'You decide', state: locked ? 'done' : result ? 'active' : undefined },
    { label: 'Submit' , state: locked ? 'done' : undefined },
  ]

  const v = result?.vision
  const flags = result?.flags ?? []

  return (
    <div className="flex flex-col gap-4">
      {/* upload */}
      <Card>
        <div className="flex flex-wrap items-end gap-4 p-4">
          <div className="min-w-[220px] flex-1">
            <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.05em] text-ink-3">
              Receipt image
            </div>
            <div className="flex items-center gap-2.5">
              {/* native file input is visually hidden (its button text is browser-locale)
                  but stays keyboard-reachable; our label drives it */}
              <input
                id="receipt-file"
                type="file"
                accept="image/*"
                className="sr-only"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              <label
                htmlFor="receipt-file"
                className="inline-flex h-9 cursor-pointer items-center gap-2 rounded-lg border border-line-strong bg-surface px-3.5 text-[13px] font-medium hover:bg-surface-2"
              >
                <Upload size={14} strokeWidth={1.7} /> Choose file
              </label>
              <span className={cn('truncate text-[12px]', file ? 'font-medium text-ink' : 'text-ink-3')}>
                {file ? file.name : 'No file selected'}
              </span>
            </div>
          </div>
          <div className="w-[180px]">
            <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.05em] text-ink-3">
              Submitting as
            </div>
            <div className="flex h-9 items-center rounded-lg border border-line bg-surface-2 px-2.5 text-[13px] text-ink-2">
              {actor?.name ?? '—'}
            </div>
          </div>
          <Button variant="primary" onClick={doExtract} disabled={!file || extracting}>
            {extracting ? (
              <>
                <Spinner /> Reading…
              </>
            ) : (
              'Read receipt'
            )}
          </Button>
        </div>
      </Card>

      {error && (
        <div className="rounded-lg border border-bad bg-bad-soft px-4 py-3 text-[13px] text-bad">{error}</div>
      )}

      {result && (
        <>
          <Stepper steps={steps} />

          <Card>
            <CardHeader
              title="Review draft — verify against the receipt"
              right={
                <div className="flex items-center gap-2">
                  <Pill tone="neutral">completeness {Math.round(result.completeness * 100)}%</Pill>
                  {flags.length > 0 && <Pill tone="warn">{flags.length} flags</Pill>}
                </div>
              }
            />
            <div className="flex flex-col gap-4 p-4">
              {/* policy flags — always-visible alerts (like WF2), the one thing the human
                  must not miss; full-width so they read before anything else */}
              {flags.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {flags.map((f, i) => (
                    <FlagChip key={`${f.rule}-${i}`} severity={f.severity}>
                      {f.message}
                    </FlagChip>
                  ))}
                </div>
              )}

              {/* agent reasoning — folded by default; full-width and in the same order WF2 uses
                  (alerts → reasoning → the form), so it no longer inflates the receipt column.
                  Each row: what the vision model read from the receipt → what deterministic
                  code resolved & checked it into. */}
              <AgentReasoning>
                  {v?.not_a_receipt ? (
                    <Trace label="receipt?" read="model says NO" resolved="check the image" bad />
                  ) : (
                    <>
                      <Trace
                        label="vendor"
                        read={v?.vendor}
                        resolved={result.fields.vendor}
                        bad={!result.fields.vendor}
                      />
                      <Trace
                        label="date"
                        read={v?.date}
                        resolved={result.fields.date}
                        bad={!result.fields.date}
                      />
                      <Trace
                        label="amount"
                        read={fmtMoney(v?.amount, v?.currency)}
                        resolved={
                          result.fields.amount != null && result.fields.amount !== ''
                            ? `${result.fields.amount} ${result.fields.currency ?? ''}`.trim()
                            : null
                        }
                      />
                      <Trace label="category" read={v?.category_guess} resolved={result.fields.category} />
                      <Trace label="payment" read={v?.payment_method} resolved={result.fields.payment_method} />
                      <Trace
                        label="items"
                        read={v?.line_items?.length ? `${v.line_items.length} line(s)` : null}
                        resolved={
                          extra.line_items?.length
                            ? `${extra.line_items.length} · Σ ${extra.line_items
                                .reduce((s, it) => s + (it.amount || 0), 0)
                                .toFixed(2)}`
                            : null
                        }
                      />
                      <Trace
                        label="checks"
                        read={null}
                        resolved={flags.length ? `⚠ ${flags.length} flag(s)` : 'clean ✓'}
                        bad={flags.length > 0}
                      />
                    </>
                  )}
              </AgentReasoning>

              <div className="flex flex-wrap gap-x-5 gap-y-1 rounded-lg border border-line bg-surface-2 px-3 py-2 font-mono text-[10.5px] text-ink-3">
                <span>evidence {result.evidence.receipt_id}</span>
                <span>SHA-256 {result.evidence.receipt_sha256.slice(0, 16)}…</span>
                <span>{result.evidence.receipt_byte_size.toLocaleString('en-GB')} bytes</span>
                <span>uploaded {new Date(result.evidence.receipt_uploaded_at).toLocaleString('en-GB')}</span>
              </div>

              {/* receipt (left) + form (right) — reasoning/JSON now live outside this grid, so
                  the two columns are simply image vs form: balanced heights, no dead space */}
              <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 lg:items-start">
                {/* left: the receipt — sticky so it stays in view while you work down the form;
                    height-capped and click-to-open-full so a tall portrait receipt can't blow
                    out the column */}
                <div className="lg:sticky lg:top-4">
                  <PaneTitle
                    icon={<ReceiptText size={15} strokeWidth={1.6} />}
                    sub="Compare every value on the right against this image"
                  >
                    Receipt
                  </PaneTitle>
                  {imgUrl && (
                    <a
                      href={imgUrl}
                      target="_blank"
                      rel="noreferrer"
                      title="Open full size"
                      className="block max-h-[600px] cursor-zoom-in overflow-auto rounded-lg border border-line bg-surface-2"
                    >
                      <img src={imgUrl} alt="receipt" className="w-full" />
                    </a>
                  )}
                </div>

                {/* right: editable form */}
                <div>
                  <PaneTitle
                    icon={<PencilLine size={15} strokeWidth={1.6} />}
                    sub="Fix anything the model misread, fill what's missing, then submit — the approver decides"
                  >
                    Verify &amp; edit
                  </PaneTitle>

                <div className="grid gap-3 sm:grid-cols-2">
                  {FORM_FIELDS.map((k) => {
                    const opts = optionsFor(k, options)
                    const st = stateOf(k)
                    const hint = hintOf(k)
                    const wide = k === 'business_purpose'
                    return (
                      <div key={k} className={cn('flex flex-col gap-1.5', wide && 'sm:col-span-2')}>
                        <label
                          htmlFor={`f_${k}`}
                          className="text-[11px] font-semibold uppercase tracking-[0.05em] text-ink-3"
                        >
                          {labelOf(k)}
                        </label>
                        {opts ? (
                          <select
                            id={`f_${k}`}
                            disabled={locked}
                            value={form[k] ?? ''}
                            onChange={(e) => set(k, e.target.value)}
                            className={cn(
                              'h-9 w-full rounded-lg border bg-surface px-2.5 text-[13.5px] text-ink outline-none transition',
                              'focus:border-accent focus:ring-[3px] focus:ring-accent-ring disabled:opacity-60',
                              FIELD_BORDER[st],
                            )}
                          >
                            <option value="" />
                            {opts.map((o) => (
                              <option key={o} value={o}>
                                {o}
                              </option>
                            ))}
                          </select>
                        ) : k === 'date' ? (
                          <DateField
                            id={`f_${k}`}
                            value={form[k] ?? ''}
                            onChange={(v) => set(k, v)}
                            disabled={locked}
                            expectedTiming="past"
                            className={cn(
                              'h-9 w-full rounded-lg border bg-surface px-2.5 text-[13.5px] text-ink outline-none transition',
                              'focus:border-accent focus:ring-[3px] focus:ring-accent-ring disabled:opacity-60',
                              FIELD_BORDER[st],
                            )}
                          />
                        ) : (
                          <input
                            id={`f_${k}`}
                            disabled={locked}
                            value={form[k] ?? ''}
                            onChange={(e) => set(k, e.target.value)}
                            className={cn(
                              'h-9 w-full rounded-lg border bg-surface px-2.5 text-[13.5px] text-ink outline-none transition',
                              'focus:border-accent focus:ring-[3px] focus:ring-accent-ring disabled:opacity-60',
                              FIELD_BORDER[st],
                            )}
                          />
                        )}
                        {hint && (
                          <span
                            className={cn(
                              'text-[11.5px]',
                              hint.tone === 'bad' && 'text-bad',
                              hint.tone === 'warn' && 'text-warn',
                              hint.tone === 'muted' && 'text-ink-3',
                            )}
                          >
                            {hint.text}
                          </span>
                        )}
                        {k === 'amount' && fxHint() && (
                          <span className="text-[11.5px] text-ink-3">{fxHint()}</span>
                        )}
                      </div>
                    )
                  })}
                </div>

                {problems.length > 0 && (
                  <div className="mt-4 rounded-lg border border-warn bg-warn-soft px-3.5 py-3 text-[13px] text-warn">
                    <b>Can't submit yet</b> — please fix:
                    <ul className="mt-1 list-disc pl-5">
                      {problems.map((p) => (
                        <li key={p}>{p}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {submitted?.status === 'submitted' && (
                  <div className="mt-4 rounded-lg border border-ok bg-ok-soft px-3.5 py-3 text-[13px] text-ok">
                    <b>Submitted for approval.</b> Claim <code>{submitted.record_id}</code> is in the
                    approver queue
                    {submitted.flags?.length ? ` · ${submitted.flags.length} policy flag(s) attached` : ''}.
                  </div>
                )}
                {submitted?.status === 'blocked_missing_required' && (
                  <div className="mt-4 rounded-lg border border-warn bg-warn-soft px-3.5 py-3 text-[13px] text-warn">
                    <b>Can't submit</b> — still missing: {(submitted.missing ?? []).join(', ')}.
                  </div>
                )}

                <div className="mt-4 flex justify-end">
                  <Button variant="primary" onClick={submit} disabled={submitting || locked}>
                    {submitting ? (
                      <>
                        <Spinner /> Submitting…
                      </>
                    ) : (
                      'Submit for approval →'
                    )}
                  </Button>
                </div>
                </div>
              </div>

              {/* deepest detail — full-width at the very bottom, rarely opened */}
              <details>
                <summary className="cursor-pointer text-[12px] text-ink-3">Raw vision output (JSON)</summary>
                <pre className="mt-2 max-h-56 overflow-auto rounded-lg border border-line bg-surface-2 p-3 font-mono text-[11px] leading-relaxed text-ink-2">
                  {JSON.stringify(v, null, 2)}
                </pre>
              </details>
            </div>
          </Card>
        </>
      )}
    </div>
  )
}
