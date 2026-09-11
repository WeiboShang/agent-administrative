import { useEffect, useState } from 'react'
import { evalApi, type AuditResult } from '@/lib/api'
import { Card, CardHeader, Empty, Pill, Spinner } from '@/components/ui'
import { EvalRunner, JudgeNote, Table, Tiles, num, pct } from './parts'

export default function CrossEval() {
  const [audit, setAudit] = useState<AuditResult | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    evalApi
      .audit()
      .then(setAudit)
      .catch(() => setAudit(null))
      .finally(() => setLoading(false))
  }, [])

  const m = audit?.metrics

  return (
    <div className="flex flex-col gap-4">
      <p className="text-[13px] text-ink-3">
        The human-in-the-loop gate itself (RQ3) and grounded content generation (O4).
      </p>

      <EvalRunner
        name="m4"
        title="M4 — scripted reviewers: does the gate catch injected errors?"
        measures="False-accept rate at the approval gate under three reviewer policies, when a known share of claims carries an injected extraction error."
        method="Deterministic simulation, no LLM calls. blind = no HITL (approve everything) · flag-following = trusts the policy rules only · ideal = verifies each field against the source. The contrast is the argument for HITL: rules alone barely see field errors; verification catches them."
        cost="instant"
        run={() => evalApi.m4(200, 0.5)}
        render={(r) => {
          const P = (r.policies ?? {}) as Record<string, Record<string, unknown>>
          const row = (label: string, k: string) => {
            const p = P[k] ?? {}
            return [
              label,
              pct(p.approve_rate),
              <span key="fa" className={typeof p.false_accept_rate === 'number' && p.false_accept_rate > 0 ? 'font-semibold text-bad' : ''}>
                {pct(p.false_accept_rate)}
              </span>,
              <span key="ec" className={typeof p.errors_caught === 'number' && p.errors_caught >= 1 ? 'font-semibold text-ok' : ''}>
                {pct(p.errors_caught)}
              </span>,
              num(p.edits_per_case),
            ]
          }
          return (
            <div>
              <p className="px-4 pt-3 text-[12.5px] text-ink-3">
                {num(r.n)} claims · {num(r.n_wrong)} carry an injected extraction error
              </p>
              <div className="mt-2">
                <Table
                  head={['Reviewer policy', 'Approve rate', 'False-accept (M4)', 'Errors caught', 'Edits/case (M5)']}
                  rows={[
                    row('Blind — no HITL', 'blind'),
                    row('Flag-following — rules only', 'flag_following'),
                    row('Ideal — verifies vs source', 'ideal'),
                  ]}
                />
              </div>
            </div>
          )
        }}
      />

      <EvalRunner
        name="content"
        title="O4 — decision-note grounding (coverage · faithfulness)"
        measures="Whether an auto-drafted decision note states the key facts (decision, amount, vendor, date, reason) and invents nothing beyond the record."
        method="Notes are drafted from decided synthetic claims — the record plus its policy flags are the ONLY permitted source. Judge is a different family from the generator. Drafts are stored, never sent."
        cost="~40s"
        run={() => evalApi.content(8)}
        render={(r) => {
          const f = (r.faithfulness ?? {}) as Record<string, unknown>
          return (
            <div>
              <Tiles
                items={[
                  { label: `fact coverage (code, n=${num(r.n)})`, value: pct(r.fact_coverage) },
                  { label: 'faithfulness (judge)', value: pct(f.mean_faithfulness) },
                  { label: '≥1 unsupported claim', value: pct(f.unsupported_rate) },
                  { label: 'generation failures', value: num(r.generation_failures) },
                ]}
              />
              <JudgeNote generator={r.generator} judge={r.judge} />
            </div>
          )
        }}
      />

      {/* Live HITL process metrics — not a "run", they read the decisions made in Expenses */}
      <Card>
        <CardHeader
          title="M5 / HITL process metrics — from the live decision log"
          right={m ? <Pill tone="neutral">{m.total} decisions</Pill> : undefined}
        />
        <div className="border-b border-line px-4 py-3 text-[13px] text-ink-2">
          <span className="font-medium text-ink">Measures:</span> what the human actually does at
          the gate — how often they edit the draft, how often they override a soft flag, and
          whether a flag changes the approve rate.
          <p className="mt-1 text-[12.5px] text-ink-3">
            Reads the shared live store, so it reflects decisions you make on the Expenses page
            (it is not a separate run).
          </p>
        </div>
        {loading ? (
          <Empty>
            <Spinner /> Loading…
          </Empty>
        ) : !m ? (
          <Empty>Could not load the audit log.</Empty>
        ) : m.total === 0 ? (
          <Empty>No decisions yet — approve or reject a claim in Expenses, then come back.</Empty>
        ) : (
          <>
            <Tiles
              items={[
                { label: 'decisions', value: m.total, note: `${m.approved} approved · ${m.rejected} rejected` },
                { label: 'edit rate (M5)', value: pct(m.edit_rate) },
                { label: 'override rate', value: pct(m.override_rate) },
                { label: 'business purpose refined', value: pct(m.purpose_refined_rate) },
                {
                  label: 'approve rate — flagged vs clean',
                  value: `${pct(m.flag_influence.with_flag_approve_rate)} / ${pct(m.flag_influence.without_flag_approve_rate)}`,
                  note: `n=${m.flag_influence.n_with_flag} vs ${m.flag_influence.n_without_flag}`,
                },
              ]}
            />
            <div className="overflow-x-auto border-t border-line">
              <Table
                head={['ID', 'Employee', 'Vendor', 'Amount', 'Decision', 'Overrode', 'Edited', 'Reason']}
                rows={audit!.rows.map((r) => [
                  <code key="i" className="text-[12px]">{String(r.id)}</code>,
                  String(r.employee ?? ''),
                  String(r.vendor ?? ''),
                  <span key="a" className="tabular-nums">{String(r.amount ?? '')} {String(r.currency ?? '')}</span>,
                  <Pill key="s" tone={r.status === 'approved' ? 'ok' : 'bad'}>{String(r.status)}</Pill>,
                  (r.overridden_flags as string[])?.join(', ') || '—',
                  (r.changed_fields as string[])?.join(', ') || '—',
                  String(r.reason ?? '—'),
                ])}
              />
            </div>
          </>
        )}
      </Card>
    </div>
  )
}
