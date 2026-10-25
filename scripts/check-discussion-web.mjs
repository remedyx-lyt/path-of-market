/** 用隔离HTTP验收产生的实际JSON检查网页契约/分支/安全展示，不调用模型。 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
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
  const result = JSON.parse(fs.readFileSync(path.join(root, '.runtime/qa/discussion/result.json'), 'utf8'))
  const fixture = result.discussion
  const { getDiscussion, selectedTurns } = await vite.ssrLoadModule('/src/api/discussion.ts')
  const { agentReportSchema } = await vite.ssrLoadModule('/src/api/researchSchemas.ts')
  const { ReportWorkbench } = await vite.ssrLoadModule('/src/features/research-lab/ReportWorkbench.tsx')
  const { ResearchPreview } = await vite.ssrLoadModule('/src/features/research-lab/ResearchPreview.tsx')
  const { ReportText } = await vite.ssrLoadModule('/src/features/research-lab/ReportText.tsx')
  const { ActivityPanel, timeline } = await vite.ssrLoadModule('/src/features/research-lab/ActivityPanel.tsx')
  const methods = []
  globalThis.fetch = async (_url, options) => { methods.push(options?.method ?? 'GET'); return { ok: true, json: async () => fixture } }
  const data = await getDiscussion(fixture.rootTaskId)
  assert.ok(data.versions.length >= 3)
  assert.deepEqual(methods, ['GET'])
  for (const version of data.versions) {
    assert.ok(agentReportSchema.safeParse(version.report).success)
    assert.match(renderToStaticMarkup(createElement(ReportWorkbench, { report: version.report })), /报告版本/)
  }
  const follow = data.turns.find((t) => t.userMessage === 'QA_FOLLOW')
  assert.deepEqual(selectedTurns(data.turns, follow.id).map((t) => t.userMessage), ['QA_FIRST', 'QA_REVISE', 'QA_FOLLOW'])
  const sibling = data.turns.find((t) => t.userMessage === 'QA_SIBLING')
  assert.deepEqual(selectedTurns(data.turns, sibling.id).map((t) => t.userMessage), ['QA_SIBLING'])
  assert.deepEqual(selectedTurns(data.turns, data.versions[0].id), [])
  const html = renderToStaticMarkup(createElement(ReportWorkbench, { report: data.versions[0].report }))
  assert.match(html, /报告对话/)
  assert.match(html, /report-version/)
  const preview = renderToStaticMarkup(createElement(ResearchPreview, { draft: null, report: data.versions[0].report,
    isGenerating: false, hasError: false, job: { taskId: data.versions[0].report.run.taskId,
      status: 'completed', startedAt: data.versions[0].report.run.startedAt,
      events: [{ id: 'x', type: 'run_completed', message: 'done' }], modelCalls: 3, usage: {} } }))
  assert.match(preview, /查看完整研究过程与工具记录/)
  const escaped = renderToStaticMarkup(createElement(ReportText, { text: '<script>alert(1)</script> **结论**' }))
  assert.doesNotMatch(escaped, /<script>/)
  assert.match(escaped, /<strong>结论<\/strong>/)
  const compacted = result.compactionJob
  assert.ok(compacted.events.some((e) => e.type === 'compaction_completed'))
  const compactHtml = renderToStaticMarkup(createElement(ActivityPanel, { job: compacted, live: false }))
  assert.match(compactHtml, /上下文已整理 1 次/)
  assert.match(compactHtml, /查看第 1 次上下文摘要/)
  assert.match(compactHtml, /原始研究资料仍保留/)
  assert.ok(timeline(compacted.events).some((e) => e.kind === 'note' && e.text.includes('上下文整理完成')))
  const hostile = { ...compacted, events: compacted.events.map((e) => e.type === 'compaction_completed' ? { ...e, summaryText: '<script>alert(1)</script>' } : e) }
  assert.doesNotMatch(renderToStaticMarkup(createElement(ActivityPanel, { job: hostile, live: false })), /<script>/)
  // 保存真实组件的离线渲染，供浏览器核对原生details展开与布局；不向正式服务写测试任务。
  const previewFolder = path.join(root, '.runtime/qa/discussion')
  const css = fs.readdirSync(path.join(root, 'apps/web/dist/assets')).find((name) => name.endsWith('.css'))
  fs.copyFileSync(path.join(root, 'apps/web/dist/assets', css), path.join(previewFolder, 'preview.css'))
  fs.writeFileSync(path.join(previewFolder, 'compaction-preview.html'), `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>上下文压缩 · 隔离检查</title><link rel="stylesheet" href="preview.css"><body><main class="research-preview--agent" style="max-width:1000px;margin:40px auto;padding:24px"><h1>上下文整理</h1><p>隔离检查：实际多轮HTTP结果，使用脚本模型；未调用真实模型。</p>${compactHtml}</main></body></html>`)
  console.log('PASS：实际HTTP数据的三版本契约、查看零POST、父链隔离、入口、HTML转义，以及摘要/字符数/过程事件展示。真实模型调用0次。')
} finally { await vite.close() }
