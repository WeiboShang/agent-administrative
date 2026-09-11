import { Suspense, lazy, useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Card, CardHeader, PageHeader, Pill, Segmented } from '@/components/ui'
import { api, type RoutedDraft } from '@/lib/api'
import { useAppData } from '@/context/AppData'
import UploadReview from './UploadReview'
import ApproverQueue from './ApproverQueue'
import EmployeeRevisions from './EmployeeRevisions'
import Ledger from './Ledger'

// Charts pull in Recharts (~360 kB); the Work tab must not pay for it.
const Analytics = lazy(() => import('./Analytics'))

type Tab = 'work' | 'analytics'

export default function Expenses() {
  const { loading, error } = useAppData()
  const [tab, setTab] = useState<Tab>('work')
  // bumped after any write (submit / decide) so the queue and ledger re-fetch
  const [tick, setTick] = useState(0)
  const [routedDrafts, setRoutedDrafts] = useState<RoutedDraft[]>([])
  const [searchParams] = useSearchParams()
  const requestedDraft = searchParams.get('draft')
  const bump = useCallback(() => setTick((t) => t + 1), [])

  useEffect(() => {
    api.routedExpenseDrafts().then((result) => setRoutedDrafts(result.items)).catch(() => setRoutedDrafts([]))
  }, [tick])

  return (
    <div>
      <PageHeader
        title="Expense reimbursement"
        subtitle="Agent reads the receipt · you verify against the image · code posts &amp; deducts budget."
        right={
          <Segmented
            value={tab}
            onChange={setTab}
            options={[
              { value: 'work', label: 'Work' },
              { value: 'analytics', label: 'Analytics' },
            ]}
          />
        }
      />

      {error && (
        <div className="mt-6 rounded-lg border border-bad bg-bad-soft px-4 py-3 text-[13px] text-bad">
          Could not reach the backend ({error}). Start it with{' '}
          <code>.venv/bin/uvicorn backend.main:app --port 8000</code>.
        </div>
      )}

      {loading && !error && <div className="mt-6 text-[13px] text-ink-3">Loading options…</div>}

      {!loading && !error && (
        <div className="mt-6">
          {tab === 'work' ? (
            <div className="flex flex-col gap-4">
              {routedDrafts.length > 0 && (
                <Card>
                  <CardHeader title="Routed expense drafts" right={<Pill tone="warn">{routedDrafts.length} awaiting evidence</Pill>} />
                  <div className="divide-y divide-line">
                    {routedDrafts.map((draft) => (
                      <div key={draft.id} className={`flex flex-wrap items-center justify-between gap-2 px-4 py-3 ${requestedDraft === draft.id ? 'bg-accent-soft' : ''}`}>
                        <div><div className="font-mono text-[12px] font-semibold text-ink">{draft.id}</div><div className="mt-0.5 text-[12px] text-ink-3">{draft.title ?? 'Expense draft'} · {draft.status} · {draft.evidence_refs?.length ?? 0} evidence reference(s)</div></div>
                        <Link to={draft.origin?.source_path ?? '/inbox'} className="text-[12px] font-medium text-accent hover:underline">View source thread →</Link>
                      </div>
                    ))}
                  </div>
                </Card>
              )}
              <UploadReview onSubmitted={bump} />
              <EmployeeRevisions tick={tick} reload={bump} />
              <ApproverQueue tick={tick} reload={bump} />
              <Ledger tick={tick} />
            </div>
          ) : (
            <Suspense
              fallback={
                <div className="rounded-xl border border-line bg-surface p-12 text-center text-[13px] text-ink-3 shadow-sm">
                  Loading charts…
                </div>
              }
            >
              <Analytics tick={tick} />
            </Suspense>
          )}
        </div>
      )}
    </div>
  )
}
