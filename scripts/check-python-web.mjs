/** 浏览器、Vite 同源代理和单进程 FastAPI 的离线端到端验收。 */
import assert from 'node:assert/strict'
import { execFileSync, spawn } from 'node:child_process'
import { once } from 'node:events'
import { mkdtemp, rm } from 'node:fs/promises'
import { createRequire } from 'node:module'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'

const root = path.resolve(import.meta.dirname, '..')
const webRoot = path.join(root, 'apps/web')
const require = createRequire(path.join(webRoot, 'package.json'))
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || path.join(os.homedir(),
  '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'))
const { createServer } = await import(pathToFileURL(require.resolve('vite')).href)
const temp = await mkdtemp(path.join(os.tmpdir(), 'pom-browser-'))
const socket = net.createServer().listen(0, '127.0.0.1')
await once(socket, 'listening')
const port = socket.address().port
await new Promise(resolve => socket.close(resolve))
process.env.API_SERVER_URL = `http://127.0.0.1:${port}`
const python = process.env.PYTHON || path.join(root, 'apps/agent/.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
const env = { ...process.env, SESSIONS_DIR: path.join(temp, 'sessions'), PYTHONUTF8: '1' }
let executable = python
if (process.platform === 'win32') {
  executable = execFileSync(python, ['-c', 'import sys; print(sys._base_executable)'], { encoding: 'utf8', windowsHide: true }).trim()
  env.__PYVENV_LAUNCHER__ = python
}
const backend = spawn(executable, [path.join(root, 'scripts/backend_contract/fixture_agent.py'), String(port), temp, '--complete'],
  { env, stdio: 'inherit', windowsHide: true })
const exited = once(backend, 'exit')
let vite, browser
try {
  for (let i = 0; i < 150; i++) {
    if (backend.exitCode !== null) throw Error('隔离后端启动失败')
    if (await fetch(process.env.API_SERVER_URL + '/api/health').then(r => r.ok, () => false)) break
    await delay(200)
  }
  vite = await createServer({ root: webRoot, server: { host: '127.0.0.1', port: 0 }, logLevel: 'error' })
  await vite.listen()
  const origin = `http://127.0.0.1:${vite.httpServer.address().port}`
  browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true })
  const page = await browser.newPage()
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.goto(origin)
  await page.locator('#research-target').fill('同花顺')
  await page.locator('.research-options summary').click()
  await page.locator('#research-date').fill('2026-10-23')
  await page.locator('#research-question').fill('研究最近两年的经营变化与行情。')
  const jobs = '/api/research/jobs'
  const creating = page.waitForResponse(r => r.url() === origin + jobs && r.request().method() === 'POST')
  await page.getByRole('button', { name: '开始真实研究' }).click()
  const created = await creating
  assert.equal(created.status(), 202)
  const { taskId } = await created.json()
  try {
    await page.getByRole('button', { name: '报告对话' }).waitFor({ timeout: 90000 })
  } catch (error) {
    const job = await (await fetch(origin + jobs + '/' + taskId)).json()
    throw Error(JSON.stringify({ status: job.status, error: job.error, progress: job.progress, events: job.events.slice(-4) }), { cause: error })
  }
  const report = await (await fetch(origin + jobs + '/' + taskId)).json()
  assert.equal(report.status, 'completed', JSON.stringify({ error: report.error, progress: report.progress, events: report.events.slice(-6) }))
  assert.ok(report.report.sections.length > 0 && report.coverage.length > 0)
  await page.getByRole('button', { name: '报告对话' }).click()
  await page.locator('#followup-message').fill('解释这个判断的资料来源。')
  const sending = page.waitForResponse(r => r.url().endsWith('/chat') && r.request().method() === 'POST')
  await page.getByRole('button', { name: '发送追问' }).click()
  assert.equal((await sending).status(), 202)
  await page.getByText('离线回答。', { exact: true }).waitFor()
  const restoring = page.waitForResponse(r => r.url().endsWith('/discussion') && r.request().method() === 'GET')
  await page.goto(origin + '/?task=' + taskId)
  const history = await (await restoring).json()
  assert.ok(history.turns.some(turn => turn.status === 'completed' && turn.answer === '离线回答。'))
  await page.getByText('离线回答。', { exact: true }).waitFor()
  assert.deepEqual(errors, [])
  console.log('PASS 浏览器创建研究、查看报告、发送追问、重开历史并读回回答。')
} finally {
  await browser?.close()
  await vite?.close()
  backend.kill()
  await exited
  assert.equal(path.dirname(path.resolve(temp)), path.resolve(os.tmpdir()))
  assert.ok(path.basename(temp).startsWith('pom-browser-'))
  await rm(temp, { recursive: true, force: true, maxRetries: 3 })
}
