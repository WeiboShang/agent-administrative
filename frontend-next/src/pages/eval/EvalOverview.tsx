import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  GitCompareArrows,
  HeartHandshake,
  MousePointerClick,
  Play,
  ShieldCheck,
} from 'lucide-react'
import { Button, Card, Empty, Pill, Spinner } from '@/components/ui'
import {
  evalApi,
  type CaseContext,
  type OutcomeSuite,
  type OutcomeSummary,
  type ReviewValueSummary,
} from '@/lib/api'
import { cn } from '@/lib/utils'

const WORKFLOWS = ['wf1', 'wf2', 'wf3'] as const
const WORKFLOW_NAME = {
  wf1: 'WF1 Inbox routing',
  wf2: 'WF2 Meeting scheduling',
  wf3: 'WF3 Expense review',
}

function percentage(value: number | null | undefined) {
  return typeof value === 'number' ? `${Math.round(value * 100)}%` : 'Not measured'
}

function conditionLabel(condition: string) {
  return condition
    .replace('baseline_', 'Baseline: ')
    .replace('optimised_', 'Optimised: ')
    .replaceAll('_', ' ')
}

function MetricCard({
  icon,
  label,
  value,
  question,
  note,
  tone = 'neutral',
}: {
  icon: ReactNode
  label: string
  value: string
  question: string
  note: string
  tone?: 'ok' | 'bad' | 'accent' | 'neutral'
}) {
  const tones = {
    ok: 'border-ok/30 bg-ok-soft text-ok',
    bad: 'border-bad/30 bg-bad-soft text-bad',
    accent: 'border-accent/30 bg-accent-soft text-accent',
    neutral: 'border-line-strong bg-surface-2 text-ink-2',
  }
  return (
    <div className="rounded-xl border border-line-strong bg-surface p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[11px] font-bold uppercase tracking-[0.075em] text-ink-3">{label}</div>
          <div className="mt-2 text-[30px] font-[680] leading-none tracking-[-0.035em] tabular-nums text-ink">
            {value}
          </div>
        </div>
        <div className={cn('grid size-9 place-items-center rounded-lg border', tones[tone])}>{icon}</div>
      </div>
      <p className="mt-3 text-[12.5px] font-medium leading-5 text-ink">{question}</p>
      <p className="mt-1 text-[11.5px] leading-4 text-ink-3">{note}</p>
    </div>
  )
}

function PairBar({
  workflow,
  baseline,
  optimised,
}: {
  workflow: (typeof WORKFLOWS)[number]
  baseline?: OutcomeSummary
  optimised?: OutcomeSummary
}) {
  const base = baseline?.task_outcome_rate ?? 0
  const opt = optimised?.task_outcome_rate ?? 0
  const delta = Math.round((opt - base) * 100)
  return (
    <div className="grid gap-3 border-b border-line px-4 py-4 last:border-b-0 lg:grid-cols-[190px_1fr_80px] lg:items-center">
      <div>
        <div className="text-[13px] font-semibold text-ink">{WORKFLOW_NAME[workflow]}</div>
        <div className="mt-0.5 text-[11.5px] text-ink-3">
          matched cached inputs  |  n={baseline?.n ?? 0} per condition
        </div>
      </div>
      <div className="space-y-2">
        <div className="grid grid-cols-[76px_1fr_42px] items-center gap-2 text-[11.5px]">
          <span className="text-ink-3">Baseline</span>
          <div className="h-2 overflow-hidden rounded-full bg-surface-3">
            <div className="h-full rounded-full bg-ink-3" style={{ width: `${base * 100}%` }} />
          </div>
          <span className="text-right font-medium tabular-nums text-ink-2">{percentage(base)}</span>
        </div>
        <div className="grid grid-cols-[76px_1fr_42px] items-center gap-2 text-[11.5px]">
          <span className="font-medium text-accent">Optimised</span>
          <div className="h-2 overflow-hidden rounded-full bg-surface-3">
            <div className="h-full rounded-full bg-accent" style={{ width: `${opt * 100}%` }} />
          </div>
          <span className="text-right font-semibold tabular-nums text-ink">{percentage(opt)}</span>
        </div>
      </div>
      <div className={cn('text-right text-[13px] font-semibold tabular-nums', delta >= 0 ? 'text-ok' : 'text-bad')}>
        {delta >= 0 ? '+' : ''}{delta} pp
      </div>
    </div>
  )
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-64 overflow-auto rounded-lg border border-line bg-surface-2 p-3 font-mono text-[11px] leading-5 text-ink-2">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

function DetailSection({ title, children, open = false }: { title: string; children: ReactNode; open?: boolean }) {
  return (
    <details className="group border-b border-line last:border-b-0" open={open}>
      <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-[12.5px] font-semibold text-ink">
        {title}
        <ChevronDown className="size-4 text-ink-3 transition-transform group-open:rotate-180" />
      </summary>
      <div className="px-4 pb-4">{children}</div>
    </details>
  )
}

function ReviewMatrix({ value: v }: { value: ReviewValueSummary }) {
  const cells = [
    { label: 'Correct acceptance', value: v.correct_acceptance, note: 'Good draft, correct final result', tone: 'bg-ok-soft text-ok' },
    { label: 'Over-correction', value: v.over_correction, note: 'Good draft changed into a failure', tone: 'bg-warn-soft text-warn' },
    { label: 'Rescued', value: v.rescued, note: 'Wrong draft corrected by review', tone: 'bg-accent-soft text-accent' },
    { label: 'Over-reliance', value: v.over_reliance, note: 'Wrong draft remained wrong', tone: 'bg-bad-soft text-bad' },
  ]
  return (
    <div className="grid grid-cols-[88px_1fr_1fr] gap-2 p-4">
      <div />
      <div className="text-center text-[10.5px] font-bold uppercase tracking-[0.06em] text-ink-3">Final correct</div>
      <div className="text-center text-[10.5px] font-bold uppercase tracking-[0.06em] text-ink-3">Final wrong</div>
      <div className="flex items-center text-[11px] font-semibold text-ink-3">Draft correct</div>
      {cells.slice(0, 2).map((cell) => (
        <div key={cell.label} className={cn('rounded-lg border border-current/15 p-3', cell.tone)}>
          <div className="text-[22px] font-bold tabular-nums">{cell.value}</div>
          <div className="text-[11.5px] font-semibold">{cell.label}</div>
          <div className="mt-1 text-[10.5px] opacity-80">{cell.note}</div>
        </div>
      ))}
      <div className="flex items-center text-[11px] font-semibold text-ink-3">Draft wrong</div>
      {cells.slice(2).map((cell) => (
        <div key={cell.label} className={cn('rounded-lg border border-current/15 p-3', cell.tone)}>
          <div className="text-[22px] font-bold tabular-nums">{cell.value}</div>
          <div className="text-[11.5px] font-semibold">{cell.label}</div>
          <div className="mt-1 text-[10.5px] opacity-80">{cell.note}</div>
        </div>
      ))}
    </div>
  )
}

function optimisedReviewValue(data: OutcomeSuite): ReviewValueSummary {
  const rows = Object.entries(data.review_value_by_condition)
    .filter(([condition]) => condition.startsWith('optimised_'))
    .map(([, value]) => value)
  const sum = (key: 'n' | 'unscored' | 'correct_acceptance' | 'rescued' | 'over_reliance' | 'over_correction') =>
    rows.reduce((total, row) => total + row[key], 0)
  const rescued = sum('rescued')
  const overReliance = sum('over_reliance')
  const correctAcceptance = sum('correct_acceptance')
  const overCorrection = sum('over_correction')
  const wrongDrafts = rescued + overReliance
  const correctDrafts = correctAcceptance + overCorrection
  const reviewerTypes: Record<string, number> = {}
  for (const row of rows) {
    for (const [reviewer, count] of Object.entries(row.reviewer_types)) {
      reviewerTypes[reviewer] = (reviewerTypes[reviewer] ?? 0) + count
    }
  }
  return {
    n: sum('n'),
    unscored: sum('unscored'),
    correct_acceptance: correctAcceptance,
    rescued,
    over_reliance: overReliance,
    over_correction: overCorrection,
    rescue_rate: wrongDrafts ? rescued / wrongDrafts : null,
    over_reliance_rate: wrongDrafts ? overReliance / wrongDrafts : null,
    over_correction_rate: correctDrafts ? overCorrection / correctDrafts : null,
    reviewer_types: reviewerTypes,
  }
}

const SCENARIO_FAMILIES = [
  {
    key: 'ordinary',
    label: 'Ordinary',
    note: 'Routine, complete inputs',
    tiers: ['meeting', 'expense', 'clean'],
  },
  {
    key: 'ambiguous_degraded',
    label: 'Ambiguous / degraded',
    note: 'Missing, noisy or visually degraded evidence',
    tiers: ['noise', 'ambiguous', 'missing', 'skewed', 'faint', 'low_res', 'cropped'],
  },
  {
    key: 'complex_stateful',
    label: 'Pooled multi-step / revision / conflict',
    note: 'Cross-workflow diagnostic; inspect the component tiers before interpreting',
    tiers: ['multi', 'revision', 'stateful_conflict'],
  },
  {
    key: 'policy_refusal',
    label: 'Policy / refusal',
    note: 'Out-of-scope, non-receipt, limit or duplicate cases',
    tiers: ['out_of_scope', 'non_receipt', 'over_limit', 'duplicate'],
  },
] as const

function ScenarioCoverage({ data }: { data: OutcomeSuite }) {
  const summarise = (rows: OutcomeSuite['cases']) => ({
    n: rows.length,
    taskRate: rows.length ? rows.filter((row) => row.task_outcome).length / rows.length : null,
    unsafeRate: rows.length ? rows.filter((row) => row.unsafe_outcome).length / rows.length : null,
  })

  return (
    <div className="grid gap-3 p-4 md:grid-cols-2">
      {SCENARIO_FAMILIES.map((family) => {
        const rows = data.cases.filter((row) => (family.tiers as readonly string[]).includes(row.scenario_tier))
        const baseline = summarise(rows.filter((row) => row.condition.startsWith('baseline_')))
        const optimised = summarise(rows.filter((row) => row.condition.startsWith('optimised_')))
        const delta = baseline.taskRate === null || optimised.taskRate === null
          ? null
          : Math.round((optimised.taskRate - baseline.taskRate) * 100)
        const workflowCounts = WORKFLOWS.map((workflow) => ({
          workflow,
          n: rows.filter((row) => row.workflow === workflow && row.condition.startsWith('optimised_')).length,
        })).filter(({ n }) => n > 0)
        return (
          <div key={family.key} className="rounded-xl border border-line-strong bg-surface p-4 shadow-sm">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h4 className="text-[13px] font-semibold text-ink">{family.label}</h4>
                <p className="mt-0.5 text-[11px] leading-4 text-ink-3">{family.note}</p>
              </div>
              <Pill tone={delta !== null && delta > 0 ? 'ok' : 'neutral'}>
                {delta === null ? '--' : `${delta >= 0 ? '+' : ''}${delta} pp`}
              </Pill>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <div className="rounded-lg bg-surface-2 p-3">
                <div className="text-[10.5px] font-bold uppercase tracking-[0.05em] text-ink-3">Baseline task</div>
                <div className="mt-1 text-[21px] font-bold tabular-nums text-ink-2">{percentage(baseline.taskRate)}</div>
              </div>
              <div className="rounded-lg bg-accent-soft p-3">
                <div className="text-[10.5px] font-bold uppercase tracking-[0.05em] text-accent">Optimised task</div>
                <div className="mt-1 text-[21px] font-bold tabular-nums text-accent">{percentage(optimised.taskRate)}</div>
              </div>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10.5px] text-ink-3">
              <span>n={optimised.n} matched cases</span>
              <span>Optimised unsafe {percentage(optimised.unsafeRate)}</span>
              {workflowCounts.map(({ workflow, n }) => <span key={workflow}>{workflow.toUpperCase()} n={n}</span>)}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function CaseExplorer({ data }: { data: OutcomeSuite }) {
  const [selectedKey, setSelectedKey] = useState(() => {
    const first = data.cases[0]
    return first ? `${first.workflow}|${first.case_id}|${first.condition}` : ''
  })
  useEffect(() => {
    if (!data.cases.some((row) => `${row.workflow}|${row.case_id}|${row.condition}` === selectedKey)) {
      const first = data.cases[0]
      setSelectedKey(first ? `${first.workflow}|${first.case_id}|${first.condition}` : '')
    }
  }, [data, selectedKey])
  const selected = data.cases.find((row) => `${row.workflow}|${row.case_id}|${row.condition}` === selectedKey)
  const context: CaseContext | undefined = data.case_context.find(
    (row) => selected && row.case_id === selected.case_id && row.condition === selected.condition,
  )
  if (!selected) return <Empty>No case evidence available.</Empty>
  const failedChecks = [...selected.task_checks, ...selected.safety_checks].filter((check) => !check.passed)
  return (
    <div className="grid lg:grid-cols-[280px_1fr]">
      <div className="border-b border-line p-3 lg:border-b-0 lg:border-r">
        <label className="mb-2 block text-[10.5px] font-bold uppercase tracking-[0.06em] text-ink-3">Evaluation case</label>
        <select
          aria-label="Evaluation case"
          className="w-full rounded-lg border border-line-strong bg-surface px-3 py-2 text-[12px] text-ink outline-none focus:border-accent"
          value={selectedKey}
          onChange={(event) => setSelectedKey(event.target.value)}
        >
          {data.cases.map((row) => {
            const key = `${row.workflow}|${row.case_id}|${row.condition}`
            return <option key={key} value={key}>{row.workflow.toUpperCase()}  |  {row.case_id}  |  {conditionLabel(row.condition)}</option>
          })}
        </select>
        <div className="mt-3 flex flex-wrap gap-2">
          <Pill tone={selected.task_outcome ? 'ok' : 'bad'}>{selected.task_outcome ? 'task passed' : 'task failed'}</Pill>
          <Pill tone={selected.unsafe_outcome ? 'bad' : 'ok'}>{selected.unsafe_outcome ? 'unsafe' : 'safe'}</Pill>
        </div>
        <dl className="mt-4 space-y-2 text-[11.5px]">
          <div className="flex justify-between gap-3"><dt className="text-ink-3">Scenario</dt><dd className="font-medium text-ink">{selected.scenario_tier}</dd></div>
          <div className="flex justify-between gap-3"><dt className="text-ink-3">Reviewer</dt><dd className="font-medium text-ink">{context?.reviewer_type ?? '--'}</dd></div>
          <div className="flex justify-between gap-3"><dt className="text-ink-3">Mutations</dt><dd className="font-medium text-ink">{selected.mutation_ids.length}</dd></div>
          <div className="flex justify-between gap-3"><dt className="text-ink-3">Failed checks</dt><dd className={failedChecks.length ? 'font-semibold text-bad' : 'font-medium text-ok'}>{failedChecks.length}</dd></div>
        </dl>
      </div>
      <div className="min-w-0">
        <DetailSection title="1. Gold final state" open><JsonBlock value={context?.gold_final_state ?? {}} /></DetailSection>
        <DetailSection title="2. Model draft"><JsonBlock value={context?.model_draft ?? {}} /></DetailSection>
        <DetailSection title="3. Deterministic checks and review">
          <JsonBlock value={{ checks: context?.deterministic_checks, review_action: context?.review_action, draft_outcome: context?.draft_outcome }} />
        </DetailSection>
        <DetailSection title="4. Outcome and safety predicates">
          <div className="space-y-2">
            {[...selected.task_checks, ...selected.safety_checks].map((check) => (
              <div key={check.name} className={cn('rounded-lg border px-3 py-2', check.passed ? 'border-line bg-surface-2' : 'border-bad/30 bg-bad-soft')}>
                <div className="flex items-center gap-2 text-[12px] font-semibold text-ink">
                  {check.passed ? <CheckCircle2 className="size-3.5 text-ok" /> : <AlertTriangle className="size-3.5 text-bad" />}
                  {check.name.replaceAll('_', ' ')}
                </div>
                <div className="mt-0.5 pl-5 text-[11px] text-ink-3">{check.detail}</div>
              </div>
            ))}
          </div>
        </DetailSection>
        <DetailSection title="5. Final workspace state diff">
          {selected.state_diff.length ? <JsonBlock value={selected.state_diff} /> : <p className="text-[12px] text-ink-3">No workspace mutation.</p>}
        </DetailSection>
      </div>
    </div>
  )
}

export default function EvalOverview() {
  const [data, setData] = useState<OutcomeSuite | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    evalApi.formalOutcomes()
      .then((formal) => {
        if (!cancelled) setData(formal)
      })
      .catch((reason) => {
        if (!cancelled) setError((reason as Error).message)
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function runSample() {
    setBusy(true)
    setError(null)
    try {
      setData(await evalApi.replayFinalPartA())
    } catch (reason) {
      setError((reason as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const optimisedCases = useMemo(
    () => data?.cases.filter((row) => row.condition.startsWith('optimised_')) ?? [],
    [data],
  )
  const optimisedTaskRate = optimisedCases.length
    ? optimisedCases.filter((row) => row.task_outcome).length / optimisedCases.length
    : null
  const optimisedUnsafeRate = optimisedCases.length
    ? optimisedCases.filter((row) => row.unsafe_outcome).length / optimisedCases.length
    : null
  const optimisedReview = useMemo(
    () => data ? optimisedReviewValue(data) : null,
    [data],
  )
  const optimisedEffort = useMemo(() => {
    const summaries = Object.entries(data?.review_effort_by_condition ?? {})
      .filter(([condition]) => condition.startsWith('optimised_'))
      .map(([, value]) => value)
    const medians = [...new Set(summaries
      .map((summary) => summary.interactions.median)
      .filter((value): value is number => value !== null))].sort((a, b) => a - b)
    return {
      n: summaries.reduce((total, summary) => total + summary.n, 0),
      label: medians.length === 0
        ? 'Not measured'
        : medians.length === 1
          ? `${medians[0]} actions`
          : `${medians[0]}–${medians[medians.length - 1]} actions`,
    }
  }, [data])

  const summaryFor = (workflow: string, kind: 'baseline' | 'optimised') => {
    const entries = Object.entries(data?.by_workflow_condition[workflow] ?? {})
    return entries.find(([condition]) => condition.startsWith(`${kind}_`))?.[1]
  }

  return (
    <div className="flex flex-col gap-4">
      <Card className="border-line-strong">
        <div className="flex flex-wrap items-start justify-between gap-4 bg-surface-2 px-5 py-4">
          <div className="max-w-[690px]">
            <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.075em] text-accent">
              <GitCompareArrows className="size-4" /> Part A · Automated workflow outcome and safety evaluation
            </div>
            <h2 className="mt-1 text-[20px] font-[660] tracking-[-0.02em] text-ink">Did each workflow finish correctly and safely?</h2>
            <p className="mt-1 text-[12.5px] leading-5 text-ink-2">
              Part A Final uses the authoritative sealed result for each workflow: WF1/WF3 V3.4.3 and the stricter WF2 V3.5 follow-up. Versions stay explicit for provenance; all evaluation execution uses isolated mock backends.
            </p>
          </div>
          <div className="text-right">
            <Button variant="primary" onClick={runSample} disabled={busy}>
              {busy ? <><Spinner /> Running verification...</> : <><Play className="size-3.5" /> Verify Part A Final locally</>}
            </Button>
            <div className="mt-1.5 text-[10.5px] text-ink-3">verification only; never writes formal results  |  no model call</div>
          </div>
        </div>
        {error && <div className="border-t border-bad/25 bg-bad-soft px-5 py-2.5 text-[12px] text-bad">Could not run sample: {error}</div>}
      </Card>

      {!data ? (
        <Card>
          <Empty>Run the full matched evaluation to populate the four outcome questions. Existing M1-M7 pages remain available in the workflow tabs for historical analysis.</Empty>
        </Card>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <MetricCard icon={<CheckCircle2 className="size-4" />} label="Task outcome" value={percentage(optimisedTaskRate)} tone="ok" question="Did the optimised workflow reach the correct final state?" note={`n=${optimisedCases.length} optimised cases  |  final workspace state`} />
            <MetricCard icon={<ShieldCheck className="size-4" />} label="Unsafe outcome" value={percentage(optimisedUnsafeRate)} tone={optimisedUnsafeRate ? 'bad' : 'ok'} question="Did it create a harmful or unauthorised final result?" note="Lower is better  |  approval, policy, duplication and routing guards" />
          </div>

          <Card>
            <div className="grid gap-3 p-4 sm:grid-cols-2">
              <MetricCard icon={<HeartHandshake className="size-4" />} label="Secondary: scripted policy transition" value={percentage(optimisedReview?.rescue_rate)} tone="accent" question="When a draft was wrong, how often did deterministic scripted handling avoid the wrong final state?" note={`non-human analysis; no oracle field correction  |  ${optimisedReview?.rescued ?? 0} rescued`} />
              <MetricCard icon={<MousePointerClick className="size-4" />} label="Secondary: scripted transitions" value={optimisedEffort.label} question="How many deterministic transition steps ran?" note={`not review effort and not human evidence  |  n=${optimisedEffort.n}`} />
            </div>
          </Card>

          <Card>
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3.5">
              <div>
                <h3 className="text-[14px] font-[650] text-ink">Baseline to optimised task outcome</h3>
                <p className="mt-0.5 text-[11.5px] text-ink-3">Percentage-point change on identical frozen inputs. WF3 compares blind legacy approval with a gold-free deterministic policy gate; missing or wrong extracted evidence is never repaired from gold.</p>
              </div>
              <Pill tone="neutral">matched pairs</Pill>
            </div>
            {WORKFLOWS.map((workflow) => <PairBar key={workflow} workflow={workflow} baseline={summaryFor(workflow, 'baseline')} optimised={summaryFor(workflow, 'optimised')} />)}
          </Card>

          <div className="grid gap-4 xl:grid-cols-[1.12fr_0.88fr]">
            <Card>
              <div className="border-b border-line px-4 py-3.5">
                <h3 className="text-[14px] font-[650] text-ink">Scenario coverage</h3>
                <p className="mt-0.5 text-[11.5px] text-ink-3">Four interpretable risk families; all original tiers and all 223 matched cases remain. Change is shown in percentage points (pp).</p>
              </div>
              <ScenarioCoverage data={data} />
            </Card>
            <Card>
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3.5">
                <div>
                  <h3 className="text-[14px] font-[650] text-ink">Deterministic Policy-Gate Analysis</h3>
                  <p className="mt-0.5 text-[11.5px] text-ink-3">Gold-free scripted handling separating policy rescue, failed rescue and over-correction.</p>
                </div>
                <Pill tone="neutral">scripted policy</Pill>
              </div>
              {optimisedReview && <ReviewMatrix value={optimisedReview} />}
              <p className="border-t border-line bg-surface-2 px-4 py-2.5 text-[10.5px] leading-4 text-ink-3">
                These are deterministic system simulations, not human-review evidence. Human effort and behaviour are reported only in Human Evaluation V5.1.
              </p>
            </Card>
          </div>

          <Card>
            <div className="border-b border-line px-4 py-3.5">
              <h3 className="text-[14px] font-[650] text-ink">Case evidence explorer</h3>
              <p className="mt-0.5 text-[11.5px] text-ink-3">Trace one score from the gold final state through the draft, checks, review action and actual workspace mutation.</p>
            </div>
            <CaseExplorer data={data} />
          </Card>
        </>
      )}
    </div>
  )
}
