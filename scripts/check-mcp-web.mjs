/** 网页来源/覆盖/引用/展示契约；纯离线，无模型调用。 */
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
const root = path.resolve(import.meta.dirname, '..')
const require = createRequire(path.join(root, 'apps/web/package.json'))
const { createServer } = await import(pathToFileURL(require.resolve('vite')).href)
const { createElement } = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const vite = await createServer({ root: path.join(root, 'apps/web'), server: { middlewareMode: true }, appType: 'custom' })
try {
  const { agentReportSchema } = await vite.ssrLoadModule('/src/api/researchSchemas.ts')
  const { ResearchReport } = await vite.ssrLoadModule('/src/features/research-lab/ResearchReport.tsx')
  const { ActivityPanel } = await vite.ssrLoadModule('/src/features/research-lab/ActivityPanel.tsx')
  const saved = JSON.parse(fs.readFileSync(path.join(root, 'storage/runs/m1-3-zjxc-web-live.json'), 'utf8'))
  const report = structuredClone(saved.report)
  const sid = 'web-'+'b'.repeat(24)
  report.sources.push({ sourceId: sid, kind: 'web', title: '公开网页正文', url: 'https://example.org/news', publishedAt: '2026-10-20', retrievedAt: '2026-10-25T00:00:00Z', citationEligible: true })
  report.coverage.push({ sourceId: sid, unit: 'segment', pageCount: 2, processedPages: [1,2], processedCharacters: 25000, fetchedCharacters: 25000, batches: 2, emptyTextPages: [], fetchComplete: true, textComplete: true })
  report.sections[0].citations.push({ sourceId: sid, page: null })
  assert.ok(agentReportSchema.safeParse(report).success)
  const html = renderToStaticMarkup(createElement(ResearchReport, { report }))
  assert.match(html, /25000\/25000 字网页正文/)
  assert.match(html, /网页发布日期/)
  for (const change of [r => r.coverage.at(-1).textComplete=false, r => r.sources.at(-1).publishedAt='', r => r.sources.at(-1).publishedAt='2099-01-01', r => r.sections[0].citations.at(-1).page=1]) {
    const invalid = structuredClone(report); change(invalid)
    assert.equal(agentReportSchema.safeParse(invalid).success, false)
  }
  const timeline = renderToStaticMarkup(createElement(ActivityPanel, { job: { phase: 'research', modelCalls: 0, usage: {}, events: [{ id: 'mcp', type: 'mcp_fetch_finished', message: '已取得网页正文，开始逐段阅读' }] }, live: false }))
  assert.match(timeline, /已取得网页正文/)
  console.log('PASS：7组MCP网页契约/引用限制/正文覆盖/活动展示检查，0次模型调用。')
} finally { await vite.close() }
