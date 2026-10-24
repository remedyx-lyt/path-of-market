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
  const fixture = JSON.parse(fs.readFileSync(path.join(root, '.runtime/qa/discussion/result.json'), 'utf8')).discussion
  const { getDiscussion, selectedTurns } = await vite.ssrLoadModule('/src/api/discussion.ts')
  const { agentReportSchema } = await vite.ssrLoadModule('/src/api/researchSchemas.ts')
  const { ReportWorkbench } = await vite.ssrLoadModule('/src/features/research-lab/ReportWorkbench.tsx')
  const { ResearchPreview } = await vite.ssrLoadModule('/src/features/research-lab/ResearchPreview.tsx')
  const { ReportText } = await vite.ssrLoadModule('/src/features/research-lab/ReportText.tsx')
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
    isGenerating: false, hasError: false, job: { events: [{ id: 'x', type: 'run_completed', message: 'done' }], modelCalls: 3, usage: {} } }))
  assert.match(preview, /查看研究过程与工具记录/)
  const escaped = renderToStaticMarkup(createElement(ReportText, { text: '<script>alert(1)</script> **结论**' }))
  assert.doesNotMatch(escaped, /<script>/)
  assert.match(escaped, /<strong>结论<\/strong>/)
  console.log('PASS：实际HTTP数据的三版本契约、查看零POST、父链与分支隔离、版本/对话入口、过程入口、模型HTML转义。真实模型调用0次。')
} finally { await vite.close() }
