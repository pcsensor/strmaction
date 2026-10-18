import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'

const BASE = process.env.BASE_URL || 'http://127.0.0.1:8080'
const PASSWORD = process.env.DEMO_PASSWORD || 'demo-password-123'
const OUT = path.resolve('..', 'docs', 'screenshots')
fs.mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const errors = []

async function newPage(viewport) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 })
  const page = await context.newPage()
  page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`))
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(`console: ${message.text()}`)
  })
  page.on('requestfailed', (request) => {
    const url = request.url()
    if (!url.includes('example.com')) errors.push(`requestfailed: ${url} ${request.failure()?.errorText}`)
  })
  return { context, page }
}

async function login(page) {
  await page.goto(BASE, { waitUntil: 'networkidle' })
  if (await page.locator('input[autocomplete="current-password"]').count()) {
    await page.fill('input[autocomplete="username"]', 'admin')
    await page.fill('input[autocomplete="current-password"]', PASSWORD)
    await page.click('button[type="submit"]')
    await page.waitForLoadState('networkidle')
  }
  await page.waitForTimeout(1200)
}

const desktop = await newPage({ width: 1440, height: 900 })
await desktop.page.goto(BASE, { waitUntil: 'networkidle' })
await desktop.page.waitForTimeout(800)
await desktop.page.screenshot({ path: path.join(OUT, '01-login.png'), fullPage: false })
await login(desktop.page)
await desktop.page.waitForTimeout(1500)
await desktop.page.screenshot({ path: path.join(OUT, '02-home.png'), fullPage: false })

await desktop.page.goto(`${BASE}/item/4`, { waitUntil: 'networkidle' })
await desktop.page.waitForTimeout(1200)
await desktop.page.screenshot({ path: path.join(OUT, '03-detail.png'), fullPage: true })

await desktop.page.goto(`${BASE}/search`, { waitUntil: 'networkidle' })
await desktop.page.waitForTimeout(900)
await desktop.page.screenshot({ path: path.join(OUT, '04-search.png'), fullPage: false })

await desktop.page.goto(`${BASE}/settings`, { waitUntil: 'networkidle' })
await desktop.page.waitForTimeout(900)
await desktop.page.screenshot({ path: path.join(OUT, '05-settings.png'), fullPage: false })

await desktop.page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' })
await desktop.page.waitForTimeout(900)
await desktop.page.screenshot({ path: path.join(OUT, '06-tasks.png'), fullPage: false })

await desktop.page.goto(`${BASE}/fix`, { waitUntil: 'networkidle' })
await desktop.page.waitForTimeout(900)
await desktop.page.screenshot({ path: path.join(OUT, '07-fix.png'), fullPage: false })

const tv = await newPage({ width: 1920, height: 1080 })
await login(tv.page)
await tv.page.goto(`${BASE}/?tv=1`, { waitUntil: 'networkidle' })
await tv.page.waitForTimeout(1500)
await tv.page.screenshot({ path: path.join(OUT, '08-tv.png'), fullPage: false })

const mobile = await newPage({ width: 390, height: 844 })
await login(mobile.page)
await mobile.page.waitForTimeout(1200)
await mobile.page.screenshot({ path: path.join(OUT, '09-mobile-home.png'), fullPage: false })
await mobile.page.goto(`${BASE}/item/9`, { waitUntil: 'networkidle' })
await mobile.page.waitForTimeout(1000)
await mobile.page.screenshot({ path: path.join(OUT, '10-mobile-detail.png'), fullPage: false })

await browser.close()
console.log(JSON.stringify({ errors: [...new Set(errors)].slice(0, 40) }, null, 2))
