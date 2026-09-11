/**
 * Headless smoke test — the check that the type-checker and the build cannot do:
 * does the app actually MOUNT and RENDER against the live backend, without console
 * errors or failed requests, in both themes?
 *
 *   LD_LIBRARY_PATH=/tmp/chromedeps/root/usr/lib/x86_64-linux-gnu node smoke.mjs
 */
import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'

const BASE = process.env.BASE ?? 'http://127.0.0.1:8000'
const OUT = '/tmp/wf-smoke'
mkdirSync(OUT, { recursive: true })

// route → a selector/text that only appears if that page really rendered
const ROUTES = [
  ['/overview', 'text=Open threads'],
  ['/inbox', 'text=Threads'],
  ['/calendar', 'text=Extract meeting'],
  ['/expenses', 'text=Read receipt'],
  ['/eval', 'text=Did each workflow finish correctly and safely?'],
  ['/eval/wf1', 'text=Action detection'],
  ['/eval/wf2', 'text=Scheduling accuracy'],
  ['/eval/wf3', 'text=Receipt extraction'],
  ['/eval/cross', 'text=scripted reviewers'],
]

const browser = await chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] })
let failures = 0

// Desktop is the presentation target; compact and phone widths catch the fixed-width
// controls/cards that previously overlapped even though the production build succeeded.
const MODES = [
  { name: 'light', theme: 'light', viewport: { width: 1440, height: 900 }, screenshots: true },
  { name: 'dark', theme: 'dark', viewport: { width: 1440, height: 900 }, screenshots: false },
  { name: 'compact', theme: 'light', viewport: { width: 1024, height: 768 }, screenshots: false },
  { name: 'phone', theme: 'light', viewport: { width: 390, height: 844 }, screenshots: true },
]
const requestedModes = new Set((process.env.MODES ?? '').split(',').filter(Boolean))
const activeModes = requestedModes.size
  ? MODES.filter((mode) => requestedModes.has(mode.name))
  : MODES

for (const mode of activeModes) {
  const ctx = await browser.newContext({
    viewport: mode.viewport,
    colorScheme: mode.theme,
  })
  const page = await ctx.newPage()
  for (const [route, probe] of ROUTES) {
    const errors = []
    const onConsole = (m) => m.type() === 'error' && errors.push(m.text().slice(0, 160))
    const onPageError = (e) => errors.push('PAGEERROR ' + e.message.slice(0, 160))
    // SPA navigation legitimately aborts requests owned by the page being left. That is not
    // a backend failure; every other network failure remains fatal.
    const onRequestFailed = (r) => {
      if (r.failure()?.errorText !== 'net::ERR_ABORTED') {
        errors.push('REQFAIL ' + r.url().slice(-60))
      }
    }
    page.on('console', onConsole)
    page.on('pageerror', onPageError)
    page.on('requestfailed', onRequestFailed)

    let rendered = false
    try {
      await page.goto(BASE + route, { waitUntil: 'domcontentloaded', timeout: 12000 })
      await page.waitForSelector(probe, { timeout: 8000 })
      rendered = true
    } catch (e) {
      errors.push('PROBE MISS: ' + String(e).split('\n')[0].slice(0, 120))
    }

    // horizontal overflow = a layout bug the build can never catch
    const overflow = await page.evaluate(() =>
      Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)
      - document.documentElement.clientWidth,
    )
    if (overflow > 0) errors.push(`H-OVERFLOW ${overflow}px`)

    const name = route.replace(/\//g, '_') || '_root'
    if (mode.screenshots) {
      await page.screenshot({ path: `${OUT}/${mode.name}_${name}.png`, fullPage: true })
    }

    const ok = rendered && errors.length === 0
    if (!ok) failures++
    console.log(
      `${ok ? 'PASS' : 'FAIL'}  ${mode.name.padEnd(7)} ${route.padEnd(14)}` +
        (errors.length ? ' :: ' + errors.slice(0, 3).join(' | ') : ''),
    )
    page.off('console', onConsole)
    page.off('pageerror', onPageError)
    page.off('requestfailed', onRequestFailed)
  }
  await page.close()
  await ctx.close()
}

// Analytics tabs are behind a click — the charts never mount until then.
if (process.env.SKIP_CHARTS !== '1') {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  for (const [route, tabLabel, chartProbe] of [
    ['/inbox', 'Analysis', 'text=Work-queue funnel'],
    ['/calendar', 'Analytics', 'text=Booking density'],
    ['/expenses', 'Analytics', 'text=Spend by category'],
  ]) {
    const page = await ctx.newPage()
    const errors = []
    page.on('console', (m) => m.type() === 'error' && errors.push(m.text().slice(0, 160)))
    page.on('pageerror', (e) => errors.push('PAGEERROR ' + e.message.slice(0, 160)))
    let ok = false
    try {
      await page.goto(BASE + route, { waitUntil: 'domcontentloaded', timeout: 12000 })
      await page.getByRole('button', { name: tabLabel, exact: true }).click()
      await page.waitForSelector(chartProbe, { timeout: 10000 })
      // a chart that mounts but has zero height renders nothing — check real geometry
      const svgH = await page.evaluate(() => {
        const s = document.querySelector('svg.recharts-surface')
        return s ? s.getBoundingClientRect().height : -1
      })
      if (svgH <= 0) errors.push(`CHART HEIGHT ${svgH}`)
      ok = errors.length === 0
      await page.screenshot({ path: `${OUT}/${route.replace(/\//g, '_')}_analytics.png`, fullPage: true })
    } catch (e) {
      errors.push('MISS: ' + String(e).split('\n')[0].slice(0, 120))
    }
    if (!ok) failures++
    console.log(`${ok ? 'PASS' : 'FAIL'}  tab   ${route}/analytics` + (errors.length ? ' :: ' + errors.slice(0, 2).join(' | ') : ''))
    await page.close()
  }
  await ctx.close()
}
await browser.close()

console.log(failures === 0 ? '\nALL PASS' : `\n${failures} FAILURE(S)`)
process.exit(failures === 0 ? 0 : 1)
