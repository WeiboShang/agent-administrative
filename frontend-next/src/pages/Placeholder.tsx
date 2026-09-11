export default function Placeholder({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div>
      <h1 className="text-[27px] font-[640] tracking-[-0.02em] text-balance">{title}</h1>
      {subtitle && <p className="mt-1 text-[13px] text-ink-3">{subtitle}</p>}
      <div className="mt-6 rounded-xl border border-line bg-surface p-12 text-center text-[13px] text-ink-3 shadow-sm">
        Coming next in the rebuild.
      </div>
    </div>
  )
}
