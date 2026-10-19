import { chromium } from 'playwright'
import path from 'node:path'

const BASE = 'http://127.0.0.1:8080'
const PASSWORD = 'demo-password-123'
const OUT = path.resolve('..', 'docs', 'screenshots')
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await context.newPage()
const errors = []
page.on('pageerror', (error) => errors.push(error.message))
page.on('console', (message) => {
  if (message.type() === 'error') errors.push(message.text())
})

const results = []
const check = (name, ok, extra = '') => results.push({ name, ok: Boolean(ok), extra })

await page.goto(BASE, { waitUntil: 'networkidle' })
if (await page.locator('input[autocomplete="current-password"]').count()) {
  await page.fill('input[autocomplete="username"]', 'admin')
  await page.fill('input[autocomplete="current-password"]', PASSWORD)
  await page.click('button[type="submit"]')
  await page.waitForLoadState('networkidle')
}
await page.waitForTimeout(1000)

// 自动连播：找一部有至少两集的剧
const data = await page.evaluate(async () => {
  const list = await fetch('/api/items?kind=series&page_size=50').then((r) => r.json())
  for (const item of list.items) {
    const detail = await fetch(`/api/items/${item.id}`).then((r) => r.json())
    const episodes = detail.seasons.flatMap((season) => season.episodes)
    if (episodes.length >= 2) {
      return { series: item, first: episodes[0], second: episodes[1] }
    }
  }
  return null
})
check('series with 2 episodes', data !== null)
if (data) {
  await page.goto(`${BASE}/item/${data.first.id}`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(800)
  await page.evaluate(
    ([episodeId]) => window.StrmActionNextEpisode?.(episodeId, true),
    [data.first.id],
  )
  await page.waitForTimeout(900)
  const overlay = await page.getByText('自动连播').count()
  check('auto-next overlay', overlay > 0)
  await page.screenshot({ path: path.join(OUT, '15-auto-next.png') })
  if (overlay > 0) {
    await page.locator('button[aria-label="取消"]').first().click()
    await page.waitForTimeout(500)
    check('auto-next cancel', (await page.getByText('自动连播').count()) === 0)
  }
}

// 恢复自动刮削
await page.goto(`${BASE}/item/4`, { waitUntil: 'networkidle' })
await page.waitForTimeout(900)
const lockedBefore = await page.getByText(/已锁定/).count()
await page.getByRole('button', { name: '管理' }).click()
const restore = await page.getByRole('button', { name: '恢复自动刮削' }).count()
check('restore auto menu', restore > 0, `locked=${lockedBefore}`)
if (restore > 0) {
  await page.getByRole('button', { name: '恢复自动刮削' }).click()
  await page.waitForTimeout(1500)
  const lockedAfter = await page.getByText(/已锁定/).count()
  check('restore auto clears locks', lockedAfter === 0, `before=${lockedBefore} after=${lockedAfter}`)
}

console.log(JSON.stringify({ results, errors }, null, 2))
await browser.close()
