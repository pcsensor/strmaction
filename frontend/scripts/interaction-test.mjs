import { chromium } from 'playwright'

const BASE = 'http://127.0.0.1:8080'
const PASSWORD = 'demo-password-123'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await context.newPage()
const errors = []
page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`))
page.on('console', (message) => {
  if (message.type() === 'error') errors.push(`console: ${message.text()}`)
})

const results = []
function check(name, condition, extra = '') {
  results.push({ name, ok: Boolean(condition), extra })
}

await page.goto(BASE, { waitUntil: 'networkidle' })
if (await page.locator('input[autocomplete="current-password"]').count()) {
  await page.fill('input[autocomplete="username"]', 'admin')
  await page.fill('input[autocomplete="current-password"]', PASSWORD)
  await page.click('button[type="submit"]')
  await page.waitForLoadState('networkidle')
}
await page.waitForTimeout(1200)

// 首页
check('home hero visible', await page.locator('section[aria-roledescription="carousel"] h1').first().isVisible())
check('continue row exists', await page.getByText('继续观看', { exact: true }).first().isVisible())

// 详情 + 播放
const heroTitle = (await page.locator('section[aria-roledescription="carousel"] h1').first().textContent()) || ''
await page.locator('section[aria-roledescription="carousel"]').getByRole('link', { name: '详情' }).click()
await page.waitForTimeout(1200)
const detailTitle = (await page.locator('h1').first().textContent()) || ''
check('detail title', detailTitle.includes(heroTitle.trim()), `${heroTitle} / ${detailTitle}`)
const playButton = page.locator('button', { hasText: /播放|继续播放/ }).first()
await playButton.click()
await page.waitForTimeout(1500)
const pageText = await page.locator('body').innerText()
check(
  'play feedback toast',
  ['播放地址已复制', '即将用 mpv 打开', '已交给桌面 mpv', '正在唤起播放器'].some((text) => pageText.includes(text)),
  pageText.slice(0, 80),
)

// 搜索
await page.goto(`${BASE}/search`, { waitUntil: 'networkidle' })
await page.fill('input[aria-label="搜索"]', '三体')
await page.waitForTimeout(1200)
check('search result', (await page.locator('a[aria-label="三体"]').count()) > 0)
await page.locator('a[aria-label="三体"]').first().click()
await page.waitForTimeout(1000)
check('series detail seasons', (await page.getByText('选集').count()) > 0)

// 设置
await page.goto(`${BASE}/settings`, { waitUntil: 'networkidle' })
await page.waitForTimeout(800)
check('settings library cards', (await page.getByText('立即扫描').count()) >= 4)

// TV 模式聚焦
await page.goto(`${BASE}/?tv=1`, { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)
const tv = await page.evaluate(() => document.documentElement.dataset.tv)
check('tv mode on', tv === 'true', tv)
await page.keyboard.press('ArrowRight')
await page.waitForTimeout(300)
const focused = await page.evaluate(() => document.activeElement?.textContent?.slice(0, 20) || '')
check('tv focus moves', focused.length > 0, focused)

// 退出登录
await page.goto(`${BASE}/`, { waitUntil: 'networkidle' })
await page.waitForTimeout(500)
await page.locator('button[aria-label="退出登录"]').click()
await page.waitForTimeout(1200)
check('logout shows login', (await page.locator('input[autocomplete="current-password"]').count()) > 0)

console.log(JSON.stringify({ results, errors }, null, 2))
await browser.close()
