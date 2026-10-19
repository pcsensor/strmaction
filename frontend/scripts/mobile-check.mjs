/**
 * v0.8 手机端检查：
 * - 伴侣 App 的 UA 不再触发 TV 布局
 * - 触摸手势能正常纵向滚动（首页 / 详情 / 设置）
 * - ?tv=1 仍然进入 TV 布局
 */
import { chromium, devices } from 'playwright'

const BASE = process.env.BASE_URL || 'http://127.0.0.1:8080'
const PASSWORD = process.env.DEMO_PASSWORD || 'demo-password-123'

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const errors = []
const phone = devices['Pixel 7']

const context = await browser.newContext({
  ...phone,
  userAgent: `${phone.userAgent} StrmActionCompanion/1.1`,
})
const page = await context.newPage()
page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`))
page.on('console', (message) => {
  if (message.type() === 'error') errors.push(`console: ${message.text()}`)
})

async function login() {
  await page.goto(BASE, { waitUntil: 'networkidle' })
  if (await page.locator('input[autocomplete="current-password"]').count()) {
    await page.fill('input[autocomplete="username"]', 'admin')
    await page.fill('input[autocomplete="current-password"]', PASSWORD)
    await page.click('button[type="submit"]')
    await page.waitForLoadState('networkidle')
  }
  await page.waitForTimeout(1200)
}

const cdp = await context.newCDPSession(page)

async function swipeUp() {
  const startY = 700
  const steps = 8
  await cdp.send('Input.dispatchTouchEvent', {
    type: 'touchStart',
    touchPoints: [{ x: 190, y: startY }],
  })
  for (let i = 1; i <= steps; i += 1) {
    await cdp.send('Input.dispatchTouchEvent', {
      type: 'touchMove',
      touchPoints: [{ x: 190, y: startY - i * 55 }],
    })
  }
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
  await page.waitForTimeout(900)
}

await login()

const tvFlag = await page.evaluate(() => document.documentElement.dataset.tv)
const home = await page.evaluate(() => ({
  scrollHeight: document.scrollingElement.scrollHeight,
  innerHeight: window.innerHeight,
  width: window.innerWidth,
}))
await page.screenshot({ path: '../docs/screenshots/16-mobile-home.png', fullPage: false })
await swipeUp()
const homeY = await page.evaluate(() => window.scrollY)

await page.goto(`${BASE}/item/4`, { waitUntil: 'networkidle' })
await page.waitForTimeout(900)
await page.screenshot({ path: '../docs/screenshots/17-mobile-detail.png', fullPage: false })
const detailBefore = await page.evaluate(() => window.scrollY)
await swipeUp()
const detailY = await page.evaluate(() => window.scrollY)

await page.goto(`${BASE}/settings`, { waitUntil: 'networkidle' })
await page.waitForTimeout(900)
await page.screenshot({ path: '../docs/screenshots/18-mobile-settings.png', fullPage: false })
await swipeUp()
const settingsY = await page.evaluate(() => window.scrollY)

// TV 布局：?tv=1
await page.goto(`${BASE}/?tv=1`, { waitUntil: 'networkidle' })
await page.waitForTimeout(800)
const tvMode = await page.evaluate(() => document.documentElement.dataset.tv)

console.log(
  JSON.stringify(
    {
      tvFlag,
      home,
      homeY,
      detailBefore,
      detailY,
      settingsY,
      tvMode,
      errors,
    },
    null,
    2,
  ),
)

const checks = [
  ['手机进入非 TV 布局', tvFlag === 'false'],
  ['首页内容高于视口', home.scrollHeight > home.innerHeight + 200],
  ['首页触摸可滚动', homeY > 80],
  ['详情页触摸可滚动', detailY > detailBefore + 80],
  ['设置页触摸可滚动', settingsY > 80],
  ['?tv=1 进入 TV 布局', tvMode === 'true'],
  ['无前端错误', errors.length === 0],
]

let failed = 0
for (const [name, ok] of checks) {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}`)
  if (!ok) failed += 1
}
await browser.close()
process.exit(failed ? 1 : 0)
