import { useState } from 'react'
import { useLocation } from 'react-router-dom'
import { Sun, Moon } from 'lucide-react'
import { type Theme, initTheme, saveTheme } from '@/lib/theme'
import { useAppData } from '@/context/AppData'

const CRUMB: Record<string, string> = {
  overview: 'Overview',
  inbox: 'Inbox',
  calendar: 'Calendar',
  expenses: 'Expenses',
  eval: 'Evaluation',
}
// Evaluation's sub-views are tabs, so the crumb names the tab — otherwise /eval/wf3 reads
// as the useless "Evaluation / Evaluation".
const EVAL_CRUMB: Record<string, string> = {
  '': 'Overview',
  wf1: 'WF1 Inbox',
  wf2: 'WF2 Calendar',
  wf3: 'WF3 Expenses',
  cross: 'Cross-cutting',
}

export default function Topbar() {
  const { pathname } = useLocation()
  const { options, actor, setActor } = useAppData()
  const segs = pathname.split('/').filter(Boolean)
  const seg = segs[0] ?? 'overview'
  const isEval = seg === 'eval'
  const group = isEval ? 'Evaluation' : 'Workspace'
  const crumb = isEval ? (EVAL_CRUMB[segs[1] ?? ''] ?? 'Overview') : (CRUMB[seg] ?? 'Workspace')
  const [theme, setTheme] = useState<Theme>(() => initTheme())

  function toggle() {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    saveTheme(next)
  }

  return (
    <header className="flex h-13 shrink-0 items-center justify-between gap-2 border-b border-line bg-surface px-3 sm:px-5">
      <div className="hidden min-w-0 truncate text-[12.5px] text-ink-3 sm:block">
        <span>{group}</span>
        <span className="px-1.5">/</span>
        <b className="font-semibold text-ink">{crumb}</b>
      </div>

      <div className="ml-auto flex min-w-0 items-center gap-2 sm:gap-3">
        {options && actor && (
          <label className="flex min-w-0 items-center gap-2 text-[11px] text-ink-3">
            <span className="hidden lg:inline">Acting as</span>
            <select
              value={actor.id}
              onChange={(e) => setActor(e.target.value)}
              className="h-8 min-w-0 max-w-[180px] rounded-lg border border-line-strong bg-surface px-2 text-[12.5px] text-ink outline-none focus:border-accent focus:ring-[3px] focus:ring-accent-ring"
            >
              {options.actors.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                  {a.is_approver ? ' · approver' : ''}
                </option>
              ))}
            </select>
          </label>
        )}
        {options?.vision_model && (
          <span className="hidden rounded-md bg-surface-3 px-2 py-1 font-mono text-[11px] text-ink-2 lg:inline">
            {options.vision_model}
          </span>
        )}
        <button
          type="button"
          onClick={toggle}
          aria-label="Toggle theme"
          className="grid size-8 place-items-center rounded-lg border border-line-strong text-ink-2 transition-colors hover:bg-surface-2"
        >
          {theme === 'dark' ? <Moon size={15} strokeWidth={1.7} /> : <Sun size={15} strokeWidth={1.7} />}
        </button>
      </div>
    </header>
  )
}
