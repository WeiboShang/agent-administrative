/** Browser interaction preflight for the WF2 controls most likely to regress.
 *
 * Run against an isolated mock-backed server, never the Google-configured live workspace:
 *   BASE=http://127.0.0.1:8765 node preflight.mjs
 */
import { chromium } from 'playwright'

const BASE = process.env.BASE ?? 'http://127.0.0.1:8765'
const day = (offset) => {
  const value = new Date()
  value.setDate(value.getDate() + offset)
  return value.toISOString().slice(0, 10)
}

const browser = await chromium.launch({ args: ['--no-sandbox', '--disable-dev-shm-usage'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const errors = []
page.on('console', (message) => {
  if (message.type() === 'error') errors.push(`console: ${message.text()}`)
})
page.on('pageerror', (error) => errors.push(`page: ${error.message}`))
page.on('requestfailed', (request) => {
  if (request.failure()?.errorText !== 'net::ERR_ABORTED') {
    errors.push(`request: ${request.url()} ${request.failure()?.errorText}`)
  }
})

try {
  await page.goto(`${BASE}/calendar`, { waitUntil: 'domcontentloaded' })
  await page.getByText('Smart Schedule', { exact: true }).waitFor()

  await page.getByLabel('Meeting title').fill('Browser preflight')
  await page.getByText('Select participants…', { exact: true }).click()
  await page.getByRole('checkbox', { name: 'Chen Wei', exact: true }).check()
  await page.getByLabel('Meeting date').fill(day(35))
  await page.getByLabel('Optional exact time').fill('10:00')
  await page.getByLabel('Duration (minutes)').fill('60')
  await page.getByRole('button', { name: 'Find options' }).click()
  await page.getByRole('button', { name: /recommended/i }).click()
  await page.getByRole('button', { name: 'Approve create →' }).click()
  await page.getByText(/Booked evt-/).waitFor()

  await page.getByLabel('Operation').selectOption('RESCHEDULE')
  const target = page.getByLabel('Existing event')
  const targetValue = await target.locator('option', { hasText: 'Browser preflight' }).first().getAttribute('value')
  if (!targetValue) throw new Error('Created event did not appear in the existing-event picker')
  await target.selectOption(targetValue)
  if (await page.getByLabel('Duration (minutes)').inputValue() !== '60') {
    throw new Error('Existing event duration was not restored')
  }
  const participantSummary = page.locator('summary').filter({ hasText: 'Chen Wei' })
  if (await participantSummary.count() !== 1) {
    throw new Error('Existing participants were not restored')
  }
  await page.getByLabel('Meeting date').fill(day(36))
  await page.getByRole('button', { name: 'Find options' }).click()
  await page.getByRole('button', { name: /recommended/i }).click()
  await page.getByRole('button', { name: 'Approve reschedule →' }).click()
  await page.getByText('reschedule', { exact: true }).waitFor()

  await page.getByLabel('Operation').selectOption('CANCEL')
  await page.getByRole('button', { name: 'Review cancellation' }).click()
  await page.getByRole('button', { name: 'Approve cancel →' }).click()
  await page.getByText('cancelled', { exact: true }).waitFor()

  await page.screenshot({ path: '/tmp/wf-smoke/interaction_preflight.png', fullPage: true })
  if (errors.length) throw new Error(errors.join('\n'))
  console.log('PASS  browser interaction: create → reschedule → cancel')
} catch (error) {
  console.error(`FAIL  ${error.stack ?? error}`)
  process.exitCode = 1
} finally {
  await browser.close()
}
