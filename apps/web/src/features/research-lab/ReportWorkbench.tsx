import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import type { AgentResearchReport, ResearchJob } from '../../api/research'
import { cancelAgentJob, getAgentJob } from '../../api/research'
import { getDiscussion, pollFollowup, selectedTurns, sendFollowup } from '../../api/discussion'
import type { Discussion, DiscussionTurn } from '../../api/discussion'
import { ActivityPanel } from './ActivityPanel'
import { ResearchReport } from './ResearchReport'
import { ReportText } from './ReportText'

export function ReportWorkbench({ report }: { report: AgentResearchReport }) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<Discussion | null>(null)
  const [versionId, setVersionId] = useState('')
  const [leaf, setLeaf] = useState('')
  const [message, setMessage] = useState('')
  const [action, setAction] = useState<'ask' | 'revise'>('ask')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState<ResearchJob | null>(null)
  const controller = useRef<AbortController | null>(null)
  const request = useRef<{ signature: string; id: string } | null>(null)
  const reportRef = useRef<HTMLDivElement>(null)
  const selectedVersion = data?.versions.find((v) => v.id === versionId)
  const shownReport = selectedVersion?.report ?? report
  const isComplete = report.run.status === 'completed'

  const remember = useCallback((node: string, version: string) => {
    const url = new URL(window.location.href)
    url.searchParams.set('chatNode', node)
    url.searchParams.set('version', version)
    window.history.replaceState(null, '', url)
  }, [])

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const next = await getDiscussion(report.run.taskId, signal)
    if (!signal?.aborted) setData(next)
    return next
  }, [report.run.taskId])

  const watch = useCallback(async (taskId: string, abort: AbortController) => {
    setBusy(true)
    try {
      const job = await pollFollowup(taskId, abort.signal, setProgress)
      const next = await refresh(abort.signal)
      const turn = next.turns.find((t) => t.runId === taskId)
      if (turn) {
        if (turn.status === 'pending' && !['queued', 'running'].includes(job.status)) {
          turn.status = job.status === 'completed' ? 'failed' : job.status === 'cancelled' ? 'cancelled' : 'failed'
          turn.error = job.error ?? { code: 'RESEARCH_INTERRUPTED', message: '本次对话中途停止，已保存的证据可继续使用。' }
          setData({ ...next, turns: [...next.turns] })
        }
        setLeaf(turn.id)
        const id = turn.versionId ?? turn.baseVersionId
        setVersionId(id)
        remember(turn.id, id)
      }
      if (job.status !== 'completed') setError(job.error?.message ?? '本次对话未完成，原报告保留，可从上一节点重试。')
    } catch (reason) {
      if (!abort.signal.aborted) setError(reason instanceof Error ? reason.message : '读取对话进度失败，请刷新记录。')
    } finally { if (controller.current === abort) { controller.current = null; setBusy(false) } }
  }, [refresh, remember])

  useEffect(() => {
    if (!isComplete) return
    const abort = new AbortController()
    controller.current = abort
    void refresh(abort.signal).then((next) => {
      if (abort.signal.aborted) return
      const params = new URLSearchParams(window.location.search)
      const chosenTurn = next.turns.find((t) => t.id === params.get('chatNode'))
      const requestedVersion = chosenTurn?.versionId ?? chosenTurn?.baseVersionId ?? params.get('version')
      const version = next.versions.find((v) => v.id === requestedVersion) ?? next.versions.at(-1)
      if (!version) return
      setVersionId(version.id)
      setLeaf(chosenTurn?.id ?? version.id)
      if (chosenTurn) setOpen(true)
      const pending = [...next.turns].reverse().find((t) => t.status === 'pending')
      if (pending) { setOpen(true); void watch(pending.runId, abort) }
      else controller.current = null
    }).catch((reason) => { if (!abort.signal.aborted) setError(reason instanceof Error ? reason.message : '读取记录失败。') })
    return () => { abort.abort(); controller.current?.abort(); controller.current = null }
  }, [isComplete, refresh, watch])

  async function send(event: FormEvent) {
    event.preventDefault()
    if (!message.trim() || !data || !leaf || busy) return
    const abort = new AbortController()
    controller.current = abort
    setBusy(true); setError('')
    const signature = JSON.stringify({ message: message.trim(), action, leaf })
    if (request.current?.signature !== signature) request.current = { signature, id: crypto.randomUUID() }
    try {
      const job = await sendFollowup(data.rootTaskId, { message: message.trim(), action, parentId: leaf, requestId: request.current.id }, abort.signal)
      setMessage(''); request.current = null
      await watch(job.taskId, abort)
    } catch (reason) {
      if (!abort.signal.aborted) {
        setError(reason instanceof Error ? reason.message : '请求结果未确认，请先刷新记录，避免重复发送。')
        setBusy(false); controller.current = null
      }
    }
  }

  function retry(turn: DiscussionTurn) {
    setLeaf(turn.id); setVersionId(turn.baseVersionId)
    setMessage(turn.userMessage); setAction(turn.action); setError(''); request.current = null
    remember(turn.id, turn.baseVersionId)
  }

  function quoteSelection() {
    const selection = window.getSelection()
    if (selection?.anchorNode && selection.focusNode && reportRef.current?.contains(selection.anchorNode) && reportRef.current.contains(selection.focusNode)) {
      const quote = selection.toString().trim().slice(0, 1800)
      if (quote) {
        const next = `${message}\n\n所选报告原文：\n${quote}`.trim()
        if (next.length > 4000) { setError('问题加引用超过4000字，请缩短后再引用。'); return }
        setMessage(next); setOpen(true); setError(''); return
      }
    }
    setError('请先在报告正文中选中要讨论的文字，再点引用。')
  }

  const turns = data ? selectedTurns(data.turns, leaf) : []
  const parentVersion = data?.versions.find((v) => v.id === selectedVersion?.parentVersionId)
  return <section className={`report-workbench${open ? ' is-chat-open' : ''}`} aria-label="报告与对话工作台">
    <div className="report-workbench-toolbar">
      <div><label htmlFor="report-version">报告版本 </label><select id="report-version" value={versionId} disabled={busy || !data?.versions.length}
        onChange={(e) => { const id = e.target.value; setVersionId(id); setLeaf(id); setProgress(null); remember(id, id) }}>
        {!data?.versions.length && <option value="">原始报告</option>}
        {data?.versions.map((v) => <option key={v.id} value={v.id}>V{v.reportVersion}{v.parentVersionId ? ' · 修订版' : ' · 初版'}</option>)}
      </select></div>
      <button type="button" className="secondary-button" onClick={() => setOpen(!open)} aria-expanded={open} aria-controls="report-discussion">{open ? '收起对话' : '报告对话'} <span aria-hidden="true">↗</span></button>
    </div>
    {parentVersion && selectedVersion && <details className="version-diff"><summary>本版修改 · 对比 V{parentVersion.reportVersion}</summary>
      {selectedVersion.summaryChanged && <p>报告摘要已修改。</p>}
      {(selectedVersion.changedSections ?? []).map((index) => <details key={index}><summary>第 {index + 1} 节 · {shownReport.sections[index]?.heading}</summary>
        <p>修改前</p><ReportText text={parentVersion.report.sections[index]?.content ?? '新增章节'} />
        <p>修改后</p><ReportText text={shownReport.sections[index]?.content ?? ''} />
      </details>)}
    </details>}
    <div className="report-and-chat">
      <div className="report-reading" ref={reportRef}><ResearchReport report={shownReport} /></div>
      {open && <aside className="report-discussion" id="report-discussion" aria-label="报告对话">
        <div className="discussion-heading"><h2>围绕报告继续研究</h2><button type="button" className="text-button" onClick={() => setOpen(false)}>关闭对话</button></div>
        <button type="button" className="text-button" disabled={busy} onClick={() => {
          setError('')
          const abort = new AbortController(); controller.current = abort
          void refresh(abort.signal).then((next) => {
            const pending = [...next.turns].reverse().find((t) => t.status === 'pending')
            if (pending) void watch(pending.runId, abort)
          }).catch((e: Error) => setError(e.message))
        }}>刷新记录 / 恢复进度查看</button>
        <p className="discussion-help">沿用截至 {report.asOfDate} 的资料。发送后调用模型；查看记录不收费。</p>
        {!isComplete ? <p>请先从已保存进度完成研究，再开启报告对话。</p> : <>
          <label htmlFor="discussion-branch">从哪个节点继续</label>
          <select id="discussion-branch" value={leaf} disabled={busy || !data} onChange={(e) => {
            const id = e.target.value, turn = data?.turns.find((t) => t.id === id)
            const version = turn?.versionId ?? turn?.baseVersionId ?? id
            setLeaf(id); setVersionId(version); setProgress(null); remember(id, version)
            if (turn) void getAgentJob(turn.runId).then(setProgress).catch((e: Error) => setError(e.message))
          }}>
            {data?.versions.map((v) => <option key={v.id} value={v.id}>从 V{v.reportVersion} 开始新分支</option>)}
            {data?.turns.map((t, index) => <option key={t.id} value={t.id}>对话 {index + 1} · {t.userMessage.slice(0, 24)}{t.status === 'completed' ? '' : '（未完成）'}</option>)}
          </select>
          <ol className="discussion-messages" aria-live="polite">
            {!turns.length && <li className="discussion-empty">解释判断、核对证据，或提出修改。切换旧版本会另开分支。</li>}
            {turns.map((turn) => <li key={turn.id}>
              <p className="discussion-role">你 · {turn.action === 'revise' ? '修改报告' : '追问 / 补查'}</p><ReportText text={turn.userMessage} />
              <p className="discussion-role">研究助手</p>
              {turn.status === 'completed' ? <><ReportText text={turn.answer} /><p className="discussion-citations">{turn.citations.map((c, i) => {
                const source = turn.sources?.find((s) => s.sourceId === c.sourceId) ?? shownReport.sources.find((s) => s.sourceId === c.sourceId)
                return source ? <a key={i} href={`${source.url}${c.page ? `#page=${c.page}` : ''}`} target="_blank" rel="noreferrer">{source.title}{c.page ? ` · p.${c.page}` : ''} ↗ </a> : <span key={i}>{c.sourceId}{c.page ? ` · p.${c.page}` : ''} </span>
              })}</p>{turn.versionId && <p className="discussion-version">已另存报告版本</p>}</> : <>
                <p className="field-error">{turn.error?.message ?? '本次对话未结束；刷新记录可恢复进度查看。'}</p>
                {turn.status !== 'pending' && <button type="button" className="text-button" disabled={busy} onClick={() => retry(turn)}>保留已读证据，重新尝试</button>}
              </>}
            </li>)}
          </ol>
          {progress && <details className="discussion-progress" open={busy || undefined}><summary>本次对话的工具与执行记录 · {progress.modelCalls} 次模型调用</summary><ActivityPanel job={progress} live={busy} /></details>}
          <form onSubmit={(event) => void send(event)} className="discussion-form">
            <label htmlFor="followup-action">本次操作</label><select id="followup-action" value={action} disabled={busy} onChange={(e) => setAction(e.target.value as 'ask' | 'revise')}><option value="ask">追问 / 补查</option><option value="revise">修改正文并另存版本</option></select>
            <label htmlFor="followup-message">继续研究的问题</label><textarea id="followup-message" value={message} onChange={(e) => setMessage(e.target.value)} maxLength={4000} rows={5} required disabled={busy} placeholder="例如：第三节的判断有哪些反方证据？" />
            <div className="discussion-actions"><button type="button" className="text-button" disabled={busy} onMouseDown={(e) => e.preventDefault()} onClick={quoteSelection}>引用选中文字</button><span>{message.length} / 4000</span></div>
            <button className="primary-button" type="submit" disabled={busy || !data || !leaf || !message.trim() || data.turns.some((t) => t.id === leaf && t.status === 'pending')}>{busy ? '正在处理…' : action === 'revise' ? '修改并另存版本' : '发送追问'}</button>
            {busy && progress && <button className="text-button" type="button" onClick={() => { void cancelAgentJob(progress.taskId).catch((e: Error) => setError(e.message)) }}>停止本次对话</button>}
            {action === 'revise' && <p className="discussion-help">本轮修改正文 / 摘要，保留原图表和数据表。</p>}
          </form>
        </>}
        {error && <p role="alert" className="field-error">{error}</p>}
      </aside>}
    </div>
  </section>
}
