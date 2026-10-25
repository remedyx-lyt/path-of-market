/** 实际Java记忆HTTP夹具的网页契约、零收费读取、版本冲突与失败输入保留；不调用模型。 */
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
  const fixture = JSON.parse(fs.readFileSync(path.join(root, '.runtime/qa/memory/result.json'), 'utf8')).memory
  const { getUserMemory, editUserMemory } = await vite.ssrLoadModule('/src/api/memory.ts')
  const { ActivityPanel } = await vite.ssrLoadModule('/src/features/research-lab/ActivityPanel.tsx')
  const calls = []
  globalThis.fetch = async (_url, options) => {
    calls.push(options)
    return { ok: true, json: async () => fixture }
  }
  const result = await getUserMemory()
  assert.equal(result.companyCount, 2)
  assert.ok(result.notes.some((n) => n.status === 'confirmed'))
  assert.equal(calls[0].method, 'GET')
  await editUserMemory(result.revision, { action: 'save', text: '修改后的现金流偏好', category: 'research_preference' })
  const sent = JSON.parse(calls.at(-1).body)
  assert.deepEqual(sent, { revision: result.revision, action: 'save', text: '修改后的现金流偏好', category: 'research_preference' })
  globalThis.fetch = async () => ({ ok: false, json: async () => ({ error: { message: '记忆已更新，请刷新后再保存' } }) })
  await assert.rejects(() => editUserMemory(0, { action: 'toggle', enabled: false }), /刷新后再保存/)
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ ...fixture, notes: ['malformed'] }) })
  await assert.rejects(() => getUserMemory(), /格式不完整/)
  const job = { events: [{ id: 'memory', type: 'memory_loaded', message: '已读取研究记忆：1条确认偏好、2个研究对象' }], modelCalls: 0, usage: {}, phase: 'research' }
  assert.match(renderToStaticMarkup(createElement(ActivityPanel, { job, live: false })), /已读取研究记忆/)
  console.log('PASS：真实记忆响应契约、查看零POST、保存版本/字段、冲突消息、无效响应保护、记忆活动事件；0次真实模型调用。')
} finally { await vite.close() }
