import { type ButtonHTMLAttributes, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

/* ── Button ── */
type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'md' | 'sm'
}
const BTN_VARIANT: Record<NonNullable<BtnProps['variant']>, string> = {
  primary: 'bg-accent border-accent text-accent-ink shadow-sm hover:brightness-95',
  secondary: 'bg-surface border-line-strong text-ink hover:bg-surface-2',
  ghost: 'bg-transparent border-transparent text-ink hover:bg-surface-2',
  danger: 'bg-surface border-line-strong text-bad hover:bg-bad-soft',
}
export function Button({ variant = 'secondary', size = 'md', className, ...p }: BtnProps) {
  return (
    <button
      type="button"
      className={cn(
        'inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-lg border font-medium transition-colors',
        'focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-accent-ring',
        'disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' ? 'h-[30px] px-3 text-[12.5px]' : 'h-9 px-4 text-[13.5px]',
        BTN_VARIANT[variant],
        className,
      )}
      {...p}
    />
  )
}

/* ── Card ── */
export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cn('overflow-hidden rounded-xl border border-line bg-surface shadow-sm', className)}>
      {children}
    </div>
  )
}
export function CardHeader({ title, right }: { title: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3.5">
      <h4 className="min-w-0 text-[14px] font-[640]">{title}</h4>
      {right}
    </div>
  )
}

/* ── Pill (row status) ── */
type Tone = 'ok' | 'warn' | 'bad' | 'neutral'
const PILL: Record<Tone, string> = {
  ok: 'bg-ok-soft text-ok',
  warn: 'bg-warn-soft text-warn',
  bad: 'bg-bad-soft text-bad',
  neutral: 'bg-surface-3 text-ink-2',
}
const DOT: Record<Tone, string> = { ok: 'bg-ok', warn: 'bg-warn', bad: 'bg-bad', neutral: 'bg-ink-3' }
export function Pill({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={cn(
        'inline-flex h-[23px] shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 text-[12px] font-medium',
        PILL[tone],
      )}
    >
      <span aria-hidden="true" className={cn('size-1.5 shrink-0 rounded-full', DOT[tone])} />
      {children}
    </span>
  )
}

/* ── Policy flag chip (mono) ── */
export function FlagChip({ severity, children }: { severity: 'soft' | 'hard'; children: ReactNode }) {
  return (
    <span
      className={cn(
        'inline-flex min-h-6 max-w-full items-center gap-1.5 rounded-md px-2.5 py-1 font-mono text-[12px] font-medium',
        severity === 'hard' ? 'bg-bad-soft text-bad' : 'bg-warn-soft text-warn',
      )}
    >
      {severity === 'hard' ? '⛔' : '⚠'} {children}
    </span>
  )
}

/* ── Stepper ── */
export type Step = { label: string; sub?: string; state?: 'done' | 'active' }
export function Stepper({ steps }: { steps: Step[] }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {steps.map((s, i) => (
        <div key={s.label} className="flex items-center gap-1.5">
          <div
            className={cn(
              'flex items-center gap-2 rounded-lg border px-3 py-2 text-[12.5px] font-medium',
              s.state === 'active' ? 'border-accent bg-accent-soft' : 'border-line bg-surface',
            )}
          >
            <span
              className={cn(
                'grid size-[19px] place-items-center rounded-full text-[11px] font-semibold',
                s.state === 'active' ? 'bg-accent text-accent-ink' : 'bg-surface-3 text-ink-2',
              )}
            >
              {s.state === 'done' ? '✓' : i + 1}
            </span>
            {s.label}
            {s.sub && <span className="font-normal text-ink-3">{s.sub}</span>}
          </div>
          {i < steps.length - 1 && <span className="text-ink-3">→</span>}
        </div>
      ))}
    </div>
  )
}

/* ── Spinner ── */
export function Spinner() {
  return (
    <span className="inline-block size-3.5 animate-spin rounded-full border-2 border-current border-t-transparent align-middle" />
  )
}

/* ── Budget tile (compact; sits in a responsive grid, not a full-width stack) ── */
export function BudgetTile({ label, remaining, total }: { label: string; remaining: number; total: number }) {
  const used = total - remaining
  const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0
  const fill = pct >= 100 ? 'bg-bad' : pct >= 90 ? 'bg-warn' : 'bg-accent'
  const money = (n: number) => `£${Math.round(n).toLocaleString('en-GB')}`
  return (
    <div className="rounded-lg border border-line bg-surface-2 px-3 py-2.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-[12.5px] font-medium text-ink">{label}</span>
        <span className={cn('shrink-0 text-[12.5px] font-semibold tabular-nums', pct >= 90 ? 'text-warn' : 'text-ink')}>
          {pct}%
        </span>
      </div>
      <div className="mt-1.5 h-[5px] overflow-hidden rounded-full bg-surface-3">
        <div className={cn('h-full rounded-full', fill)} style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-1.5 text-[11px] tabular-nums text-ink-3">
        {money(remaining)} of {money(total)} left
      </div>
    </div>
  )
}

/* ── Raw table shells (styled via parent) ── */
export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-5 py-8 text-center text-[13px] text-ink-3">{children}</div>
}

/* ── Segmented control (Work / Analytics on every workspace page) ── */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: string }[]
}) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-surface-2 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={cn(
            'rounded-md px-3.5 py-1.5 text-[13px] font-medium transition-colors',
            value === o.value ? 'bg-surface text-ink shadow-sm' : 'text-ink-2 hover:text-ink',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

/* ── Page header ── */
export function PageHeader({
  title,
  subtitle,
  right,
}: {
  title: string
  subtitle?: string
  right?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 className="text-[27px] font-[640] tracking-[-0.02em] text-balance">{title}</h1>
        {subtitle && <p className="mt-1 text-[13px] text-ink-3">{subtitle}</p>}
      </div>
      {right}
    </div>
  )
}
