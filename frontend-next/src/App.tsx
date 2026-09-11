import { Routes, Route, Navigate } from 'react-router-dom'
import Sidebar from '@/components/Sidebar'
import Topbar from '@/components/Topbar'
import Overview from '@/pages/Overview'
import Expenses from '@/pages/expenses/Expenses'
import Inbox from '@/pages/inbox/InboxWorkspace'
import Calendar from '@/pages/calendar/Calendar'
import EvalLayout from '@/pages/eval/EvalLayout'
import EvalOverview from '@/pages/eval/EvalOverview'
import Wf1Eval from '@/pages/eval/Wf1Eval'
import Wf2Eval from '@/pages/eval/Wf2Eval'
import Wf3Eval from '@/pages/eval/Wf3Eval'
import CrossEval from '@/pages/eval/CrossEval'
import HumanEval from '@/pages/eval/HumanEval'
import RunHistory from '@/pages/eval/RunHistory'
import Placeholder from '@/pages/Placeholder'

export default function App() {
  return (
    <div className="flex h-full min-w-0">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <main className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1160px] px-3 pb-24 pt-5 sm:px-6 sm:py-7 md:pb-7">
            <Routes>
              <Route path="/" element={<Navigate to="/overview" replace />} />
              <Route path="/overview" element={<Overview />} />
              <Route path="/inbox" element={<Inbox />} />
              <Route path="/calendar" element={<Calendar />} />
              <Route path="/expenses" element={<Expenses />} />
              {/* one sidebar entry; the sub-views are tabs inside the section */}
              <Route path="/eval" element={<EvalLayout />}>
                <Route index element={<EvalOverview />} />
                <Route path="wf1" element={<Wf1Eval />} />
                <Route path="wf2" element={<Wf2Eval />} />
                <Route path="wf3" element={<Wf3Eval />} />
                <Route path="cross" element={<CrossEval />} />
                <Route path="human" element={<HumanEval />} />
                <Route path="history" element={<RunHistory />} />
              </Route>
              <Route path="*" element={<Placeholder title="Not found" subtitle="" />} />
            </Routes>
          </div>
        </main>
      </div>
    </div>
  )
}
