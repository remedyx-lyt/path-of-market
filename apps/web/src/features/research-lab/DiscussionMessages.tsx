import { useEffect, useRef } from 'react'
import type { AgentResearchReport, ResearchJob } from '../../api/research'
import type { DiscussionTurn } from '../../api/discussion'
import { ReportText } from './ReportText'
import { ActivityPanel } from './ActivityPanel'

export type PendingMessage = { message: string; action: 'ask' | 'revise'; requestId: string; parentId: string }

export function DiscussionMessages({ turns, report, pending, progress, busy, onRetry }: {
  turns: DiscussionTurn[]; report: AgentResearchReport; pending: PendingMessage | null;
  progress: ResearchJob | null; busy: boolean; onRetry: (turn: DiscussionTurn) => void;
}) {
  const scroll = useRef<HTMLDivElement>(null)
  const latest = useRef<HTMLDivElement>(null)
  const follows = useRef(true)
  const last = turns.at(-1)
  const optimistic = pending && !turns.some((t) => t.requestId === pending.requestId)
  const draft = busy && progress?.followup?.draft ? progress.followup.answer : ''
  useEffect(() => {
    const host = scroll.current, target = latest.current
    if (!host || !target) return
    if (optimistic) host.scrollTop = host.scrollHeight
    else host.scrollTop += (target.parentElement ?? target).getBoundingClientRect().top - host.getBoundingClientRect().top - 20
    follows.current = true
  }, [last?.id, pending?.requestId, optimistic])
  useEffect(() => {
    if (draft && follows.current && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight
  }, [draft])
  return <div className="discussion-scroll" ref={scroll} onScroll={() => {
    const host = scroll.current
    if (host) follows.current = host.scrollHeight - host.scrollTop - host.clientHeight < 96
  }}>
    <ol className="discussion-messages" aria-label="报告聊天记录">
      {!turns.length && !pending && <li className="discussion-empty"><strong>围绕这份报告，继续追问。</strong><p>解释判断、补查资料，或修改正文。答案会出现在这里。</p></li>}
      {turns.map((turn, index) => <li key={turn.id} className="discussion-turn" data-turn-id={turn.id}>
        <div className="user-message"><p className="discussion-role">你 · {turn.action === 'revise' ? '修改报告' : '追问 / 补查'}</p><ReportText text={turn.userMessage} /></div>
        <div className="assistant-answer" ref={index === turns.length - 1 && !optimistic ? latest : undefined}>
          <p className="discussion-role"><span className="assistant-symbol" aria-hidden="true">✦</span>研究助手</p>
          {turn.status === 'completed' ? <><ReportText text={turn.answer} />
            <details className="discussion-citations"><summary>参考来源 · {turn.citations.length}</summary>{turn.citations.map((c, i) => {
              const source = turn.sources?.find((s) => s.sourceId === c.sourceId) ?? report.sources.find((s) => s.sourceId === c.sourceId)
              return source ? <a key={i} href={`${source.url}${c.page ? `#page=${c.page}` : ''}`} target="_blank" rel="noreferrer">{source.title}{c.page ? ` · p.${c.page}` : ''} ↗</a> : <span key={i}>{c.sourceId}</span>
            })}</details>{turn.versionId && <p className="discussion-version">已另存报告版本</p>}</> : turn.status === 'pending' && busy ? <>
              <p className="reply-status" role="status">{draft ? '正在回答 · 内容尚未校验' : progress?.progress ?? '正在处理…'}</p>
              {draft && <ReportText text={draft} />}
            </> : <><p className="field-error">{turn.error?.message ?? '对话中断；可刷新记录恢复查看。'}</p>
              <button type="button" className="text-button" disabled={busy} onClick={() => onRetry(turn)}>保留已读证据，重新尝试</button></>}
        </div>
      </li>)}
      {optimistic && <li className="discussion-turn" data-testid="pending-user-message">
        <div className="user-message"><p className="discussion-role">你 · {pending.action === 'revise' ? '修改报告' : '追问 / 补查'}</p><ReportText text={pending.message} /></div>
        <div className="assistant-answer" ref={latest} aria-busy={busy}>
          <p className="discussion-role"><span className="assistant-symbol" aria-hidden="true">✦</span>研究助手</p>
          <p className="reply-status" role="status">{draft ? '正在回答 · 内容尚未校验' : busy ? progress?.progress ?? '已收到，正在开始研究…' : '发送结果待确认，请刷新记录。'}</p>
          {draft && <ReportText text={draft} />}
        </div>
      </li>}
    </ol>
    {progress && <details className="discussion-progress"><summary>工具与执行记录 · {progress.modelCalls} 次模型调用</summary><ActivityPanel job={progress} live={busy} /></details>}
  </div>
}
