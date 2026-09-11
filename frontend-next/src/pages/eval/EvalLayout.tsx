import { Outlet } from 'react-router-dom'
import { PageHeader } from '@/components/ui'
import TabNav from '@/components/TabNav'
import { LastResultsProvider } from './parts'

// Tabs name the workspace page each evaluation covers, so the link between what the user
// operates and what the researcher measures is explicit.
const TABS = [
  { to: '/eval', label: 'Overview', end: true },
  { to: '/eval/wf1', label: 'WF1 Inbox' },
  { to: '/eval/wf2', label: 'WF2 Calendar' },
  { to: '/eval/wf3', label: 'WF3 Expenses' },
  { to: '/eval/cross', label: 'Cross-cutting' },
  { to: '/eval/human', label: 'Human Review' },
  { to: '/eval/history', label: 'Run History' },
]

export default function EvalLayout() {
  return (
    <LastResultsProvider>
      <PageHeader
        title="Evaluation"
        subtitle="Part A automated outcome and safety evaluation · Part B controlled single-reviewer evaluation."
      />
      <div className="mt-5">
        <TabNav items={TABS} />
      </div>
      <div className="mt-5">
        <Outlet />
      </div>
    </LastResultsProvider>
  )
}
