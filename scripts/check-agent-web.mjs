// 需要本机 Chrome 与 Playwright；只读取指定真实结果，其余故障由浏览器拦截，不调用模型。
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import fs from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'))
const root = path.resolve(import.meta.dirname, '..')
const saved = JSON.parse(await fs.readFile(path.join(root, 'storage/runs/m1-3-zjxc-web-live.json'), 'utf8'))
const taskId = process.argv[2] || saved.taskId
const output = path.join(root, '.runtime/qa/m1-3-web')
await fs.mkdir(output, { recursive: true })
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
const checks = [], errors = [], requests = []
const context = await browser.newContext({ viewport: { width: 1440, height: 1050 } })
const page = await context.newPage()
page.on('pageerror', (error) => errors.push(error.message))
page.on('request', (request) => requests.push({ url: request.url(), method: request.method() }))

try {
  await page.goto('http://127.0.0.1:5173/')
  await page.getByRole('button', { name: '填入示例' }).click()
  assert.equal(await page.getByLabel('研究对象 必填').inputValue(), '中际旭创')
  assert.ok(await page.getByLabel('真实研究', { exact: true }).isChecked())
  checks.push('default mode and Zhongji example')

  // 查看真实已完成报告，链接读取不触发 POST 或重新调用模型。
  let completedJob
  for (let i = 0; i < 40; i++) {
    const response = await context.request.get(`http://127.0.0.1:5173/api/research/jobs/${taskId}`)
    const current = await response.json()
    if (current.status === 'completed') { completedJob = current; break }
    if (i === 39) throw new Error(`live job not complete: ${current.status}`)
    await new Promise((resolve) => setTimeout(resolve, 1500))
  }
  await page.goto(`http://127.0.0.1:5173/?task=${taskId}`)
  await page.getByText('真实研究 · 已完成', { exact: true }).waitFor({ timeout: 15000 })
  assert.ok(await page.getByRole('heading', { name: '股票行情', exact: true }).isVisible())
  assert.equal(await page.locator('.report-section').count(), completedJob.report.sections.length)
  assert.ok(await page.locator('.section-citations a').count() > 5)
  assert.equal(requests.filter((r) => r.method === 'POST' && r.url.includes('/api/research/jobs')).length, 0)
  assert.equal(requests.filter((r) => /127\.0\.0\.1:8000/.test(r.url)).length, 0)
  checks.push('real completed report through Java, sources and no additional model calls')

  const section = page.locator('.market-section')
  const initialPath = await section.locator('svg path').getAttribute('d')
  await page.getByRole('button', { name: '实际价格（元）', exact: true }).click()
  assert.notEqual(await section.locator('svg path').getAttribute('d'), initialPath)
  assert.equal(await page.getByRole('button', { name: '实际价格（元）', exact: true }).getAttribute('aria-pressed'), 'true')
  const cursor = page.getByRole('slider', { name: '选择交易日' })
  const before = await cursor.inputValue()
  await cursor.focus(); await page.keyboard.press('ArrowLeft')
  assert.equal(Number(await cursor.inputValue()), Number(before) - 1)
  await page.getByRole('button', { name: '复权走势（起点100）', exact: true }).click()
  assert.ok((await section.locator('table').innerText()).includes('最大回撤'))
  await section.screenshot({ path: path.join(output, 'market-chart.png') })
  checks.push('chart adjustment modes, date cursor and computed table')

  for (const width of [1440, 768, 375, 320]) {
    await page.setViewportSize({ width, height: 1000 })
    await page.locator('.report-title').scrollIntoViewIfNeeded()
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `overflow at ${width}`)
    await page.screenshot({ path: path.join(output, `report-${width}.png`) })
  }
  checks.push('four responsive widths without horizontal overflow')

  const actual = await (await context.request.get(`http://127.0.0.1:5173/api/research/jobs/${taskId}`)).json()
  const fixtureId = '11111111-1111-4111-8111-111111111111'
  const fixture = { ...actual, taskId: fixtureId, report: null, status: 'running', progress: '隔离进度：正在阅读', coverage: [], events: [], modelCalls: 1 }
  const failurePage = await context.newPage()
  failurePage.on('pageerror', (error) => errors.push(error.message))
  let scenario = 'busy', deletes = 0
  await failurePage.route('**/api/research/jobs**', async (route) => {
    const method = route.request().method()
    let status = method === 'POST' ? 202 : 200, body = fixture
    if (scenario === 'busy') { status = 409; body = { error: { code: 'RESEARCH_BUSY', message: 'private-fixture-body' } } }
    else if (scenario === 'bad-report') { body = { ...fixture, status: 'completed', report: { ...actual.report, sources: [{ sourceId: 'bad', title: 'bad', kind: 'document', url: 'javascript:alert(1)' }] } } }
    else if (method === 'DELETE') { deletes++; body = { ...fixture, status: 'cancelled' } }
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await failurePage.goto('http://127.0.0.1:5173/')
  await failurePage.getByRole('button', { name: '填入示例' }).click()
  await failurePage.getByRole('button', { name: '开始真实研究' }).click()
  await failurePage.getByRole('alert').waitFor()
  assert.ok((await failurePage.getByRole('alert').innerText()).includes('已有研究正在运行'))
  assert.ok(!(await failurePage.locator('body').innerText()).includes('private-fixture-body'))
  checks.push('busy error localized and private upstream text hidden')

  scenario = 'bad-report'
  await failurePage.getByRole('button', { name: '开始真实研究' }).click()
  await failurePage.getByText('任务或报告格式不正确。', { exact: true }).waitFor()
  checks.push('invalid nested report and unsafe source URL rejected')

  scenario = 'running'
  await failurePage.getByRole('button', { name: '开始真实研究' }).click()
  await failurePage.getByText('隔离进度：正在阅读', { exact: true }).waitFor()
  await failurePage.getByRole('button', { name: '取消并清空' }).click()
  await failurePage.waitForFunction(() => document.querySelector('#research-target')?.value === '')
  for (let i = 0; i < 20 && deletes === 0; i++) await new Promise((resolve) => setTimeout(resolve, 100))
  assert.equal(deletes, 1)
  assert.equal(await failurePage.locator('.report-title').count(), 0)
  checks.push('explicit cancellation reaches DELETE and stale result stays cleared')

  await failurePage.unroute('**/api/research/jobs**')
  await failurePage.getByLabel('演示报告', { exact: true }).check()
  await failurePage.getByRole('button', { name: '填入示例' }).click()
  await failurePage.getByRole('button', { name: '生成演示报告' }).click()
  await failurePage.getByText('演示报告 · MOCK', { exact: true }).waitFor()
  checks.push('original real mock round trip still works')
  assert.deepEqual(errors, [])
  checks.push('no browser page exceptions')
  await fs.writeFile(path.join(output, 'summary.json'), JSON.stringify({ checks, passed: checks.length, taskId, errors }, null, 2))
  console.log(JSON.stringify({ passed: checks.length, checks, output }, null, 2))
} finally { await browser.close() }
