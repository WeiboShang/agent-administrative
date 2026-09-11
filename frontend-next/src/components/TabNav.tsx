import { NavLink } from 'react-router-dom'
import { cn } from '@/lib/utils'

export type TabItem = { to: string; label: string; end?: boolean }

/** Underline tabs for sub-views inside a section (routed, so each tab is linkable). */
export default function TabNav({ items }: { items: TabItem[] }) {
  return (
    <div className="flex gap-6 overflow-x-auto border-b border-line">
      {items.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          end={t.end}
          className={({ isActive }) =>
            cn(
              '-mb-px whitespace-nowrap border-b-2 py-2.5 text-[13.5px] font-medium transition-colors',
              isActive
                ? 'border-accent text-ink'
                : 'border-transparent text-ink-3 hover:text-ink',
            )
          }
        >
          {t.label}
        </NavLink>
      ))}
    </div>
  )
}
