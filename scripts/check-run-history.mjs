/** 接续历史/去重/缺失/循环与真实旧JSONL回放；只读GET，0次模型调用。 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import os from 'node:os'
const root = path.resolve(import.meta.dirname, '..')
const require = createRequire(path.join(root, 'apps/web/package.json'))
const { createServer } = await import(pathToFileURL(require.resolve('vite')).href)
const vite = await createServer({ root: path.join(root, 'apps/web'), server: { middlewareMode: true }, appType: 'custom' })
let loadAncestors, activityTotals, activityJobSchema, timeline
try {
  ;({ loadAncestors, activityTotals } = await vite.ssrLoadModule('/src/features/research-lab/activityHistory.ts'))
  ;({ activityJobSchema } = await vite.ssrLoadModule('/src/api/researchSchemas.ts'))
  ;({ timeline } = await vite.ssrLoadModule('/src/features/research-lab/ActivityPanel.tsx'))
  const id = (n) => `00000000-0000-0000-0000-${String(n).padStart(12, '0')}`
  const run = (n, parent, calls) => ({ taskId: id(n), parentTaskId: parent ? id(parent) : null, status: 'completed',
    target: '夹具', progress: '完成', modelCalls: calls, usage: { total_tokens: calls * 100 }, events: [] })
  const first = run(1, null, 5), second = run(2, 1, 3), last = run(3, 2, 1)
  const reader = async key => ({ [id(1)]: first, [id(2)]: second }[key])
  const history = await loadAncestors(last, reader)
  assert.deepEqual(history.runs.map(r => r.taskId), [id(1), id(2)])
  assert.equal(activityTotals([...history.runs, last, last]).calls, 9)
  assert.equal(activityTotals([...history.runs, last]).usage.total_tokens, 900)
  const broken = await loadAncestors(last, async () => { throw new Error('missing') })
  assert.ok(broken.warning); assert.equal(broken.runs.length, 0)
  const cyclic = await loadAncestors(last, async () => run(2, 3, 3))
  assert.ok(cyclic.warning); assert.equal(cyclic.runs.length, 1)
  const models = timeline(['决定下一步', '阅读原文'].flatMap((purpose, i) => [
    { id: `s${i}`, type: 'model_started', modelCall: i+1, purpose },
    { id: `e${i}`, type: 'model_finished', modelCall: i+1, usage: { total_tokens: 10 } },
  ]))
  assert.equal(models.length, 2); assert.ok(models.every(m => m.kind === 'model' && !m.running))
  assert.ok(activityJobSchema.safeParse({ ...first, report: { obsolete: '旧报告不阻塞活动读取' } }).success)
} finally { await vite.close() }

const taskId = process.argv[2]
if (!taskId) { console.log('PASS：8组历史父链/累计去重/缺失/循环/旧报告/逐次调用检查，0次模型调用'); process.exit(0) }
const read = async id => {
  const response = await fetch(`http://127.0.0.1:5173/api/research/jobs/${id}`)
  assert.ok(response.ok)
  const job = await response.json()
  assert.ok(activityJobSchema.safeParse(job).success)
  return job
}
const current = await read(taskId), history = await loadAncestors(current, read)
assert.equal(history.warning, '')
const runs = [...history.runs, current], total = activityTotals(runs)
const { chromium } = require(path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'))
const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } }), posts = [], errors = []
  page.on('request', r => { if (r.method() === 'POST') posts.push(r.url()) })
  page.on('pageerror', e => errors.push(e.message))
  await page.goto(`http://127.0.0.1:5173/?task=${taskId}`)
  try { await page.locator('.activity-replay > summary').click({ timeout: 15000 }) }
  catch (error) {
    const folder = path.join(root, '.runtime/qa/run-history'); await fs.mkdir(folder, { recursive: true })
    await page.screenshot({ path: path.join(folder, 'failure.png') })
    console.log('page errors', errors, 'body', (await page.locator('body').innerText()).slice(0, 2500))
    throw error
  }
  await page.getByTestId('activity-total').filter({ hasText: `累计：${total.calls} 次调用` }).waitFor({ timeout: 25000 })
  assert.equal(await page.locator('.activity-run').count(), runs.length)
  assert.equal(await page.locator('.activity-model').count(), runs.reduce((sum, r) => sum+r.events.filter(e => e.type === 'model_started').length, 0))
  for (let i=0; i<runs.length; i++) assert.equal(await page.locator('.activity-run').nth(i).getAttribute('data-run-id'), runs[i].taskId)
  if (runs.length > 1) await page.locator('.activity-run').first().locator(':scope > summary').click()
  const folder = path.join(root, '.runtime/qa/run-history'); await fs.mkdir(folder, { recursive: true })
  await page.locator('.activity-replay').scrollIntoViewIfNeeded()
  await page.screenshot({ path: path.join(folder, `${taskId}.png`) })
  await page.setViewportSize({ width: 375, height: 1050 })
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth+1))
  assert.equal(posts.length, 0); assert.equal(errors.length, 0)
  console.log(JSON.stringify({ taskId, runs: total.count, totalCalls: total.calls, totalTokens: total.usage.total_tokens,
    checks: '真实父链顺序/累计/历史失败/每次模型调用/手机宽度/0次模型请求通过' }))
} finally { await browser.close() }
