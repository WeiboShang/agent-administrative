import { NavLink } from 'react-router-dom'
import {
  LayoutGrid,
  Inbox,
  Calendar,
  ReceiptText,
  BarChart3,
  Bot,
  type LucideIcon,
} from 'lucide-react'
import { cn } from '@/lib/utils'

type Item = {
  to: string
  label: string
  icon: LucideIcon
  badge?: string
  /** 'prefix' keeps the entry active on nested routes (/eval/wf1 …). */
  match?: 'exact' | 'prefix'
}

// No badges: counts here would have to be fetched and kept in sync with every write on
// every page. A stale (or worse, hardcoded) number in the nav is a lie the user acts on —
// the live counts live on Overview and on each page's own header.
const WORKSPACE: Item[] = [
  { to: '/overview', label: 'Overview', icon: LayoutGrid },
  { to: '/inbox', label: 'Inbox', icon: Inbox },
  { to: '/calendar', label: 'Calendar', icon: Calendar },
  { to: '/expenses', label: 'Expenses', icon: ReceiptText },
]
// One entry: the per-WF views are tabs inside the section, so the rail stays calm.
const EVALUATION: Item[] = [{ to: '/eval', label: 'Evaluation', icon: BarChart3, match: 'prefix' }]

function NavItem({ item }: { item: Item }) {
  const Icon = item.icon
  return (
    <NavLink
      to={item.to}
      end={item.match !== 'prefix'}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] font-medium transition-colors',
          isActive ? 'bg-surface-3 text-ink' : 'text-ink-2 hover:bg-surface-2 hover:text-ink',
        )
      }
    >
      <Icon size={16} strokeWidth={1.6} />
      <span className="truncate">{item.label}</span>
      {item.badge && (
        <span className="ml-auto text-[11px] tabular-nums text-ink-3">{item.badge}</span>
      )}
    </NavLink>
  )
}

function MobileNavItem({ item }: { item: Item }) {
  const Icon = item.icon
  return (
    <NavLink
      to={item.to}
      end={item.match !== 'prefix'}
      className={({ isActive }) => cn(
        'flex min-w-0 flex-col items-center justify-center gap-0.5 rounded-lg px-1 py-1.5 text-[10px] font-medium',
        isActive ? 'bg-accent-soft text-accent' : 'text-ink-3',
      )}
    >
      <Icon size={17} strokeWidth={1.7} />
      <span className="max-w-full truncate">{item.label}</span>
    </NavLink>
  )
}

function Group({ label, items }: { label: string; items: Item[] }) {
  return (
    <div className="mt-1">
      <div className="px-2.5 pb-1.5 pt-3 text-[10px] font-semibold uppercase tracking-[0.1em] text-ink-3">
        {label}
      </div>
      <div className="flex flex-col gap-0.5">
        {items.map((it) => (
          <NavItem key={it.to} item={it} />
        ))}
      </div>
    </div>
  )
}

export default function Sidebar() {
  return (
    <>
      <aside className="hidden w-[184px] shrink-0 flex-col border-r border-line bg-surface px-2.5 py-3.5 md:flex">
        <div className="flex items-center gap-2.5 px-2 pb-3">
          <span className="grid size-6 place-items-center rounded-md bg-accent text-accent-ink">
            <Bot size={14} strokeWidth={2} />
          </span>
          <b className="leading-[1.12] tracking-[-0.01em] text-[13px] font-[640]">
            <span className="block">Administrative</span>
            <span className="block">Agent</span>
          </b>
        </div>
        <Group label="Workspace" items={WORKSPACE} />
        <Group label="Evaluation" items={EVALUATION} />
      </aside>
      <nav
        aria-label="Primary navigation"
        className="fixed inset-x-0 bottom-0 z-50 grid h-16 grid-cols-5 gap-1 border-t border-line bg-surface/95 px-2 py-1.5 shadow-[0_-4px_16px_rgba(0,0,0,0.06)] backdrop-blur md:hidden"
      >
        {[...WORKSPACE, ...EVALUATION].map((item) => (
          <MobileNavItem key={item.to} item={item} />
        ))}
      </nav>
    </>
  )
}
