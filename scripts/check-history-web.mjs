/** 读取真实已完成任务，验证长年限报告/图表/扫描覆盖；不创建模型任务。 */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import fs from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'
const root = path.resolve(import.meta.dirname, '..')
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'))
const files = process.argv.slice(2)
assert.ok(files.length, '提供已完成任务JSON文件路径')
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
try {
  for (const file of files) {
    const job = JSON.parse(await fs.readFile(path.resolve(root, file), 'utf8'))
    assert.equal(job.status, 'completed')
    const report = job.report
    const output = path.join(root, '.runtime/qa/history-web', job.taskId)
    await fs.mkdir(output, { recursive: true })
    const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } })
    const errors = [], posts = []
    page.on('pageerror', (e) => errors.push(e.message))
    page.on('request', (r) => { if (r.method() === 'POST') posts.push(r.url()) })
    await page.goto(`http://127.0.0.1:5173/?task=${job.taskId}`)
    await page.getByText('真实研究 · 已完成', { exact: true }).waitFor({ timeout: 25000 })
    assert.equal(await page.locator('.report-section').count(), report.sections.length)
    assert.ok(await page.locator('.financial-chart').count() > 0)
    assert.ok(await page.locator('.section-citations a').count() > 0)
    const labels = page.getByRole('checkbox', { name: '显示图表数据标签' })
    assert.ok(await page.locator('.chart-data-labels').count() > 0)
    await labels.uncheck(); assert.equal(await page.locator('.chart-data-labels').count(), 0)
    await labels.check(); assert.ok(await page.locator('.chart-data-labels').count() > 0)
    const first = page.locator('.financial-chart').first()
    await first.scrollIntoViewIfNeeded()
    await first.screenshot({ path: path.join(output, 'financial-chart.png') })
    for (const width of [1440, 768, 375]) {
      await page.setViewportSize({ width, height: 1050 })
      await page.locator('.report-title').scrollIntoViewIfNeeded()
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `页面横向溢出：${width}`)
      await page.screenshot({ path: path.join(output, `report-${width}.png`) })
    }
    assert.equal(errors.length, 0, errors.join('; '))
    assert.equal(posts.filter((url) => url.includes('/api/research/jobs')).length, 0)
    console.log(JSON.stringify({ taskId: job.taskId, target: report.target, annualYears: report.annualHistory?.count,
      sections: report.sections.length, charts: await page.locator('.financial-chart').count(), checks: '真实页面/图表/标签开关/三宽度/无新增任务通过' }))
    await page.close()
  }
} finally { await browser.close() }
