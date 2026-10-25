import { useEffect, useState } from 'react'
import { getAgentActivity } from '../../api/research'
import type { ResearchActivity } from '../../api/research'
import { ActivityPanel } from './ActivityPanel'
import { activityTotals, loadAncestors, parentRun } from './activityHistory'

const STATUS: Record<string, string> = { queued: '等待中', running: '进行中', completed: '已完成', partial: '部分结果', failed: '失败', cancelled: '已停止' }

export function ResearchHistory({ job, live }: { job: ResearchActivity; live: boolean }) {
  const parent = parentRun(job)
  const [history, setHistory] = useState<{ taskId: string; runs: ResearchActivity[]; warning: string } | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    void loadAncestors(job, getAgentActivity, controller.signal).then((result) => {
      if (!controller.signal.aborted) setHistory({ taskId: job.taskId, ...result })
    })
    return () => controller.abort()
    // 当前调用的轮询只更新本次面板，不反复读取已停止的父任务。
  }, [job.taskId, parent])
  const loaded = history?.taskId === job.taskId ? history : null
  const runs = [...(loaded?.runs ?? []), job], total = activityTotals(runs)
  const loading = Boolean(parent && !loaded)
  return <details className="activity-replay" open={live || undefined}>
    <summary><strong>查看完整研究过程与工具记录</strong><span>{loading ? '正在读取接续历史…' : `累计 ${total.calls} 次模型调用 · ${total.count} 次运行`}</span></summary>
    <p className="activity-meter" data-testid="activity-total">{loading ? '正在读取历史，当前仅显示本次用量' : loaded?.warning ? '已读记录累计' : '全部运行累计'}：{total.calls} 次调用 · {(total.usage.total_tokens ?? 0).toLocaleString()} tokens · 本次 {job.modelCalls} 次调用</p>
    {loaded?.warning && <p role="status">{loaded.warning}</p>}
    {runs.length > 1 && <p className="activity-meter">按开始到接续顺序展示；累计为各次运行已返回的用量，中断时尚未返回的用量以模型服务账单为准。</p>}
    {runs.map((run, index) => <details className="activity-run" key={run.taskId} data-run-id={run.taskId} open={run.taskId === job.taskId || undefined}>
      <summary>第 {index + 1} 次运行 · {STATUS[run.status]} · {run.modelCalls} 次模型调用{run.taskId === job.taskId ? ' · 本次' : ''}</summary>
      <p className="activity-meter"><a href={`?task=${run.taskId}`}>打开这次运行</a> · {run.taskId}</p>
      <ActivityPanel job={run} live={run.taskId === job.taskId && live} />
    </details>)}
  </details>
}
