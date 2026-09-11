import { type ReactNode } from 'react'
import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useThemeColors } from '@/lib/useThemeColors'
import { Empty } from '@/components/ui'

export type Bucket = { label: string; value: number }

export const pretty = (s: string) => s.replace(/_/g, ' ')

/**
 * One single-series horizontal bar chart.
 *
 * Single series ⇒ one hue and no legend (the card title names it) — which is also why no
 * categorical palette is in play here. Thin bars with 4px rounded data-ends anchored to the
 * baseline, recessive grid, direct value labels (few rows), hover tooltip.
 */
export function HBar({
  data,
  color,
  format,
  unitLabel,
}: {
  data: Bucket[]
  color: string
  format: (v: number) => string
  unitLabel: string
}) {
  const c = useThemeColors()
  if (!data.length) return <Empty>No data yet.</Empty>
  return (
    <div className="px-1 py-2">
      <ResponsiveContainer width="100%" height={data.length * 34 + 16}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 64, bottom: 4, left: 4 }} barCategoryGap={6}>
          <CartesianGrid horizontal={false} stroke={c['--line']} />
          <XAxis type="number" hide />
          <YAxis
            type="category"
            dataKey="label"
            width={124}
            axisLine={false}
            tickLine={false}
            tick={{ fill: c['--ink-3'], fontSize: 12 }}
            tickFormatter={pretty}
          />
          <Tooltip
            cursor={{ fill: c['--ink-3'], fillOpacity: 0.06 }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const p = payload[0]
              return (
                <div className="rounded-lg border border-line bg-surface px-3 py-2 text-[12.5px] shadow-md">
                  <div className="font-medium text-ink">{pretty(String(p.payload.label))}</div>
                  <div className="tabular-nums text-ink-2">
                    {format(Number(p.value))} <span className="text-ink-3">{unitLabel}</span>
                  </div>
                </div>
              )
            }}
          />
          <Bar dataKey="value" fill={color} radius={[0, 4, 4, 0]} barSize={14} isAnimationActive={false}>
            <LabelList
              dataKey="value"
              position="right"
              fill={c['--ink-2']}
              fontSize={12}
              formatter={(v: unknown) => format(Number(v))}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

/** A scalar count reads better as a tile than as a one-bar chart. */
export function StatTile({
  label,
  value,
  dot,
  note,
}: {
  label: string
  value: ReactNode
  dot: string
  note?: string
}) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4 shadow-sm">
      <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.06em] text-ink-3">
        <span className={`size-1.5 rounded-full ${dot}`} />
        {label}
      </div>
      <div className="text-[27px] font-[640] leading-none tracking-[-0.02em] tabular-nums text-ink">{value}</div>
      {note && <div className="mt-2 text-[11.5px] text-ink-3">{note}</div>}
    </div>
  )
}
