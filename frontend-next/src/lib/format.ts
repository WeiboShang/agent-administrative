// Money + date helpers ported from the vanilla build. The receipt's own amount+currency is
// what the human verifies against the image, so it is shown as-is; GBP is derived and shown
// beside it only where values are summed or compared.

const CUR_SYMBOL: Record<string, string> = {
  GBP: '£', USD: '$', EUR: '€', JPY: '¥', CNY: '¥',
  HKD: 'HK$', AUD: 'A$', CAD: 'C$', CHF: 'CHF ', SGD: 'S$',
}
const NO_MINOR_UNIT = new Set(['JPY', 'IDR'])

export function fmtMoney(amount: number | string | null | undefined, currency?: string | null): string {
  if (amount === null || amount === undefined || amount === '') return '—'
  const cur = (currency || 'GBP').toUpperCase()
  const dp = NO_MINOR_UNIT.has(cur) ? 0 : 2
  const n = Number(amount).toLocaleString('en-GB', { minimumFractionDigits: dp, maximumFractionDigits: dp })
  return (CUR_SYMBOL[cur] || cur + ' ') + n
}

export function fmtGBP(x: number | null | undefined): string {
  return x === null || x === undefined ? '—' : fmtMoney(x, 'GBP')
}

/** Live GBP conversion for the review form; rates come from /options so the UI can't drift. */
export function toGBP(
  amount: number | string,
  currency: string | null | undefined,
  fxRates: Record<string, number>,
): number | null {
  const r = fxRates[(currency || 'GBP').toUpperCase()]
  const n = Number(String(amount).trim())
  return r === undefined || !Number.isFinite(n) ? null : Math.round(n * r * 100) / 100
}

export const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/

/** True only for a real calendar date written exactly as YYYY-MM-DD. */
export function isIsoDate(value: string): boolean {
  if (!ISO_DATE.test(value)) return false
  const [year, month, day] = value.split('-').map(Number)
  const parsed = new Date(year, month - 1, day)
  return parsed.getFullYear() === year
    && parsed.getMonth() === month - 1
    && parsed.getDate() === day
}

export function labelOf(k: string): string {
  const s = k.replace(/_/g, ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}
