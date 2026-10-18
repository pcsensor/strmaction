import { chromium } from 'playwright'
import fs from 'node:fs'
import path from 'node:path'
import { execFileSync } from 'node:child_process'

const BASE = 'http://127.0.0.1:8080'
const PASSWORD = 'demo-password-123'
const OUT = path.resolve('..', 'docs', 'demo')
fs.mkdirSync(OUT, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({
  viewport: { width: 1280, height: 720 },
  recordVideo: { dir: OUT, size: { width: 1280, height: 720 } },
})
const page = await context.newPage()
const errors = []
page.on('pageerror', (error) => errors.push(error.message))
page.on('console', (message) => {
  if (message.type() === 'error') errors.push(message.text())
})

const wait = (ms) => page.waitForTimeout(ms)

await page.goto(BASE, { waitUntil: 'networkidle' })
await wait(1400)
await page.screenshot({ path: path.join(OUT, 'cover.png') })

if (await page.locator('input[autocomplete="current-password"]').count()) {
  await page.fill('input[autocomplete="username"]', 'admin')
  await page.fill('input[autocomplete="current-password"]', PASSWORD)
  await page.click('button[type="submit"]')
  await page.waitForLoadState('networkidle')
}
await wait(2200)

// 首页：悬停卡片与横向滚动
await page.mouse.wheel(0, 430)
await wait(1500)
await page.mouse.wheel(0, 520)
await wait(1600)
await page.mouse.wheel(0, -1100)
await wait(900)

// 详情页
await page.goto(`${BASE}/item/4`, { waitUntil: 'networkidle' })
await wait(2000)
await page.mouse.wheel(0, 360)
await wait(1100)
await page.mouse.wheel(0, 340)
await wait(1500)
await page.getByRole('button', { name: '管理' }).click()
await wait(1200)
await page.keyboard.press('Escape')
await page.mouse.click(20, 300)
await wait(800)
await page.getByRole('button', { name: /播放|继续播放/ }).first().click()
await wait(2200)

// 剧集详情与选集
await page.goto(`${BASE}/item/9`, { waitUntil: 'networkidle' })
await wait(2200)
await page.mouse.wheel(0, 620)
await wait(2000)
await page.mouse.wheel(0, 280)
await wait(1600)

// 搜索
await page.goto(`${BASE}/search`, { waitUntil: 'networkidle' })
await wait(800)
await page.fill('input[aria-label="搜索"]', '三体')
await wait(1700)
await page.keyboard.press('Escape')
await page.mouse.click(20, 300)
await wait(700)
await page.mouse.wheel(0, 300)
await wait(1500)

// 任务与设置
await page.goto(`${BASE}/tasks`, { waitUntil: 'networkidle' })
await wait(1800)
await page.goto(`${BASE}/settings`, { waitUntil: 'networkidle' })
await wait(1600)
await page.mouse.wheel(0, 500)
await wait(1500)
await page.mouse.wheel(0, 700)
await wait(1800)

// TV 布局
await page.goto(`${BASE}/?tv=1`, { waitUntil: 'networkidle' })
await wait(1600)
await page.keyboard.press('ArrowRight')
await wait(600)
await page.keyboard.press('ArrowRight')
await wait(600)
await page.keyboard.press('ArrowLeft')
await wait(1200)

const video = page.video()
await context.close()
await browser.close()

const recorded = await video.path()
const target = path.join(OUT, 'strmaction-demo.webm')
fs.copyFileSync(recorded, target)
console.log(JSON.stringify({ recorded, target, errors: [...new Set(errors)].slice(0, 10) }, null, 2))

const ffmpegCandidates = [
  path.join(process.env.LOCALAPPDATA || '', 'ms-playwright', 'ffmpeg-1013', 'ffmpeg-win64.exe'),
  path.join(process.env.LOCALAPPDATA || '', 'ms-playwright', 'ffmpeg-1013', 'ffmpeg'),
]
const ffmpeg = ffmpegCandidates.find((candidate) => candidate && fs.existsSync(candidate))
if (ffmpeg) {
  const mp4 = path.join(OUT, 'strmaction-demo.mp4')
  try {
    execFileSync(
      ffmpeg,
      ['-y', '-i', target, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '23', '-movflags', '+faststart', mp4],
      { stdio: 'inherit' },
    )
    console.log('mp4:', mp4)
  } catch (error) {
    console.log('mp4 conversion failed:', error.message)
  }
}
