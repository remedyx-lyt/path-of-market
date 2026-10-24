/** 离线组件验收：使用 Vite 加载真实 TSX，检查失败活动流和方法计划文案，不启动研究/不调用模型。 */
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const requireWeb = createRequire(path.join(root, 'apps/web/package.json'))
const { createServer } = await import(pathToFileURL(requireWeb.resolve('vite')).href)
const { createElement } = requireWeb('react')
const { renderToStaticMarkup } = requireWeb('react-dom/server')
const vite = await createServer({ root: path.join(root, 'apps/web'), server: { middlewareMode: true }, appType: 'custom' })
try {
  const { timeline } = await vite.ssrLoadModule('/src/features/research-lab/ActivityPanel.tsx')
  const { ResearchReport } = await vite.ssrLoadModule('/src/features/research-lab/ResearchReport.tsx')
  const event = (id, type, fields = {}) => ({ id, type, message: type, parentId: null, timestamp: '', ...fields })
  const failed = timeline([
    event('s', 'model_started', { modelCall: 1, purpose: '形成研究计划' }),
    event('f', 'model_failed', { modelCall: 1, message: '形成研究计划未完成：输出达到上限', usage: { completion_tokens: 6500 }, durationMs: 80 }),
  ])
  assert.equal(failed[0].running, false)
  assert.equal(failed[0].failed, true)
  assert.equal(failed[0].tokens, 6500)
  const stopped = timeline([
    event('t', 'tool_started', { toolCallId: 'a', name: 'read_document' }),
    event('m', 'model_started', { modelCall: 2, purpose: '提取数据' }),
    event('section', 'writing_section', { message: '正在写：未完成节' }),
    event('end', 'run_failed'),
  ])
  assert.equal(stopped.find((i) => i.kind === 'tool').status, 'interrupted')
  assert.equal(stopped.find((i) => i.kind === 'model').running, false)
  assert.equal(stopped.find((i) => i.kind === 'section').failed, true)
  const reading = timeline([
    event('r', 'model_failed', { modelCall: 3, purpose: '阅读原文', message: '阅读输出上限' }),
    event('split', 'reading_batch_split'), event('invalid', 'methods_plan_invalid'), event('retry', 'reading_batch_retry'),
  ])
  assert.equal(reading.length, 4)
  assert.equal(reading[0].warn, true)
  const usage = { status: 'plan_failed', references: [], plan: null, reviewed: false }
  const report = {
    mode: 'agent', isMock: false, target: '隔离检查', question: 'q', asOfDate: '2026-10-24', omens: [], userStyle: '', title: '未完成', summary: '未完成',
    sections: [], sources: [], coverage: [], toolCalls: [], limitations: [], methodUsage: usage,
    run: { status: 'partial', taskId: 'offline', modelCalls: 1, steps: 1, stopReason: 'test', usage: {} },
  }
  const html = renderToStaticMarkup(createElement(ResearchReport, { report }))
  assert.ok(html.includes('方法计划未形成'))
  assert.ok(!html.includes('已形成计划'))
  console.log('PASS 4 recovery UI groups: failed model, interrupted tools, recovery events, truthful plan status; no model calls')
} finally {
  await vite.close()
}
