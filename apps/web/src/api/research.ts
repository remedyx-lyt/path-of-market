import { z } from 'zod'
import type { DraftErrors, ReportOmen, ResearchDraft } from '../features/research-lab/researchDraft'
import { activityJobSchema, agentReportSchema, errorBodySchema, jobSchema, mockReportSchema, modelReportSchema, sessionListSchema, validationIssueSchema } from './researchSchemas'

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export type MockResearchReport = ResearchDraft & {
  mode: 'mock'
  isMock: true
  title: string
  summary: string
  sections: { heading: string; content: string }[]
  sources: string[]
  toolCalls: Record<string, string>[]
}

export type ModelResearchReport = Omit<MockResearchReport, 'mode' | 'isMock'> & {
  mode: 'model'
  isMock: false
  asOfDate: string
  evidenceStatus: 'not_retrieved'
  limitations: string[]
  run: {
    taskId: string; status: 'completed'; states: string[]; model: string
    startedAt: string; finishedAt: string; stopReason: 'model_response_received'
  }
}
export type EvidenceSource = { sourceId: string; kind: 'document' | 'market' | 'web'; title: string; url: string; publishedAt: string; pageCount?: number; retrievedAt?: string; citationEligible?: boolean; dateStatus?: string }
export type ReadCoverage = { sourceId: string; pageCount: number; processedPages: number[]; processedCharacters: number; textComplete: boolean; batches: number; emptyTextPages: number[]; unit?: 'segment' | 'page'; fetchComplete?: boolean; fetchedCharacters?: number; readingComplete?: boolean; visuallyProcessedPages?: number[] }
export type MarketSeries = { date: string; close: number; adjustedClose: number; volume: number }
export type MarketData = {
  provider: string; currency: string; actualStart: string; actualEnd: string; retrievedAt: string
  series: MarketSeries[]; sourceUrls: string[]; limitations: string[]
  metrics: { tradingDays: number; firstRawClose: number; lastRawClose: number; adjustedChangePct: number; maxCloseDrawdownPct: number; annualizedDailyVolatilityPct: number | null; drawdownPeakDate: string; drawdownTroughDate: string; formula: string }
}
export type FinancialRow = {
  year: number; periodLabel: string; values: Record<string, number>
  yoy: Record<string, { value: number | null; reason: string }>
  evidence: Record<string, { sourceId: string; page: number; rawValue: string; unit: string; verification: string }>
}
export type FinancialData = {
  schemaVersion: 1; datasets: { id: string; label: string; rows: FinancialRow[] }[]
  charts: { id: string; datasetId: string; title: string; type: 'bar' | 'line'; keys: string[]; valueKind: 'amount' | 'yoy' | 'ratio'; unit: string; topic?: string }[]
  labels: Record<string, string>; gaps: string[]; method: string
}
export type SectionDiagram = { kind: 'flow' | 'cards'; title: string; nodes: { label: string; detail: string; citations: { sourceId: string; page?: number | null }[] }[] }
export type BusinessData = {
  schemaVersion: 1; method: string; gaps: string[]
  datasets: { id: string; dimension: string; period: string; label: string; rows: {
    year: number; periodLabel: string; total: number; totalEvidence: FinancialRow['evidence'][string]
    items: { label: string; value: number; share: number; derived: boolean; sourceId?: string; page?: number; rawValue?: string; unit?: string; quote?: string }[]
  }[] }[]
}
/** 模型根据原文自行做的数据表；verification 是程序逐格核对结果（unmatched 为未在所引原页找到的 [行, 列]）。 */
export type SectionTable = {
  title: string; unit: string; labelHeader?: string; columns: string[]; note: string
  rows: { label: string; cells: string[]; sourceId: string; page: number | null; alsoFrom?: { sourceId: string; page?: number | null }[]; note?: string }[]
  chart: 'none' | 'bar' | 'line'; chartColumns: number[]
  verification?: { checkedCells: number; matchedCells: number; unmatched: number[][] }
}
export type FigurePlan = { sectionIndex: number; financialChartIds: string[]; businessDatasetIds: string[]; diagram: SectionDiagram | null; gap: string | null }
export type AgentResearchReport = ResearchDraft & {
  mode: 'agent'; isMock: false; asOfDate: string; evidenceStatus: 'retrieved' | 'partial'; title: string; summary: string
  sections: { heading: string; content: string; topics?: string[]; omens?: ReportOmen[]; tables?: SectionTable[]; citations: { sourceId: string; page?: number | null }[] }[]
  sources: EvidenceSource[]; coverage: ReadCoverage[]; marketData: MarketData | null; limitations: string[]
  financialData?: FinancialData | null
  businessData?: BusinessData
  figurePlan?: FigurePlan[]
  methodUsage?: {
    status: string; reviewed: boolean; planCacheReused?: boolean; onDemandReads?: string[]
    references: { reference: string; characters: number; sha256: string; selectedBecause?: string[] }[]
    plan: { focus: string; checks: { topic: string; question: string; evidenceNeeded: string; figureIdea: string; methodReference: string; omen?: string | null }[]; unavailable: string[] } | null
  } | null
  omenCoverage?: OmenCoverage[]
  researchSkill?: { name: string; version: string; upstream: string }
  visualReadings?: { sourceId: string; pages: number[]; origin: string; cacheReused: boolean; observations: { page: number; summary: string; uncertainties: string[] }[] }[]
  toolCalls: { toolCallId: string; name: string; status: string; errorCode?: string }[]
  run: { taskId: string; sessionId: string; status: 'completed' | 'partial'; model: string; stopReason: string; modelCalls: number; steps: number; usage: Record<string, number>; reviewOutcome?: string | null }
}
/** 每个所选预兆的覆盖：程序核对章节标记与关键要素，内容充分性由模型自评；capabilityGaps 是当前工具拿不到的资料。 */
export type OmenCoverage = {
  omen: ReportOmen; name: string; covered: boolean; coverageScope: string; verification: string
  sections: string[]; addressed: string[]; missingItems: string[]; capabilityGaps: string[]; skillsRead: string[]; planChecks: number
}
/** 研究事件（JSONL 方向的事件结构：id/parentId/type/timestamp 加各类事件的结构化字段，供活动流展示）。 */
export type JobEvent = {
  id: string; parentId: string | null; type: string; message: string; timestamp: string
  phase?: string; toolCallId?: string; name?: string; label?: string; summary?: string; result?: string; status?: string
  durationMs?: number; modelCall?: number; purpose?: string; usage?: Record<string, number>; title?: string
  focus?: string; checks?: { question: string; topic: string; omen?: string | null }[]
  summaryText?: string; beforeCharacters?: number; afterCharacters?: number; compactionCount?: number
  parentTaskId?: string; previousModelCalls?: number
}
export type ResearchJob = {
  taskId: string; status: 'queued' | 'running' | 'completed' | 'partial' | 'failed' | 'cancelled'; target: string
  progress: string; modelCalls: number; usage: Record<string, number>; coverage: ReadCoverage[]
  phase?: string
  parentTaskId?: string | null
  persistence?: { unsent: number; lastError?: string | null } | null
  events: JobEvent[]
  report: AgentResearchReport | null; error: { code: string; message: string } | null
}
export type ResearchActivity = Pick<ResearchJob, 'taskId' | 'status' | 'target' | 'progress' | 'modelCalls' | 'usage' | 'phase' | 'events' | 'parentTaskId'>
export type ResearchReport = MockResearchReport | ModelResearchReport | AgentResearchReport
export type ResearchMode = 'mock' | 'model' | 'agent'

export class ResearchApiError extends Error {
  readonly code: string
  readonly fieldErrors: DraftErrors

  constructor(message: string, code: string, fieldErrors: DraftErrors = {}) {
    super(message)
    this.name = 'ResearchApiError'
    this.code = code
    this.fieldErrors = fieldErrors
  }
}

/** 运行时检查已确保报告与当前模式对应；返回原始响应，保留 schema 未列出的字段。 */
export function isAgentReport(value: unknown): value is AgentResearchReport {
  return agentReportSchema.safeParse(value).success
}

function errorCode(body: unknown, fallback: string) {
  const parsed = errorBodySchema.safeParse(body)
  return parsed.success ? parsed.data.error.code : fallback
}

function validationErrors(body: unknown): DraftErrors {
  const errors: DraftErrors = {}
  const detail = z.object({ detail: z.array(z.unknown()) }).safeParse(body)
  if (!detail.success) return errors
  const labels = { target: '研究对象', question: '研究问题', userStyle: '研究偏好', omens: '研究预兆', asOfDate: '研究截止日期' }
  const limits = { target: 120, question: 2000, userStyle: 500 }
  for (const entry of detail.data.detail) {
    const parsed = validationIssueSchema.safeParse(entry)
    if (!parsed.success) continue
    const issue = parsed.data
    const field = issue.loc[1]
    if (typeof field !== 'string' || !Object.hasOwn(labels, field)) continue
    const key = field as keyof typeof labels
    if (key === 'asOfDate') errors.asOfDate = '请填写有效的研究截止日期。'
    else if (key === 'omens') errors.omens = '请选择列表中的研究预兆。'
    else if (issue.type === 'string_too_long') errors[key] = `${labels[key]}最多 ${limits[key]} 个字符。`
    else if (issue.type === 'missing' || issue.type === 'string_too_short') errors[key] = `请填写${labels[key]}。`
    else errors[key] = `${labels[key]}未通过校验，请检查后重试。`
  }
  return errors
}

const ERROR_MESSAGES: Record<string, string> = {
  SERVER_UNAVAILABLE: '无法连接应用服务，请检查本地服务是否启动。',
  AGENT_UNAVAILABLE: '研究服务暂时不可用，请稍后重试。',
  AGENT_TIMEOUT: '研究服务响应超时，请稍后重试。',
  AGENT_ERROR: '研究服务暂时无法完成请求，请稍后重试。',
  AGENT_INVALID_RESPONSE: '研究服务返回了无法识别的结果，请稍后重试。',
  INVALID_JSON: '请求内容无法解析，请重新填写后重试。',
  MODEL_NOT_CONFIGURED: '请在项目根目录 .env 的 DEEPSEEK_API_KEY= 后填写密钥并保存，然后重试。',
  MODEL_CONFIG_ERROR: '模型配置无效，请检查 .env 的接口地址、模型名称和等待上限。',
  MODEL_AUTH_FAILED: '模型密钥验证失败，请检查密钥和账户权限。',
  MODEL_BALANCE_INSUFFICIENT: '模型账户余额或额度不足，请到供应商平台检查。',
  MODEL_RATE_LIMITED: '模型调用过于频繁或额度受限，请稍后再试。',
  MODEL_UPSTREAM_ERROR: '模型接口暂时无法完成请求，请检查模型配置或稍后重试。',
  MODEL_TIMEOUT: '模型响应超时，请重试或缩短问题。',
  MODEL_UNAVAILABLE: '无法连接模型接口，请检查网络和接口地址。',
  MODEL_INVALID_RESPONSE: '模型未返回完整且有效的报告，请重试或调整输出长度。',
}

/** 浏览器只请求同源 Java API；限制完整响应等待时间，支持主动取消。 */
export async function generateReport(draft: ResearchDraft, signal: AbortSignal, mode: ResearchMode, asOfDate: string, onProgress?: (job: ResearchJob) => void): Promise<ResearchReport> {
  if (mode === 'agent') return generateAgentReport(draft, signal, asOfDate, onProgress)
  const controller = new AbortController()
  let timedOut = false
  const cancel = () => controller.abort()
  signal.addEventListener('abort', cancel, { once: true })
  if (signal.aborted) cancel()
  const timer = window.setTimeout(() => { timedOut = true; controller.abort() }, mode === 'model' ? 90_000 : 15_000)
  try {
    const response = await fetch(`/api/research/${mode}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8', Accept: 'application/json' },
      body: JSON.stringify(mode === 'model' ? { ...draft, asOfDate } : draft),
      signal: controller.signal,
    })
    const raw = await response.text()
    let body: unknown
    try { body = JSON.parse(raw) }
    catch {
      throw new ResearchApiError(
        response.ok ? '返回内容无法识别，请稍后重试。' : '应用服务返回异常，请稍后重试。',
        'INVALID_RESPONSE',
      )
    }
    if (!response.ok) {
      if (response.status === 422 && isObject(body)) {
        throw new ResearchApiError('输入校验未通过，请检查标出的内容后重试。', 'VALIDATION_ERROR', validationErrors(body))
      }
      const code = errorCode(body, 'HTTP_ERROR')
      const message = Object.hasOwn(ERROR_MESSAGES, code) ? ERROR_MESSAGES[code] : '报告生成失败，请稍后重试。'
      throw new ResearchApiError(message, code)
    }
    if (!(mode === 'model' ? modelReportSchema : mockReportSchema).safeParse(body).success) throw new ResearchApiError('返回的报告格式不正确，请稍后重试。', 'INVALID_REPORT')
    // 上面的运行时检查已确保报告与当前模式对应；返回原始响应，保留 schema 未列出的字段。
    return body as ResearchReport
  } catch (error) {
    if (signal.aborted) throw new ResearchApiError('请求已取消。', 'CANCELLED')
    if (timedOut) throw new ResearchApiError('等待报告超时，请重试或检查本地服务。', 'CLIENT_TIMEOUT')
    if (error instanceof ResearchApiError) throw error
    throw new ResearchApiError('无法连接应用服务，请检查连接后重试。', 'NETWORK_ERROR')
  } finally {
    window.clearTimeout(timer)
    signal.removeEventListener('abort', cancel)
  }
}


async function jobRequest(path: string, method: string, signal?: AbortSignal, body?: unknown, activityOnly = false): Promise<ResearchJob> {
  let response: Response
  try {
    response = await fetch(`/api/research/jobs${path}`, { method, signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(20_000)]) : AbortSignal.timeout(20_000),
      headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })
  } catch {
    if (signal?.aborted) throw new ResearchApiError('已停止等待研究。', 'CANCELLED')
    throw new ResearchApiError('无法读取研究进度。任务可能仍在运行，可点击恢复研究。', 'NETWORK_ERROR')
  }
  let result: unknown
  try { result = await response.json() } catch { throw new ResearchApiError('任务响应无法识别。', 'INVALID_RESPONSE') }
  if (!response.ok) {
    if (response.status === 422 && isObject(result)) throw new ResearchApiError('研究输入未通过校验。', 'VALIDATION_ERROR', validationErrors(result))
    const code = errorCode(result, 'RESEARCH_FAILED')
    const extra: Record<string, string> = { RESEARCH_BUSY: '已有研究正在运行，请先恢复或停止该任务。', RESEARCH_NOT_FOUND: '任务不存在或服务已重启，请重新开始。' }
    throw new ResearchApiError(ERROR_MESSAGES[code] || extra[code] || '研究任务未能完成。', code)
  }
  if (!(activityOnly ? activityJobSchema : jobSchema).safeParse(result).success) throw new ResearchApiError('任务或报告格式不正确。', 'INVALID_REPORT')
  return result as ResearchJob
}

export type SessionSummary = { sessionId: string; runId: string; createdAt: string; target: string; question: string; status: string; title?: string }

/** 最近的研究记录（会话 JSONL 中保存，重启后仍在）。失败时返回空列表，不影响研究页面。 */
export async function listSessions(signal?: AbortSignal): Promise<SessionSummary[]> {
  try {
    const response = await fetch('/api/research/sessions?limit=10', { signal })
    const parsed = sessionListSchema.safeParse(await response.json())
    return response.ok && parsed.success ? parsed.data.sessions : []
  } catch {
    return []
  }
}

export async function cancelAgentJob(taskId: string) { return jobRequest(`/${taskId}`, 'DELETE') }
export async function getAgentJob(taskId: string, signal?: AbortSignal) { return jobRequest(`/${taskId}`, 'GET', signal) }
/** 只读历史活动，不校验/渲染旧报告，不启动模型。 */
export async function getAgentActivity(taskId: string, signal?: AbortSignal): Promise<ResearchActivity> { return jobRequest(`/${taskId}`, 'GET', signal, undefined, true) }

/** 接续未完成任务，复用已读上下文；会产生新的模型调用，普通查看/恢复轮询不会调用此入口。 */
export async function continueAgentJob(taskId: string, signal: AbortSignal, onProgress?: (job: ResearchJob) => void) {
  const job = await jobRequest(`/${taskId}/continue`, 'POST', signal)
  sessionStorage.setItem('path-of-market-active-job', job.taskId)
  window.history.replaceState(null, '', `?task=${job.taskId}`)
  onProgress?.(job)
  return waitForAgent(job.taskId, signal, onProgress)
}

export async function waitForAgent(taskId: string, signal: AbortSignal, onProgress?: (job: ResearchJob) => void): Promise<AgentResearchReport> {
  try {
    for (let i = 0; i < 1100; i++) {
      const job = await jobRequest(`/${taskId}`, 'GET', signal)
      onProgress?.(job)
      if (!['queued', 'running'].includes(job.status)) {
        sessionStorage.removeItem('path-of-market-active-job')
        if (job.report) return job.report
        throw new ResearchApiError(job.error?.message || '任务已停止，尚无报告。', job.error?.code || 'RESEARCH_STOPPED')
      }
      await new Promise<void>((resolve, reject) => {
        const cancel = () => { clearTimeout(timer); reject(new ResearchApiError('请求已取消。', 'CANCELLED')) }
        const timer = window.setTimeout(() => { signal.removeEventListener('abort', cancel); resolve() }, 1500)
        if (signal.aborted) cancel()
        else signal.addEventListener('abort', cancel, { once: true })
      })
    }
    throw new ResearchApiError('等待已达上限，可恢复研究查看任务状态。', 'CLIENT_TIMEOUT')
  } catch (error) { throw error }
}

async function generateAgentReport(draft: ResearchDraft, signal: AbortSignal, asOfDate: string, onProgress?: (job: ResearchJob) => void) {
  const job = await jobRequest('', 'POST', signal, { ...draft, asOfDate, includeMarket: true })
  sessionStorage.setItem('path-of-market-active-job', job.taskId)
  onProgress?.(job)
  return waitForAgent(job.taskId, signal, onProgress)
}
