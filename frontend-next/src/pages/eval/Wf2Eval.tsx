import { evalApi } from '@/lib/api'
import { EvalRunner, Rate, Table, TierTable, num } from './parts'

const TIER_ORDER = [
  'clean', 'missing', 'ambiguous', 'noise', 'revision', 'stateful_conflict', 'out_of_scope',
]

export default function Wf2Eval() {
  return (
    <div className="flex flex-col gap-4">
      <p className="text-[13px] text-ink-3">
        Slot extraction, people resolution, stateful conflict detection, and abstention.
      </p>

      <EvalRunner
        name="scheduling"
        title="Scheduling accuracy — date · time · participants · missing · conflict · abstain"
        measures="Whether the LLM's slot extraction plus the deterministic validator produce the right meeting: the resolved date and time, the resolved participants, the missing-field detection, the stateful conflict check, and correct abstention on out-of-scope requests."
        method="Synthetic requests per difficulty tier, gold by construction. `stateful_conflict` is the tier that needs the live calendar — a stateless extractor cannot pass it. `out_of_scope` is the abstention test."
        cost="~30s"
        run={() => evalApi.scheduling(4)}
        render={(r) => (
          <TierTable
            data={(r.scheduling ?? {}) as Record<string, Record<string, unknown>>}
            order={TIER_ORDER}
            cols={[
              ['date_correct', 'Date'],
              ['time_correct', 'Time'],
              ['participants_correct', 'People'],
              ['missing_detected', 'Missing'],
              ['conflict_correct', 'Conflict'],
              ['correct_abstain', 'Abstain'],
            ]}
          />
        )}
      />

      <EvalRunner
        name="date_resolution"
        title="Date resolution against hand-authored gold"
        measures="Whether the deterministic resolver reads English date expressions the way a speaker means them: exact resolution, refusing to invent a vague date, and flagging genuinely ambiguous ones."
        method="Every expectation in this suite is written by hand from the English meaning. The scheduling generator, by contrast, builds its gold with resolve_relative_date itself — so its date_correct can only fail if the LLM mangles a phrase it was told to copy, and cannot detect a wrong convention. Deterministic: no model call, no quota."
        cost="instant"
        run={() => evalApi.dateResolution()}
        render={(r) => {
          const d = (r.date_resolution ?? {}) as Record<string, unknown>
          const failures = (d.failures ?? []) as Record<string, unknown>[]
          return (
            <div>
              <Table
                head={['Behaviour', 'Rate']}
                rows={[
                  ['exact resolution', <Rate key="a" v={d.exact} />],
                  ['refuses to invent a vague date', <Rate key="b" v={d.must_not_resolve} />],
                  ['flags an ambiguous "next <weekday>"', <Rate key="c" v={d.ambiguity_flagged} />],
                  [<b key="t">overall (n={num(d.n)})</b>, <Rate key="d" v={d.accuracy} />],
                ]}
              />
              {failures.length > 0 && (
                <div className="mx-4 my-4 rounded-lg border border-bad bg-bad-soft px-3.5 py-3 text-[12.5px] text-bad">
                  <b>{failures.length} case(s) failing:</b>{' '}
                  {failures.map((f) => `${f.expr} → ${f.got} (wanted ${f.expected})`).join(' · ')}
                </div>
              )}
              <div className="mx-4 my-4 rounded-lg border border-accent bg-accent-soft px-3.5 py-3 text-[12.5px] text-ink-2">
                <b className="text-ink">Why a separate suite.</b> "next Friday" said on a
                Thursday resolved to <b>tomorrow</b> — a reading almost nobody intends. The
                generator could never surface that, because it computes its own gold with the
                function being tested. Ambiguous expressions are now proposed <i>and</i>{' '}
                flagged, so the human confirms which week was meant.
              </div>
            </div>
          )
        }}
      />
    </div>
  )
}
