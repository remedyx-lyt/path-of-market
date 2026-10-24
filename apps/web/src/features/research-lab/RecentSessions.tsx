import { useEffect, useState } from 'react'
import { listSessions } from '../../api/research'
import type { SessionSummary } from '../../api/research'

const STATUS: Record<string, string> = { completed: '已完成', partial: '部分结果', failed: '未完成', cancelled: '已取消' }

/** 最近研究：来自会话 JSONL（M2-1），服务重启后仍可打开报告与研究过程回放。 */
export function RecentSessions({ refreshKey }: { refreshKey: unknown }) {
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  useEffect(() => {
    const controller = new AbortController()
    void listSessions(controller.signal).then((items) => { if (!controller.signal.aborted) setSessions(items) })
    return () => controller.abort()
  }, [refreshKey])
  if (!sessions.length) return null
  return <section className="recent-sessions" aria-labelledby="recent-title">
    <h2 id="recent-title">最近研究</h2>
    <ol>{sessions.map((s) => <li key={s.runId}>
      <a href={`?task=${s.runId}`}>{s.title || `${s.target}研究`}</a>
      <p>{s.question.length > 60 ? s.question.slice(0, 60) + '…' : s.question}</p>
      <span>{new Date(s.createdAt).toLocaleString('zh-CN', { hour12: false, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })} · {STATUS[s.status] ?? s.status}</span>
    </li>)}</ol>
  </section>
}
