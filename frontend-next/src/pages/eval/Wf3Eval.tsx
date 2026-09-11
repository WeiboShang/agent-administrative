import { evalApi } from '@/lib/api'
import { Card, CardHeader, Empty, Pill } from '@/components/ui'
import { EvalRunner, Rate, Table, TierTable, fmtAt, num, pct, useLastResults } from './parts'

const TIER_ORDER = [
  'clean', 'skewed', 'low_res', 'faint', 'cropped',
  'non_receipt', 'over_limit', 'duplicate', 'foreign_currency', 'inconsistent',
]

export default function Wf3Eval() {
  const { last } = useLastResults()
  const cord = last['cord']

  return (
    <div className="flex flex-col gap-4">
      <p className="text-[13px] text-ink-3">
        Multimodal extraction accuracy, refusal, policy detection, and the reasoning layer.
      </p>

      <EvalRunner
        name="receipts"
        title="Receipt extraction — M1 (field × tier) · M6 (refusal) · M3 (policy) · M7 (reasoning)"
        measures="Per-field exact match against gold-by-construction synthetic receipts, across difficulty tiers; correct refusal on non-receipts; whether the policy engine raises the expected flags."
        method="Reference-based on the synthetic generator (labels by construction, no LLM in the loop). Makes live vision calls — costs image quota."
        cost="~30s"
        run={() => evalApi.receipts(2)}
        render={(r) => {
          const ex = (r.extraction ?? {}) as Record<string, Record<string, unknown>>
          const policy = (r.policy ?? []) as { tier: string; policy_ok: boolean; expected: string[]; got: string[] }[]
          const err = r.auto_approve_error_rate
          const m7 = r.reasoning_consistency
          return (
            <div>
              <TierTable
                data={ex}
                order={TIER_ORDER}
                cols={[
                  ['vendor', 'Vendor'],
                  ['date', 'Date'],
                  ['amount', 'Amount'],
                  ['currency', 'Currency'],
                  ['refusal', 'Refusal'],
                ]}
              />

              {typeof err === 'number' && (
                <div className="m-4 rounded-lg border border-warn bg-warn-soft px-3.5 py-3 text-[13px] text-warn">
                  <b>If auto-approved: {pct(err)} of receipts would carry ≥1 wrong field.</b> That is
                  the risk that source verification is designed to catch; scripted M4 estimates
                  the upper-bound value of that check.
                </div>
              )}

              {typeof m7 === 'number' && (
                <div className="mx-4 mb-4 rounded-lg border border-accent bg-accent-soft px-3.5 py-3 text-[13px] text-ink-2">
                  <b className="text-ink">M7 — reasoning consistency: {pct(m7)}</b> of the{' '}
                  <code>inconsistent</code> receipts (printed total ≠ Σ line items) were caught by{' '}
                  <code>check_arithmetic</code>. Read it against M1 above: the vision model reads the
                  fields accurately yet is blind to their mutual inconsistency — the deterministic
                  reasoning layer is what recovers it.
                </div>
              )}

              {policy.length > 0 && (
                <div className="px-4 pb-4">
                  <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">
                    M3 — policy detection
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {/* aggregated per tier — one row per image would be a wall of identical pills */}
                    {[...policy
                      .reduce((m, p) => {
                        const e = m.get(p.tier) ?? { ok: 0, n: 0 }
                        m.set(p.tier, { ok: e.ok + (p.policy_ok ? 1 : 0), n: e.n + 1 })
                        return m
                      }, new Map<string, { ok: number; n: number }>())
                      .entries()].map(([tier, s]) => (
                      <Pill key={tier} tone={s.ok === s.n ? 'ok' : 'bad'}>
                        {tier} {s.ok}/{s.n} {s.ok === s.n ? '✓' : '✗'}
                      </Pill>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )
        }}
      />

      {/* external validity — run from the CLI, shown read-only */}
      <Card>
        <CardHeader
          title="External validity — CORD real receipts"
          right={cord ? <Pill tone="neutral">{fmtAt(cord.at)}</Pill> : undefined}
        />
        <div className="border-b border-line px-4 py-3 text-[13px] text-ink-2">
          <span className="font-medium text-ink">Measures:</span> amount accuracy on real
          photographed receipts — the generalisation gap against the synthetic set.
          <p className="mt-1 text-[12.5px] text-ink-3">
            Run from the CLI (<code>backend.evals.external_cord</code>); public receipt data redacts
            vendor/date as PII, so only the total is cleanly usable.
          </p>
        </div>
        {cord ? (
          <Table
            head={['n', 'Correct', 'Amount accuracy', 'Model']}
            rows={[[
              num(cord.result.n),
              num(cord.result.correct),
              <Rate key="a" v={cord.result.amount_accuracy} />,
              <span key="m" className="font-mono text-[12px]">{cord.model}</span>,
            ]]}
          />
        ) : (
          <Empty>No CORD run recorded.</Empty>
        )}
      </Card>
    </div>
  )
}
