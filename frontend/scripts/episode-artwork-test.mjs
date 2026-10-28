// 使用隔离的 API 响应验证详情图片、后台刷新及图片轮询，无需真实媒体库或 API Key。
// 启动 Vite 后运行：BASE_URL=http://127.0.0.1:4178 node scripts/episode-artwork-test.mjs
import assert from 'node:assert/strict'
import { chromium } from 'playwright'

const base = process.env.BASE_URL || 'http://127.0.0.1:4178'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await context.newPage()
page.setDefaultTimeout(10_000)
const errors = []
page.on('pageerror', (error) => errors.push(error.message))

let role = 'admin'
let available = true
let pending = false
let broken = false
let custom = false
let taskState = null
let runningPolls = 0
let taskRequests = 0

const item = (id, kind, title, extra = {}) => ({
  id, kind, title, library_id: 1, parent_id: null, original_title: null,
  year: 2023, season_no: null, episode_no: null, overview_short: '测试简介',
  rating: null, poster: null, poster_large: null, backdrop: null, backdrop_large: null,
  still: null, still_large: null, logo: null, color: null, certification: null,
  runtime_min: 45, provider: 'tmdb', provider_id: '100', match_state: 'auto', status: null,
  badges: [], progress: null, watched: false, created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z', overview: '测试简介', tagline: null, genres: [],
  cast: [], collection: null, alt_titles: [], external_ids: {}, locked_fields: [],
  trailer_key: null, air_date: null, ...extra,
})

function detail(id) {
  const series = item(1, 'series', '测试剧集', { poster_large: '/img/series.webp' })
  const seasons = [1, 2].map((n) => {
    const episodeId = n === 1 ? 3 : 5
    const episode = item(episodeId, 'episode', `第 ${n} 季单集`, {
      parent_id: n === 1 ? 2 : 4, season_no: n, episode_no: 1,
      episode_code: `S0${n}E01`,
      still: available ? `/img/episode-${episodeId}_300.webp` : null,
      still_large: available ? `/img/episode-${episodeId}_780.webp` : null,
    })
    if (broken) episode.still = episode.still_large = '/img/broken.webp'
    if (custom) {
      episode.poster_large = '/img/custom-poster.webp'
      episode.backdrop_large = '/img/custom-backdrop.webp'
      episode.locked_fields = ['poster_path', 'backdrop_path']
    }
    return { id: episode.parent_id, season_no: n, title: `第${n}季`, poster: null,
      episode_count: 1, watched_count: 0, episodes: [episode] }
  })
  const episode = seasons.flatMap((season) => season.episodes).find((e) => e.id === id)
  return {
    item: episode || series, series: episode ? series : null,
    parent: episode ? item(episode.parent_id, 'season', `第${episode.season_no}季`) : null,
    library: { id: 1, name: '测试媒体库', type: 'tv' }, ancestors: [], folders: [], videos: [],
    seasons, episodes: [], media_files: [], progress: null,
    next_episode_id: null, prev_episode_id: null, needs_attention: false,
    image_status: { pending: pending ? 1 : 0, failed: 0 },
  }
}

await context.route(`${base}/img/*`, (route) => route.request().url().endsWith('/broken.webp')
  ? route.fulfill({ status: 404, body: '' })
  : route.fulfill({ contentType: 'image/svg+xml', body:
    '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450"><rect width="800" height="450" fill="#446c96"/></svg>' }))

await context.route(`${base}/api/**`, async (route) => {
  const url = new URL(route.request().url())
  const path = url.pathname
  let data = {}
  if (path === '/api/auth/state') {
    data = { authenticated: true, needs_setup: false, user: { id: 1, username: 'test', role } }
  } else if (path === '/api/tasks') {
    taskRequests += 1
    if (taskState === 'running' && runningPolls++ > 0) {
      taskState = 'success'
      pending = true
    }
    data = { tasks: taskState ? [{ id: 11, kind: 'refresh', library_id: 1,
      status: taskState, message: '刷新', stats: {}, started_at: '2026-01-01T00:00:00Z',
      finished_at: taskState === 'success' ? '2026-01-01T00:00:01Z' : null }] : [] }
  } else if (/^\/api\/items\/\d+\/refresh$/.test(path)) {
    taskState = 'running'
    data = { task_id: 11 }
  } else if (/^\/api\/items\/\d+$/.test(path)) {
    data = detail(Number(path.split('/').pop()))
  } else if (path === '/api/libraries') {
    data = { libraries: [] }
  }
  await route.fulfill({ json: data })
})

const waitForImage = async (selector, suffix) => page.waitForFunction(
  ({ selector, suffix }) => document.querySelector(selector)?.getAttribute('src')?.endsWith(suffix),
  { selector, suffix },
)

try {
  await page.goto(`${base}/item/3`)
  await waitForImage('.poster-card img', '/episode-3_780.webp')
  assert.match(await page.locator('img[aria-hidden]').getAttribute('src'), /episode-3_780/)
  const box = await page.locator('.poster-card').boundingBox()
  assert.ok(Math.abs(box.width / box.height - 16 / 9) < 0.02)

  await page.setViewportSize({ width: 390, height: 844 })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  await page.setViewportSize({ width: 1440, height: 900 })

  custom = true
  await page.reload()
  await waitForImage('.poster-card img', '/custom-poster.webp')
  assert.match(await page.locator('img[aria-hidden]').getAttribute('src'), /custom-backdrop/)
  custom = false
  available = false
  await page.goto(`${base}/item/1`)
  await page.getByRole('button', { name: '第2季', exact: false }).click()
  await waitForImage('a[href="/item/5"] img', '/series.webp')
  await page.getByRole('button', { name: /管理/ }).click()
  await page.getByRole('button', { name: '刷新元数据', exact: true }).click()
  await page.getByRole('status').filter({ hasText: '完成后会自动更新' }).waitFor()
  available = true
  pending = false
  await waitForImage('a[href="/item/5"] img', '/episode-5_300.webp')
  assert.equal(await page.locator('a[href="/item/3"]').count(), 0, '轮询不应重置所选季')

  broken = true
  await page.evaluate(() => window.dispatchEvent(new Event('strmaction:refresh')))
  await page.waitForFunction(() => {
    const card = document.querySelector('a[href="/item/5"]')
    return card && !card.querySelector('img')
  })
  broken = false
  await page.waitForFunction(() => !document.querySelector('button[aria-label="刷新"]')?.disabled)
  await page.evaluate(() => window.dispatchEvent(new Event('strmaction:refresh')))
  await waitForImage('a[href="/item/5"] img', '/episode-5_300.webp')

  role = 'user'
  const priorTaskRequests = taskRequests
  await page.reload()
  await waitForImage('a[href="/item/3"] img', '/episode-3_300.webp')
  assert.equal(taskRequests, priorTaskRequests, '普通用户不应请求管理员任务接口')
  assert.deepEqual(errors, [])
  console.log('PASS: 单集主图和背景、横向比例、移动端布局、任务完成刷新、图片下载轮询、季选择保留、图片失败后恢复、普通用户权限')
} catch (error) {
  console.error({ errors, body: (await page.locator('body').innerText()).slice(0, 2000) })
  throw error
} finally {
  await browser.close()
}
