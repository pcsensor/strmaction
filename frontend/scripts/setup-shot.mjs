import { chromium } from 'playwright'
import path from 'node:path'
import fs from 'node:fs'

const BASE = 'http://127.0.0.1:8081'
const OUT = path.resolve('..', 'docs', 'screenshots')
fs.mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await context.newPage()
const errors = []
page.on('pageerror', (error) => errors.push(error.message))
page.on('console', (message) => {
  if (message.type() === 'error') errors.push(message.text())
})

await page.goto(BASE, { waitUntil: 'networkidle' })
await page.waitForTimeout(800)
await page.screenshot({ path: path.join(OUT, '11-setup-password.png') })

await page.locator('input.input').nth(0).fill('admin')
const passwordInputs = page.locator('input[type="password"]')
await passwordInputs.nth(0).fill('demo-password-123')
await passwordInputs.nth(1).fill('demo-password-123')
await page.getByRole('button', { name: '下一步' }).click()
await page.waitForTimeout(900)
await page.screenshot({ path: path.join(OUT, '12-setup-providers.png') })

await page.getByRole('button', { name: '稍后配置' }).click()
await page.waitForTimeout(700)
await page.screenshot({ path: path.join(OUT, '13-setup-library.png') })

const textInputs = page.locator('input.input')
await textInputs.nth(0).fill('电影')
await textInputs.nth(1).fill(path.resolve('..', 'sample-media', 'movies'))
await page.getByRole('button', { name: '开始扫描' }).click()
await page.waitForTimeout(3000)
await page.screenshot({ path: path.join(OUT, '14-setup-home.png') })

console.log(JSON.stringify({ url: page.url(), errors }, null, 2))
await browser.close()
