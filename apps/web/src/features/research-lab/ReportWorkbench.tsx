import { memo, useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import type { AgentResearchReport, ResearchJob } from '../../api/research'
import { cancelAgentJob, getAgentJob } from '../../api/research'
import { getDiscussion, pollFollowup, selectedTurns, sendFollowup } from '../../api/discussion'
import type { Discussion, DiscussionTurn } from '../../api/discussion'
import { ResearchReport } from './ResearchReport'
import { ReportText } from './ReportText'
import { DiscussionMessages } from './DiscussionMessages'
import type { PendingMessage } from './DiscussionMessages'
import { PanelResizeHandle } from './PanelResizeHandle'
import { readPanelNumber, savePanelNumber } from './panelLayout'

// 聊天轮询不重复渲染整份长报告及其图表；切换版本时仍正常更新。
const StableResearchReport = memo(ResearchReport)

export function ReportWorkbench({ report }: { report: AgentResearchReport }) {
  const [open, setOpen] = useState(false)
  const [reportVisible, setReportVisible] = useState(true)
  const [compact, setCompact] = useState(false)
  const [chatWidth, setChatWidth] = useState(() => readPanelNumber('pm-chat-width', 480, 320, 1400))
  const [fontSize, setFontSize] = useState(() => readPanelNumber('pm-reading-font', 16, 14, 22))
  const [data, setData] = useState<Discussion | null>(null)
  const [versionId, setVersionId] = useState('')
  const [leaf, setLeaf] = useState('')
  const [message, setMessage] = useState('')
  const [action, setAction] = useState<'ask' | 'revise'>('ask')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState<ResearchJob | null>(null)
  const [pending, setPending] = useState<PendingMessage | null>(null)
  const controller = useRef<AbortController | null>(null)
  const request = useRef<{ signature: string; id: string } | null>(null)
  const reportRef = useRef<HTMLDivElement>(null)
  const workbenchRef = useRef<HTMLElement>(null)
  const selectedVersion = data?.versions.find((v) => v.id === versionId)
  const shownReport = selectedVersion?.report ?? report
  const isComplete = report.run.status === 'completed'

  useEffect(() => {
    const host = workbenchRef.current
    if (!host) return
    const observer = new ResizeObserver(() => setCompact(host.clientWidth <= 820))
    observer.observe(host)
    return () => observer.disconnect()
  }, [])

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
      window.dispatchEvent(new Event('path-of-market-memory-changed'))
      const turn = next.turns.find((t) => t.runId === taskId)
      if (turn) {
        if (turn.status === 'pending' && !['queued', 'running'].includes(job.status)) {
          turn.status = job.status === 'cancelled' ? 'cancelled' : 'failed'
          turn.error = job.error ?? { code: 'RESEARCH_INTERRUPTED', message: '对话中途停止，已读证据可继续使用。' }
          setData({ ...next, turns: [...next.turns] })
        }
        setLeaf(turn.id)
        const id = turn.versionId ?? turn.baseVersionId
        setVersionId(id)
        remember(turn.id, id)
        setPending(null)
      }
      if (job.status !== 'completed') setError(job.error?.message ?? '本次对话未完成，可从已保存证据重试。')
    } catch (reason) {
      if (!abort.signal.aborted) setError(reason instanceof Error ? reason.message : '读取进度失败，请刷新记录。')
    } finally { if (controller.current === abort) { controller.current = null; setBusy(false) } }
  }, [refresh, remember])

  useEffect(() => {
    if (!isComplete) return
    const abort = new AbortController()
    controller.current = abort
    void refresh(abort.signal).then((next) => {
      if (abort.signal.aborted) return
      const params = new URLSearchParams(window.location.search)
      const chosen = params.get('chatNode')
      const chosenTurn = chosen ? next.turns.find((t) => t.id === chosen) : next.turns.at(-1)
      const requestedVersion = chosenTurn?.versionId ?? chosenTurn?.baseVersionId ?? params.get('version')
      const version = next.versions.find((v) => v.id === requestedVersion) ?? next.versions.at(-1)
      if (!version) return
      setVersionId(version.id)
      setLeaf(chosenTurn?.id ?? version.id)
      if (chosenTurn) {
        setOpen(true)
        if (chosenTurn.status !== 'pending') void getAgentJob(chosenTurn.runId, abort.signal).then(setProgress).catch(() => {})
      }
      const waiting = [...next.turns].reverse().find((t) => t.status === 'pending')
      if (waiting) { setOpen(true); setLeaf(waiting.id); void watch(waiting.runId, abort) }
      else controller.current = null
    }).catch((reason) => { if (!abort.signal.aborted) setError(reason instanceof Error ? reason.message : '读取记录失败。') })
    return () => { abort.abort(); controller.current?.abort(); controller.current = null }
  }, [isComplete, refresh, watch])

  async function send(event: FormEvent) {
    event.preventDefault()
    if (!message.trim() || !data || !leaf || busy) return
    const abort = new AbortController()
    controller.current = abort
    const text = message.trim()
    const signature = JSON.stringify({ message: text, action, leaf })
    if (request.current?.signature !== signature) request.current = { signature, id: crypto.randomUUID() }
    setPending({ message: text, action, parentId: leaf, requestId: request.current.id })
    setBusy(true); setOpen(true); setError(''); setProgress(null)
    try {
      const job = await sendFollowup(data.rootTaskId, { message: text, action, parentId: leaf, requestId: request.current.id }, abort.signal)
      setMessage(''); request.current = null; setProgress(job)
      await watch(job.taskId, abort)
    } catch (reason) {
      if (!abort.signal.aborted) {
        setError(reason instanceof Error ? reason.message : '发送结果未确认，请先刷新记录。')
        setBusy(false); controller.current = null
      }
    }
  }

  function chooseTurn(turn: DiscussionTurn) {
    setLeaf(turn.id); setVersionId(turn.versionId ?? turn.baseVersionId); setProgress(null)
    remember(turn.id, turn.versionId ?? turn.baseVersionId)
    void getAgentJob(turn.runId).then(setProgress).catch(() => {})
  }

  function retry(turn: DiscussionTurn) {
    chooseTurn(turn)
    setMessage(turn.userMessage); setAction(turn.action); setError(''); request.current = null
  }

  function closeChat() { setOpen(false); setReportVisible(true) }
  function toggleReport() {
    if (compact && open) { closeChat(); return }
    setReportVisible(!reportVisible)
    if (reportVisible) setOpen(true)
  }
  function focusChat() { setOpen(true); setReportVisible((value) => !value) }
  function changeFont(value: number) { setFontSize(value); savePanelNumber('pm-reading-font', value) }
  function quoteSelection() {
    const selection = window.getSelection()
    if (selection?.anchorNode && selection.focusNode && reportRef.current?.contains(selection.anchorNode) && reportRef.current.contains(selection.focusNode)) {
      const quote = selection.toString().trim().slice(0, 1800)
      if (quote) {
        const next = `${message}\n\n所选报告原文：\n${quote}`.trim()
        if (next.length > 4000) { setError('问题加引用超过4000字，请缩短。'); return }
        setMessage(next); setOpen(true); setError(''); return
      }
    }
    setError('请先在报告中选中要讨论的文字。')
  }

  const turns = data ? selectedTurns(data.turns, leaf) : []
  const latest = data?.turns.at(-1)
  const parentVersion = data?.versions.find((v) => v.id === selectedVersion?.parentVersionId)
  const panelStyle = { '--chat-width': `${chatWidth}px`, '--reading-font': `${fontSize}px` } as CSSProperties
  return <section className={`report-workbench${open ? ' is-chat-open' : ''}${!reportVisible ? ' is-report-hidden' : ''}`} aria-label="报告与对话工作台" style={panelStyle} ref={workbenchRef}>
    <div className="report-workbench-toolbar">
      <div className="pane-tabs">
        <button type="button" aria-pressed={reportVisible && (!compact || !open)} aria-controls="report-reading" onClick={toggleReport}>{compact && open ? '查看报告' : reportVisible ? '收起报告' : '展开报告'}</button>
        <button type="button" aria-expanded={open} aria-controls="report-discussion" onClick={() => open ? closeChat() : setOpen(true)}>{open ? '收起对话' : '报告对话'} ↗</button>
      </div>
      <div className="report-display-controls">
        <label htmlFor="report-version">版本</label><select id="report-version" value={versionId} disabled={busy || !data?.versions.length} onChange={(e) => {
          const id = e.target.value; setVersionId(id); setLeaf(id); setProgress(null); remember(id, id)
        }}>{!data?.versions.length && <option value="">初版</option>}{data?.versions.map((v) => <option key={v.id} value={v.id}>V{v.reportVersion}{v.parentVersionId ? ' · 修订' : ' · 初版'}</option>)}</select>
        <div className="reading-zoom" aria-label="阅读字号"><button type="button" aria-label="缩小文字" disabled={fontSize <= 14} onClick={() => changeFont(fontSize - 1)}>A−</button><span>{fontSize}</span><button type="button" aria-label="放大文字" disabled={fontSize >= 22} onClick={() => changeFont(fontSize + 1)}>A＋</button></div>
      </div>
    </div>
    <div className="report-and-chat">
      <div className="report-reading" id="report-reading" ref={reportRef} hidden={!reportVisible}>
        {parentVersion && selectedVersion && <details className="version-diff"><summary>本版修改 · 对比 V{parentVersion.reportVersion}</summary>
          {selectedVersion.summaryChanged && <p>报告摘要已修改。</p>}
          {(selectedVersion.changedSections ?? []).map((index) => <details key={index}><summary>第 {index + 1} 节 · {shownReport.sections[index]?.heading}</summary><p>修改前</p><ReportText text={parentVersion.report.sections[index]?.content ?? '新增章节'} /><p>修改后</p><ReportText text={shownReport.sections[index]?.content ?? ''} /></details>)}
        </details>}
        <StableResearchReport report={shownReport} />
      </div>
      {open && reportVisible && <PanelResizeHandle width={chatWidth} onChange={(value) => { setChatWidth(value); savePanelNumber('pm-chat-width', value) }} />}
      {open && <aside className="report-discussion" id="report-discussion" aria-label="报告对话">
        <div className="discussion-heading"><div><h2>报告对话</h2><span>{report.target} · 截至 {report.asOfDate}</span></div><div><button type="button" className="text-button" onClick={focusChat}>{reportVisible ? '放大对话' : '并排查看'}</button><button type="button" className="text-button" onClick={closeChat}>收起</button></div></div>
        {latest && latest.id !== leaf && !busy && <button className="latest-answer" type="button" onClick={() => chooseTurn(latest)}>有更新的对话 · 查看最新回复 ↓</button>}
        <details className="discussion-settings"><summary>对话选项与历史分支</summary>
          <button type="button" className="text-button" disabled={busy} onClick={() => {
            setError('')
            const abort = new AbortController(); controller.current = abort
            void refresh(abort.signal).then((next) => {
              const waiting = [...next.turns].reverse().find((t) => t.status === 'pending')
              if (waiting) { setLeaf(waiting.id); void watch(waiting.runId, abort) }
              else { const turn = next.turns.at(-1); if (turn) chooseTurn(turn); setPending(null) }
            }).catch((e: Error) => setError(e.message))
          }}>刷新记录 / 查看最新回复</button>
          <label htmlFor="discussion-branch">从哪个节点继续</label><select id="discussion-branch" value={leaf} disabled={busy || !data} onChange={(e) => {
            const turn = data?.turns.find((t) => t.id === e.target.value)
            if (turn) chooseTurn(turn)
            else { setLeaf(e.target.value); setVersionId(e.target.value); setProgress(null); remember(e.target.value, e.target.value) }
          }}>{data?.versions.map((v) => <option key={v.id} value={v.id}>从 V{v.reportVersion} 开始新分支</option>)}{data?.turns.map((t, index) => <option key={t.id} value={t.id}>对话 {index + 1} · {t.userMessage.slice(0, 24)}{t.status === 'completed' ? '' : '（未完成）'}</option>)}</select>
        </details>
        {!isComplete ? <p>请先完成研究，再开启报告对话。</p> : <>
          <DiscussionMessages turns={turns} report={shownReport} pending={pending} progress={progress} busy={busy} onRetry={retry} />
          <form onSubmit={(event) => void send(event)} className="discussion-form">
            <div className="composer-options"><label htmlFor="followup-action">本次操作</label><select id="followup-action" value={action} disabled={busy} onChange={(e) => setAction(e.target.value as 'ask' | 'revise')}><option value="ask">追问 / 补查</option><option value="revise">修改正文并另存版本</option></select><button type="button" className="text-button" disabled={busy} onMouseDown={(e) => e.preventDefault()} onClick={quoteSelection}>引用选中文字</button></div>
            <label className="sr-only" htmlFor="followup-message">继续研究的问题</label><textarea id="followup-message" value={message} onChange={(e) => setMessage(e.target.value)} maxLength={4000} rows={3} required disabled={busy} placeholder="围绕报告继续追问…" onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); e.currentTarget.form?.requestSubmit() }
            }} />
            <div className="discussion-actions"><span>{busy ? '正在研究与回答…' : 'Enter 发送 · Shift + Enter 换行'} · {message.length}/4000</span>
              {busy ? <button className="secondary-button" type="button" disabled={!progress} onClick={() => { if (progress) void cancelAgentJob(progress.taskId).catch((e: Error) => setError(e.message)) }}>停止</button> : <button className="primary-button" type="submit" disabled={!data || !leaf || !message.trim() || data.turns.some((t) => t.id === leaf && t.status === 'pending')}>{action === 'revise' ? '修改并另存' : '发送追问'} ↑</button>}
            </div>
            {action === 'revise' && <p className="discussion-help">仅修改正文 / 摘要，原图表和数据表保留。</p>}
            {error && <p role="alert" className="field-error">{error}</p>}
          </form>
        </>}
      </aside>}
    </div>
  </section>
}
