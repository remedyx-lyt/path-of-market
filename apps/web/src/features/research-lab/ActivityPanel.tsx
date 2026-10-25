import { useEffect, useRef } from 'react'
import type { JobEvent, ResearchJob } from '../../api/research'

const PHASES = [
  { id: 'methods', label: '读方法与计划' },
  { id: 'research', label: '取证' },
  { id: 'writing', label: '写正文' },
  { id: 'tables', label: '整理数据表' },
  { id: 'review', label: '复核' },
  { id: 'done', label: '完成' },
] as const

/** 值得单独列出的过程事件（其余如逐批阅读进度并入对应工具行）。 */
const NOTES = new Set(['current_period_lookup', 'skill_read', 'data_extracted', 'visual_gap', 'context_wrapup', 'report_validation_failed',
  'report_normalized', 'figure_duplicates_removed', 'unknown_figures_removed', 'required_figures_placed', 'tables_dropped',
  'review_discarded', 'report_drafting_fallback', 'methods_plan_failed', 'run_partial', 'run_failed', 'run_cancelled'])
for (const type of ['methods_plan_invalid', 'reading_note_invalid', 'reading_batch_split', 'reading_batch_retry', 'reading_batch_failed']) NOTES.add(type)
for (const type of ['run_resumed', 'budget_wrapup', 'checkpoint_failed', 'writing_unit_retry', 'writing_unit_failed']) NOTES.add(type)
for (const type of ['compaction_started', 'compaction_completed', 'compaction_failed', 'compaction_skipped']) NOTES.add(type)
for (const type of ['memory_loaded', 'memory_disabled', 'memory_unavailable', 'memory_suggested']) NOTES.add(type)
for (const type of ['mcp_search_started', 'mcp_search_finished', 'mcp_fetch_started', 'mcp_fetch_finished']) NOTES.add(type)
for (const type of ['annual_history_lookup', 'annual_history_found']) NOTES.add(type)
NOTES.add('annual_history_recheck_failed')
NOTES.add('scan_reading')
NOTES.add('writing_deferred')

type Item =
  | { kind: 'phase'; id: string; text: string }
  | { kind: 'tool'; id: string; label: string; summary: string; status: string; result?: string; durationMs?: number; progress?: string }
  | { kind: 'model'; id: string; text: string; durationMs?: number; tokens?: number; running: boolean; failed?: boolean }
  | { kind: 'decision' | 'note'; id: string; text: string; warn?: boolean }
  | { kind: 'section'; id: string; text: string; done: boolean; failed?: boolean }

function seconds(ms?: number) {
  return ms == null ? '' : ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`
}

/** 把事件序列整理成时间线：工具开始/结束合并成一行；模型调用合并；写作阶段逐节列出。 */
export function timeline(events: JobEvent[]): Item[] {
  const items: Item[] = []
  const tools = new Map<string, Extract<Item, { kind: 'tool' }>>()
  const models = new Map<number, Extract<Item, { kind: 'model' }>>()
  let lastSection: Extract<Item, { kind: 'section' }> | null = null
  let runningTool: Extract<Item, { kind: 'tool' }> | null = null
  for (const e of events) {
    if (e.type === 'phase_changed') {
      if (lastSection) lastSection.done = true
      lastSection = null
      items.push({ kind: 'phase', id: e.id, text: e.message.replace(/^阶段：/, '') })
    } else if (e.type === 'tool_started' && e.toolCallId) {
      const item = { kind: 'tool' as const, id: e.id, label: e.label ?? e.name ?? '工具', summary: e.summary ?? '', status: 'running' }
      tools.set(e.toolCallId, item); items.push(item); runningTool = item
    } else if (e.type === 'tool_finished' && e.toolCallId && tools.has(e.toolCallId)) {
      Object.assign(tools.get(e.toolCallId)!, { status: e.status ?? 'completed', result: e.result, durationMs: e.durationMs, progress: undefined })
      runningTool = null
    } else if (e.type === 'reading_processed' && runningTool) {
      runningTool.progress = e.message.replace(/^.*?：/, '')
    } else if (e.type === 'model_started' && e.modelCall != null && e.purpose !== '决定下一步' && e.purpose !== '阅读原文') {
      const item = { kind: 'model' as const, id: e.id, text: e.purpose ?? e.message, running: true }
      models.set(e.modelCall, item); items.push(item)
    } else if (e.type === 'model_finished' && e.modelCall != null && models.has(e.modelCall)) {
      Object.assign(models.get(e.modelCall)!, { running: false, durationMs: e.durationMs, tokens: e.usage?.total_tokens })
    } else if (e.type === 'model_failed') {
      if (lastSection && !lastSection.done && (e.purpose === '撰写正文' || e.purpose === '整理数据表')) lastSection.failed = true
      if (e.modelCall != null && models.has(e.modelCall)) {
        Object.assign(models.get(e.modelCall)!, { running: false, failed: true, text: e.message, durationMs: e.durationMs, tokens: e.usage?.completion_tokens })
      } else items.push({ kind: 'note', id: e.id, text: e.message, warn: true })
    } else if (e.type === 'run_failed' || e.type === 'run_cancelled' || e.type === 'run_partial') {
      if (lastSection && !lastSection.done) lastSection.failed = true
      for (const tool of tools.values()) if (tool.status === 'running') Object.assign(tool, { status: 'interrupted', result: '任务已停止，此动作未完成' })
      for (const model of models.values()) if (model.running) Object.assign(model, { running: false, failed: true, text: model.text + '（未完成）' })
      items.push({ kind: 'note', id: e.id, text: e.message, warn: true })
    } else if (e.type === 'assistant_message') {
      items.push({ kind: 'decision', id: e.id, text: e.message })
    } else if (e.type === 'writing_section' || e.type === 'table_section') {
      if (lastSection) lastSection.done = true
      lastSection = { kind: 'section', id: e.id, text: e.message, done: false }
      items.push(lastSection)
    } else if (e.type === 'writing_section_saved') {
      if (lastSection && lastSection.text.includes(e.title ?? '')) Object.assign(lastSection, { done: true, failed: false })
    } else if (NOTES.has(e.type)) {
      items.push({ kind: 'note', id: e.id, text: e.message, warn: /failed|dropped|discarded|partial|gap|fallback|cancelled/.test(e.type) })
    }
  }
  return items
}

export function ActivityPanel({ job, live }: { job: ResearchJob; live: boolean }) {
  const listRef = useRef<HTMLOListElement>(null)
  const items = timeline(job.events)
  const current = PHASES.findIndex((p) => p.id === job.phase)
  const plan = job.events.find((e) => e.type === 'methods_planned')
  const hit = job.usage.prompt_cache_hit_tokens, miss = job.usage.prompt_cache_miss_tokens
  const compactions = job.events.filter((e) => e.type === 'compaction_completed')
  const elapsed = (Date.parse(job.events.at(-1)?.timestamp ?? '') - Date.parse(job.events[0]?.timestamp ?? '')) / 1000
  useEffect(() => {
    if (live && listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight
  }, [live, items.length])
  return <section className="activity-panel" aria-label="研究过程">
    <ol className="activity-phases">{PHASES.map((p, i) => <li key={p.id} className={i < current || job.phase === 'done' ? 'is-done' : i === current ? 'is-current' : ''}>{p.label}</li>)}</ol>
    <p className="activity-meter">
      模型调用 {job.modelCalls} 次 · {(job.usage.total_tokens ?? 0).toLocaleString()} tokens
      {typeof hit === 'number' && typeof miss === 'number' && hit + miss > 0 ? ` · 缓存命中 ${Math.round(hit / (hit + miss) * 100)}%` : ''}
      {Number.isFinite(elapsed) && elapsed > 0 ? ` · 用时 ${Math.floor(elapsed / 60)}分${Math.round(elapsed % 60)}秒` : ''}
      {compactions.length ? ` · 上下文已整理 ${compactions.length} 次` : ''}
    </p>
    {compactions.map((event, index) => <details key={event.id} className="activity-plan"><summary>查看第 {index + 1} 次上下文摘要</summary>
      <p>上下文字符数：{event.beforeCharacters?.toLocaleString()} → {event.afterCharacters?.toLocaleString()}。这是模型摘要，原始研究资料仍保留。</p>
      <p style={{ whiteSpace: 'pre-wrap' }}>{event.summaryText}</p>
    </details>)}
    {plan?.checks?.length ? <details className="activity-plan"><summary>研究计划 · {plan.checks.length} 项检查</summary>
      {plan.focus ? <p>{plan.focus}</p> : null}
      <ol>{plan.checks.map((c, i) => <li key={i}>{c.question}</li>)}</ol>
    </details> : null}
    <ol className="activity-timeline" ref={listRef} aria-live={live ? 'polite' : undefined}>{items.map((item) => {
      if (item.kind === 'phase') return <li key={item.id} className="activity-phase">{item.text}</li>
      if (item.kind === 'tool') return <li key={item.id} className={`activity-tool is-${item.status}`}>
        <span className="activity-mark" aria-hidden="true">{item.status === 'running' ? '◌' : item.status === 'completed' ? '✓' : '✕'}</span>
        <div><strong>{item.label}</strong> {item.summary}
          <small>{item.status === 'running' ? item.progress ?? '进行中…' : item.result}{item.durationMs != null ? ` · ${seconds(item.durationMs)}` : ''}</small></div>
      </li>
      if (item.kind === 'model') return <li key={item.id} className={`activity-model${item.running ? ' is-running' : ''}`}>
        <span className="activity-mark" aria-hidden="true">{item.running ? '◌' : item.failed ? '✕' : '✓'}</span>
        <div><strong>模型</strong> {item.text}<small>{item.running ? '进行中…' : [seconds(item.durationMs), item.tokens ? `${item.tokens.toLocaleString()} tokens` : ''].filter(Boolean).join(' · ')}</small></div>
      </li>
      if (item.kind === 'section') return <li key={item.id} className={`activity-section${item.done || item.failed ? '' : ' is-running'}`}>
        <span className="activity-mark" aria-hidden="true">{item.failed ? '✕' : item.done ? '✓' : '✎'}</span><div>{item.failed ? `${item.text}（本次输出未完成）` : item.done ? item.text.replace(/^正在写/, '已写').replace(/^正在整理表/, '已整理表') : item.text}</div>
      </li>
      return <li key={item.id} className={`activity-${item.kind}${item.kind === 'note' && item.warn ? ' is-warn' : ''}`}><div>{item.text}</div></li>
    })}</ol>
  </section>
}
