import { z } from 'zod'
import { agentReportSchema } from './researchSchemas'
import type { AgentResearchReport, ResearchJob } from './research'
import { getAgentJob } from './research'

const turnSchema = z.object({
  id: z.string(), runId: z.string(), parentTurnId: z.string(), baseVersionId: z.string(),
  requestId: z.string(), userMessage: z.string(), action: z.enum(['ask', 'revise']),
  answer: z.string(), status: z.enum(['pending', 'completed', 'failed', 'cancelled']),
  versionId: z.string().nullish(), error: z.object({ code: z.string(), message: z.string() }).nullish(),
  citations: z.array(z.object({ sourceId: z.string(), page: z.number().nullish() })),
  sources: z.array(z.object({ sourceId: z.string(), title: z.string(), url: z.url().startsWith('https://') })).optional(),
})
const discussionSchema = z.object({
  sessionId: z.string(), rootTaskId: z.string(), turns: z.array(turnSchema),
  versions: z.array(z.object({ id: z.string(), runId: z.string(), reportVersion: z.number(),
    parentVersionId: z.string().optional(), changedSections: z.array(z.number()).optional(), summaryChanged: z.boolean().optional(), report: agentReportSchema })),
})
export type DiscussionTurn = z.infer<typeof turnSchema>
export type Discussion = Omit<z.infer<typeof discussionSchema>, 'versions'> & { versions: {
  id: string; runId: string; reportVersion: number; parentVersionId?: string; changedSections?: number[]; summaryChanged?: boolean; report: AgentResearchReport
}[] }

export async function getDiscussion(taskId: string, signal?: AbortSignal): Promise<Discussion> {
  const response = await fetch(`/api/research/jobs/${taskId}/discussion`, { signal })
  if (!response.ok) throw new Error('暂时无法读取对话与版本，请刷新记录重试。')
  const result: unknown = await response.json()
  // 校验后返回原始投影，保留报告中的usage、方法和图表扩展字段；zod默认会剥离未声明字段。
  if (!discussionSchema.safeParse(result).success) throw new Error('保存的报告或对话结构无法读取，请刷新记录或检查后端日志；原记录未改动。')
  return result as Discussion
}

export async function sendFollowup(taskId: string, body: { message: string; action: 'ask' | 'revise'; parentId: string; requestId: string }, signal: AbortSignal) {
  const response = await fetch(`/api/research/jobs/${taskId}/chat`, { method: 'POST', signal,
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const result = await response.json()
  if (!response.ok) throw new Error(typeof result.error?.message === 'string' ? result.error.message : '对话请求未能启动，请检查输入并刷新记录。')
  // 仍由统一任务读取入口校验快照；POST只返回新运行标识。
  const task = z.string().regex(/^[0-9a-f-]{36}$/i).parse(result.taskId)
  return getAgentJob(task, signal)
}

export async function pollFollowup(taskId: string, signal: AbortSignal, onProgress: (job: ResearchJob) => void): Promise<ResearchJob> {
  let unsavedPolls = 0
  for (let i = 0; i < 1000; i++) {
    const job = await getAgentJob(taskId, signal)
    onProgress(job)
    if (!['queued', 'running'].includes(job.status) && !(job.persistence?.unsent)) return job
    if (!['queued', 'running'].includes(job.status) && ++unsavedPolls >= 10) throw new Error('本次执行已结束，但会话尚未保存成功。请保留页面并检查后端存储，再刷新记录；原报告仍保留。')
    await new Promise<void>((resolve, reject) => {
      const cancel = () => { clearTimeout(timer); reject(new DOMException('Stopped polling', 'AbortError')) }
      const timer = window.setTimeout(() => { signal.removeEventListener('abort', cancel); resolve() }, 1200)
      if (signal.aborted) cancel()
      else signal.addEventListener('abort', cancel, { once: true })
    })
  }
  throw new Error('等待时间已到，可刷新记录恢复查看；不会自动重发付费请求。')
}

/** UI与模型都只沿所选节点向上，其他分支不会混入当前对话。 */
export function selectedTurns(turns: DiscussionTurn[], leaf: string): DiscussionTurn[] {
  const byId = new Map(turns.map((turn) => [turn.id, turn]))
  const result: DiscussionTurn[] = [], seen = new Set<string>()
  while (byId.has(leaf) && !seen.has(leaf)) {
    seen.add(leaf)
    const turn = byId.get(leaf)!
    result.unshift(turn)
    leaf = turn.parentTurnId
  }
  return result
}
