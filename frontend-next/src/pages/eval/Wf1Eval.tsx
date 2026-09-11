import { evalApi } from '@/lib/api'
import { Card, CardHeader, Empty, Pill } from '@/components/ui'
import { EvalRunner, JudgeNote, Rate, Table, TierTable, Tiles, fmtAt, num, pct, useLastResults } from './parts'

/** One column of the feedback A/B: a run recorded under `resultKey`, or "not yet run". */
function FeedbackColumn({ label, sub, resultKey, last }: {
  label: string
  sub: string
  resultKey: string
  last: Record<string, { result: Record<string, unknown>; at: string }>
}) {
  const rec = last[resultKey]
  const pairs = (rec?.result?.pairs ?? {}) as Record<string, Record<string, unknown>>
  return (
    <div className="flex-1 min-w-[220px]">
      <div className="text-[12.5px] font-semibold text-ink">{label}</div>
      <div className="text-[11px] text-ink-3">{sub}</div>
      {!rec ? (
        <div className="mt-2 rounded-lg border border-line bg-surface-2 px-3 py-4 text-center text-[12px] text-ink-3">
          not yet run
        </div>
      ) : (
        <div className="mt-2 flex flex-col gap-1.5">
          {Object.entries(pairs).map(([delta, m]) => (
            <div key={delta} className="flex items-center justify-between gap-2 text-[12px]">
              <span className="truncate font-mono text-ink-2">{delta.replace(/_/g, ' ')}</span>
              <Rate v={m.abstain_rate} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * The feedback-conditioned prompting A/B (docs/results.md §6). This closes the loop on the
 * reviewer's Dismiss decisions — held-out negatives are injected as few-shot examples — but
 * it is CLI-only, not a click-to-run card: each condition is 48 threads (~30-50k tokens) and
 * the three columns must use the SAME test cases to be comparable, which the shared cache
 * key already guarantees. This card is a read-only comparison of whatever has been collected.
 */
function FeedbackAB({ last }: { last: Record<string, { result: Record<string, unknown>; at: string }> }) {
  const have = ['pairs', 'pairs_fb_in_family', 'pairs_fb_cross_family'].some((k) => last[k])
  return (
    <Card>
      <CardHeader
        title="Feedback-conditioned prompting — does closing the loop help?"
        right={have ? <Pill tone="ok">data collected</Pill> : <Pill tone="neutral">none yet</Pill>}
      />
      <div className="border-b border-line px-4 py-3">
        <p className="text-[13px] text-ink-2">
          <span className="font-medium text-ink">Measures:</span> the reviewer's Dismiss
          decisions are already recorded but were never fed back. Appending a few as few-shot
          negatives is prompt-layer conditioning, not persistent agent memory — the agent
          still only proposes.
        </p>
        <p className="mt-1 text-[12.5px] text-ink-3">
          <b>in_family</b> negatives share the test δ's sentence frame (upper bound — could be
          pattern-matching). <b>cross_family</b> negatives come only from the OTHER three
          families — if abstention improves there too, the model generalised "this kind of
          phrasing is not a request", not just the frame. Negatives are drawn from a
          vocabulary reserved for this purpose, disjoint from every test case, so a negative
          can never leak a test answer. Run via CLI (<code>run_full_eval.py pairs --feedback
          in_family|cross_family</code>) so the two conditions share test cases with the
          baseline.
        </p>
      </div>
      <div className="flex flex-wrap gap-6 p-4">
        <FeedbackColumn label="Baseline" sub="no feedback" resultKey="pairs" last={last} />
        <FeedbackColumn label="in_family" sub="k=4, same δ frame" resultKey="pairs_fb_in_family" last={last} />
        <FeedbackColumn label="cross_family" sub="k=4, other δ frames" resultKey="pairs_fb_cross_family" last={last} />
      </div>
      {!have && (
        <p className="border-t border-line px-4 py-3 text-[12px] text-ink-3">
          See <code>docs/results.md §6</code> for the resume commands and checkpoint state.
        </p>
      )}
    </Card>
  )
}

export default function Wf1Eval() {
  const { last } = useLastResults()
  const ami = last['ami']

  return (
    <div className="flex flex-col gap-4">
      <p className="text-[13px] text-ink-3">
        Action detection, abstention, depth robustness, and key-point / summary quality.
      </p>

      <EvalRunner
        name="triage"
        title="Action detection — recall · exact match · correct refusal"
        measures="Whether the agent detects the actionable intents buried in a multi-party thread, and whether it correctly abstains when there is nothing to do."
        method="Synthetic threads per difficulty tier, gold by construction. Correct refusal is the abstention test — a false positive books a meeting nobody asked for."
        cost="~20s"
        run={() => evalApi.triage(3)}
        render={(r) => (
          <TierTable
            data={(r.triage ?? {}) as Record<string, Record<string, unknown>>}
            cols={[
              ['recall', 'Action recall'],
              ['exact', 'Exact match'],
              ['correct_refusal', 'Correct refusal'],
            ]}
          />
        )}
      />

      <EvalRunner
        name="pairs"
        title="Minimal pairs — does it know when NOT to act?"
        measures="Abstention under a controlled contrast. Every case ships a twin whose thread is identical except for one cue (δ): one side must be routed, the other must be refused."
        method="Because a constant policy is right on exactly one side of every twin, paired accuracy floors 'always act' and 'always abstain' at 0. CAR conditions abstention on the pairs the model got right on the act side, so a model that is merely inert cannot look good at restraint."
        cost="~40s"
        run={() => evalApi.pairs(4)}
        render={(r) => {
          const P = (r.pairs ?? {}) as Record<string, Record<string, unknown>>
          const deltas = Object.keys(P)
          return (
            <div>
              <Table
                head={['δ contrast', 'n', 'Act (T+)', 'Abstain (T−)', 'Gap', 'Paired acc.', 'CAR']}
                rows={deltas.map((d) => {
                  const m = P[d]
                  const act = m.act_rate as number
                  const abs = m.abstain_rate as number
                  const gap = typeof act === 'number' && typeof abs === 'number' ? act - abs : null
                  return [
                    <span key="d" className="font-mono text-[12.5px]">{d.replace(/_/g, ' ')}</span>,
                    num(m.n),
                    <Rate key="a" v={act} />,
                    <Rate key="b" v={abs} />,
                    // signed points, not a rate: positive = biased toward acting, which is
                    // the harmful direction here (a spurious booking reaches the calendar)
                    <span
                      key="g"
                      className={gap !== null && gap > 0.05 ? 'font-semibold text-warn' : 'text-ink-3'}
                    >
                      {gap === null ? '—' : `${gap > 0 ? '+' : ''}${Math.round(gap * 100)} pts`}
                    </span>,
                    <Rate key="p" v={m.paired_accuracy} />,
                    m.car === null || m.car === undefined ? (
                      <span key="c" className="text-ink-3">—</span>
                    ) : (
                      <Rate key="c" v={m.car} />
                    ),
                  ]
                })}
              />
              <div className="mx-4 my-4 rounded-lg border border-accent bg-accent-soft px-3.5 py-3 text-[12.5px] text-ink-2">
                <b className="text-ink">Reading it:</b> a positive <b>Gap</b> is the
                act-over-abstain bias — the model routes the twin it should have refused.
                <b> Paired acc.</b> is the honest headline (both sides right).
                <b> CAR</b> removes the inert-model confound.
              </div>
            </div>
          )
        }}
      />

      <FeedbackAB last={last} />

      <EvalRunner
        name="retraction"
        title="Retracted plans — model abstention vs deterministic recovery"
        measures="A fully specified meeting (topic · day · time · room · attendees) that the same thread later calls off. Gold is no action: booking a cancelled meeting is a real-world harm."
        method="near/far vary how many turns separate the plan from its retraction. When the model fails to abstain, check_retraction (a deterministic scan of the lines AFTER the action's source span) gets a second chance — the WF1 analogue of WF3's arithmetic self-consistency."
        cost="~25s"
        run={() => evalApi.retraction(4)}
        render={(r) => {
          const R = (r.retraction ?? {}) as Record<string, Record<string, unknown>>
          const fp = r.retraction_false_positive_rate
          const ctrlN = r.retraction_control_n
          return (
            <div>
              <Table
                head={['Retraction distance', 'n', 'Model abstained', 'Code recovery', 'Net caught']}
                rows={Object.keys(R).map((tier) => [
                  tier.replace('retracted_', ''),
                  num(R[tier].n),
                  <Rate key="m" v={R[tier].model_abstained} />,
                  R[tier].code_recovery === null ? (
                    <span key="c" className="text-ink-3">— (model caught all)</span>
                  ) : (
                    <Rate key="c" v={R[tier].code_recovery} />
                  ),
                  <Rate key="n" v={R[tier].net_caught} />,
                ])}
              />
              {/* The recovery rate is only meaningful next to the false-positive rate — a
                  check that fired on everything would score a perfect recovery. */}
              {typeof fp === 'number' && (
                <div
                  className={`mx-4 my-4 rounded-lg border px-3.5 py-3 text-[12.5px] ${
                    fp > 0 ? 'border-warn bg-warn-soft text-warn' : 'border-ok bg-ok-soft text-ok'
                  }`}
                >
                  <b>False-positive rate {pct(fp)}</b> on {num(ctrlN)} genuine, non-retracted
                  meeting threads.{' '}
                  {fp > 0
                    ? 'The check fires on healthy threads — discount the recovery rate accordingly.'
                    : 'The check never fired on a healthy thread, so the recovery above is real signal, not an always-on alarm.'}
                </div>
              )}
            </div>
          )
        }}
      />

      <EvalRunner
        name="underspecified"
        title="Underspecified requests — does it invent the missing parts?"
        measures="A genuine request to meet that names no day, no time and no attendees. Detection is the CORRECT behaviour here, so this scores seed_fields, not abstention: what did the model fill in that nobody said?"
        method="AgentAbstain's S1 scenario (missing critical parameter), adapted. Values are read through the shared null-normaliser, so a stringy 'not specified' counts as absent rather than as an invention."
        cost="~15s"
        run={() => evalApi.underspecified(6)}
        render={(r) => {
          const u = (r.underspecified ?? {}) as Record<string, unknown>
          const byField = (u.fabricated_by_field ?? {}) as Record<string, number>
          const fields = ['date', 'time', 'participants']
          return (
            <div>
              <Tiles
                items={[
                  { label: `detection rate (n=${num(u.n)})`, value: pct(u.detection_rate) },
                  { label: 'fabricated any absent field', value: pct(u.fabrication_rate) },
                ]}
              />
              <Table
                head={['Absent field', 'Fabrication rate']}
                rows={fields.map((f) => [
                  <span key="f" className="font-mono text-[12.5px]">{f}</span>,
                  <span
                    key="v"
                    className={(byField[f] ?? 0) > 0 ? 'font-semibold text-bad' : 'text-ok'}
                  >
                    {pct(byField[f] ?? 0)}
                  </span>,
                ])}
              />
              <div className="mx-4 my-4 rounded-lg border border-accent bg-accent-soft px-3.5 py-3 text-[12.5px] text-ink-2">
                <b className="text-ink">The split is the finding.</b> A fabricated slot is the
                harmful case — it would put a wrong meeting on a real calendar — and the model
                avoids it entirely. Participants are a different failure: it copies whoever
                spoke in the thread, reading "who is in the room" as "who is in the meeting".
              </div>
            </div>
          )
        }}
      />

      <EvalRunner
        name="position"
        title="Needle-in-a-haystack — recall vs thread length × action position"
        measures="Whether detection degrades as the actionable turn is buried deeper in a longer thread."
        method="One meeting hidden in 10/25/50-turn synthetic threads at an early / middle / late position. Cell = detection recall; cov = gold facts present in the summary."
        cost="~40s"
        run={() => evalApi.position(2)}
        render={(r) => {
          const g = (r.position ?? {}) as Record<string, Record<string, { recall?: number; coverage?: number }>>
          const lens = Object.keys(g).sort((a, b) => Number(a) - Number(b))
          return (
            <Table
              head={['Thread length', 'Action early', 'Action middle', 'Action late']}
              rows={lens.map((len) => [
                `${len} turns`,
                ...(['early', 'middle', 'late'] as const).map((p) => (
                  <span key={p}>
                    <Rate v={g[len][p]?.recall} />
                    {typeof g[len][p]?.coverage === 'number' && (
                      <span className="text-ink-3"> · cov {pct(g[len][p].coverage)}</span>
                    )}
                  </span>
                )),
              ])}
            />
          )
        }}
      />

      <EvalRunner
        name="summary"
        title="Key points &amp; summary quality — gold-fact coverage (code) · faithfulness (LLM judge)"
        measures="Coverage: are the buried facts (topic · day · time · people) actually in the summary? Faithfulness: does the summary invent claims the thread does not support?"
        method="Coverage is computed in code against gold. Faithfulness is scored by an LLM judge of a DIFFERENT family from the generator — the same summaries scored 0.95 under a same-family judge and 0.85 under Gemini."
        cost="~30s"
        run={() => evalApi.summary(4)}
        render={(r) => {
          const f = (r.faithfulness ?? {}) as Record<string, unknown>
          return (
            <div>
              <Tiles
                items={[
                  { label: `gold-fact coverage (code, n=${num(r.n)})`, value: pct(r.coverage) },
                  { label: 'faithfulness — claims supported by the thread', value: pct(f.mean_faithfulness) },
                  { label: 'summaries with ≥1 invented claim', value: pct(f.unsupported_rate) },
                ]}
              />
              <JudgeNote generator={r.generator} judge={r.judge} />
            </div>
          )
        }}
      />

      <Card>
        <CardHeader
          title="External validity — AMI/QMSum real meeting transcripts"
          right={ami ? <Pill tone="neutral">{fmtAt(ami.at)}</Pill> : undefined}
        />
        <div className="border-b border-line px-4 py-3 text-[13px] text-ink-2">
          <span className="font-medium text-ink">Measures:</span> correct abstention on real,
          messy transcripts — no public corpus labels administrative intent, so recall is not
          measurable here; this is an <b>abstention test only</b>.
          <p className="mt-1 text-[12.5px] text-ink-3">
            Run from the CLI (<code>backend.evals.external_ami</code>).
          </p>
        </div>
        {ami ? (
          <Table
            head={['n', 'Max turns', 'Correct abstention', 'Spurious meeting', 'Spurious leave']}
            rows={[[
              num(ami.result.n),
              num(ami.result.max_turns),
              <Rate key="c" v={ami.result.correct_abstention} />,
              num(ami.result.spurious_schedule_meeting),
              num(ami.result.spurious_leave_request),
            ]]}
          />
        ) : (
          <Empty>No AMI run recorded.</Empty>
        )}
      </Card>
    </div>
  )
}
