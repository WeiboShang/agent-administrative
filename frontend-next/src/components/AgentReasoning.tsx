import type { ReactNode } from 'react'
import { Brain, ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'

// Shared across workflows so the framing and the column labels stay identical everywhere
// this appears (WF2 scheduling, WF3 expense). The story is always the same: what the model
// read from the source (text or receipt image) → what deterministic code resolved & checked
// it into (docs/workflow_design.md). Keep the two labels here the single source of truth — don't
// re-spell them per page.
const GRID = 'grid grid-cols-[64px_minmax(90px,auto)_20px_1fr] gap-x-3'

/** One reasoning row: label · what the model read · → · what the code resolved it to. */
export function Trace({
  label,
  read,
  resolved,
  bad,
}: {
  label: string
  read?: ReactNode
  resolved?: ReactNode
  bad?: boolean
}) {
  return (
    <div className={cn(GRID, 'items-baseline text-[12.5px]')}>
      <span className="text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-3">{label}</span>
      <span className="break-words text-ink-2">{read || '—'}</span>
      <span className="text-ink-3">→</span>
      <span className={cn('break-words font-medium', bad ? 'text-bad' : 'text-ink')}>
        {resolved || '—'}
      </span>
    </div>
  )
}

/**
 * Folded "Agent reasoning" panel — the LLM-proposes-vs-code-resolves transparency, on demand
 * (for the write-up / debugging) without cluttering the form the human actually edits. Pass
 * `<Trace>` rows as children.
 */
export function AgentReasoning({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <details className={cn('group rounded-lg border border-line bg-surface-2', className)}>
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3.5 py-2.5 text-[12.5px] font-medium text-ink-2">
        <Brain size={14} strokeWidth={1.6} />
        Agent reasoning
        <span className="font-normal text-ink-3">— what the model read vs what the code resolved</span>
        <ChevronDown size={14} className="ml-auto transition-transform group-open:rotate-180" />
      </summary>
      {/* cap the list to a comfortable reading width — the transformation table reads as a
          deliberate left-aligned block instead of stretching sparsely across a full-width card */}
      <div className="flex max-w-2xl flex-col gap-2 border-t border-line p-3.5">
        <div
          className={cn(
            GRID,
            'items-center text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-3',
          )}
        >
          <span />
          <span>Model read</span>
          <span />
          <span>Code resolved</span>
        </div>
        {children}
      </div>
    </details>
  )
}
