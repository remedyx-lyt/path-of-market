import { OMENS } from '../features/research-lab/researchDraft'
import type { DraftErrors, ReportOmen, ResearchDraft } from '../features/research-lab/researchDraft'

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
export type EvidenceSource = { sourceId: string; kind: 'document' | 'market'; title: string; url: string; publishedAt: string; pageCount?: number }
export type ReadCoverage = { sourceId: string; pageCount: number; processedPages: number[]; processedCharacters: number; textComplete: boolean; batches: number; emptyTextPages: number[] }
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
export type FigurePlan = { sectionIndex: number; financialChartIds: string[]; businessDatasetIds: string[]; diagram: SectionDiagram | null; gap: string | null }
export type AgentResearchReport = ResearchDraft & {
  mode: 'agent'; isMock: false; asOfDate: string; evidenceStatus: 'retrieved' | 'partial'; title: string; summary: string
  sections: { heading: string; content: string; topics?: string[]; citations: { sourceId: string; page?: number | null }[] }[]
  sources: EvidenceSource[]; coverage: ReadCoverage[]; marketData: MarketData | null; limitations: string[]
  financialData?: FinancialData | null
  businessData?: BusinessData
  figurePlan?: FigurePlan[]
  methodUsage?: { status: string; reviewed: boolean; references: { reference: string; characters: number; sha256: string }[]; plan: { focus: string; checks: { topic: string; question: string; evidenceNeeded: string; figureIdea: string; methodReference: string }[]; unavailable: string[] } } | null
  researchSkill?: { name: string; version: string; upstream: string }
  visualReadings?: { sourceId: string; pages: number[]; origin: string; cacheReused: boolean; observations: { page: number; summary: string; uncertainties: string[] }[] }[]
  toolCalls: { toolCallId: string; name: string; status: string; errorCode?: string }[]
  run: { taskId: string; sessionId: string; status: 'completed' | 'partial'; model: string; stopReason: string; modelCalls: number; steps: number; usage: Record<string, number> }
}
export type ResearchJob = {
  taskId: string; status: 'queued' | 'running' | 'completed' | 'partial' | 'failed' | 'cancelled'; target: string
  progress: string; modelCalls: number; usage: Record<string, number>; coverage: ReadCoverage[]
  events: { id: string; parentId: string | null; type: string; message: string; timestamp: string }[]
  report: AgentResearchReport | null; error: { code: string; message: string } | null
}
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

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isOmen(value: unknown): value is ReportOmen {
  return OMENS.some((omen) => omen.value === value)
}

function isMockReport(value: unknown): value is MockResearchReport {
  return isObject(value) && value.mode === 'mock' && value.isMock === true
    && ['target', 'question', 'userStyle', 'title', 'summary'].every((key) => typeof value[key] === 'string')
    && Array.isArray(value.omens) && value.omens.every(isOmen)
    && Array.isArray(value.sections) && value.sections.length > 0
    && value.sections.every((section) => isObject(section) && typeof section.heading === 'string' && typeof section.content === 'string')
    && Array.isArray(value.sources) && value.sources.length === 0
    && Array.isArray(value.toolCalls) && value.toolCalls.length === 0
}

function isModelReport(value: unknown): value is ModelResearchReport {
  return isObject(value) && value.mode === 'model' && value.isMock === false
    && value.evidenceStatus === 'not_retrieved' && typeof value.asOfDate === 'string'
    && ['target', 'question', 'userStyle', 'title', 'summary'].every((key) => typeof value[key] === 'string')
    && Array.isArray(value.omens) && value.omens.every(isOmen)
    && Array.isArray(value.sections) && value.sections.length >= 2 && value.sections.length <= 6
    && value.sections.every((section) => isObject(section) && typeof section.heading === 'string' && typeof section.content === 'string')
    && Array.isArray(value.sources) && value.sources.length === 0
    && Array.isArray(value.toolCalls) && value.toolCalls.length === 0
    && Array.isArray(value.limitations) && value.limitations.length > 0 && value.limitations.every((item) => typeof item === 'string')
    && isObject(value.run) && value.run.status === 'completed'
    && ['taskId', 'model', 'startedAt', 'finishedAt'].every((key) => typeof (value.run as Record<string, unknown>)[key] === 'string')
    && value.run.stopReason === 'model_response_received'
    && Array.isArray(value.run.states) && value.run.states.every((state) => typeof state === 'string')
}

function validationErrors(body: Record<string, unknown>): DraftErrors {
  const errors: DraftErrors = {}
  if (!Array.isArray(body.detail)) return errors
  const labels = { target: '研究对象', question: '研究问题', userStyle: '研究偏好', omens: '研究预兆', asOfDate: '研究截止日期' }
  const limits = { target: 120, question: 2000, userStyle: 500 }
  for (const issue of body.detail) {
    if (!isObject(issue) || !Array.isArray(issue.loc)) continue
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
      const code = isObject(body) && isObject(body.error) && typeof body.error.code === 'string' ? body.error.code : 'HTTP_ERROR'
      const message = Object.hasOwn(ERROR_MESSAGES, code) ? ERROR_MESSAGES[code] : '报告生成失败，请稍后重试。'
      throw new ResearchApiError(message, code)
    }
    if (!(mode === 'model' ? isModelReport(body) : isMockReport(body))) throw new ResearchApiError('返回的报告格式不正确，请稍后重试。', 'INVALID_REPORT')
    // 上面的运行时检查已确保报告与当前模式对应。
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

function validSource(source: unknown): source is EvidenceSource {
  return isObject(source) && typeof source.sourceId === 'string' && typeof source.title === 'string'
    && typeof source.publishedAt === 'string' && typeof source.url === 'string' && source.url.startsWith('https://') && ['document', 'market'].includes(String(source.kind))
}
function validCoverage(value: unknown): value is ReadCoverage {
  return isObject(value) && typeof value.sourceId === 'string' && Number.isInteger(value.pageCount)
    && Array.isArray(value.processedPages) && value.processedPages.every(Number.isInteger) && typeof value.textComplete === 'boolean'
    && typeof value.processedCharacters === 'number' && Number.isInteger(value.batches) && Array.isArray(value.emptyTextPages)
}
export function isAgentReport(value: unknown): value is AgentResearchReport {
  if (!isObject(value) || value.mode !== 'agent' || value.isMock !== false || !['retrieved', 'partial'].includes(String(value.evidenceStatus))) return false
  if (!['target', 'question', 'userStyle', 'asOfDate', 'title', 'summary'].every((key) => typeof value[key] === 'string')
    || !Array.isArray(value.omens) || !value.omens.every(isOmen) || !Array.isArray(value.sources) || !value.sources.every(validSource)
    || !Array.isArray(value.coverage) || !value.coverage.every(validCoverage) || !Array.isArray(value.sections) || value.sections.length < 2
    || !value.sections.every((s) => isObject(s) && typeof s.heading === 'string' && typeof s.content === 'string' && Array.isArray(s.citations)
      && s.citations.every((c) => isObject(c) && typeof c.sourceId === 'string' && (c.page == null || Number.isInteger(c.page))))
    || !Array.isArray(value.limitations) || !value.limitations.every((v) => typeof v === 'string') || !Array.isArray(value.toolCalls)
    || !value.toolCalls.every((t) => isObject(t) && typeof t.name === 'string' && typeof t.status === 'string' && typeof t.toolCallId === 'string')
    || !isObject(value.run) || !['completed', 'partial'].includes(String(value.run.status)) || typeof value.run.taskId !== 'string'
    || typeof value.run.model !== 'string' || typeof value.run.stopReason !== 'string' || typeof value.run.modelCalls !== 'number') return false
  if (value.marketData !== null) {
    const data = value.marketData
    if (!isObject(data) || !Array.isArray(data.series) || data.series.length < 2 || !isObject(data.metrics)
      || !data.series.every((r) => isObject(r) && typeof r.date === 'string' && typeof r.close === 'number' && Number.isFinite(r.close)
        && r.close > 0 && typeof r.adjustedClose === 'number' && Number.isFinite(r.adjustedClose) && r.adjustedClose > 0)
      || !['tradingDays', 'firstRawClose', 'lastRawClose', 'adjustedChangePct', 'maxCloseDrawdownPct'].every((k) => typeof data.metrics === 'object' && typeof (data.metrics as Record<string, unknown>)[k] === 'number')
      || !['provider', 'currency', 'actualStart', 'actualEnd', 'retrievedAt'].every((k) => typeof data[k] === 'string')
      || !Array.isArray(data.sourceUrls) || !data.sourceUrls.every((u) => typeof u === 'string' && u.startsWith('https://'))) return false
  }
  if (value.financialData != null && !validFinancialData(value.financialData, value.sources as EvidenceSource[])) return false
  if (value.businessData != null && !validBusinessData(value.businessData, value.sources as EvidenceSource[])) return false
  if (value.figurePlan != null && !validFigurePlan(value)) return false
  if (value.methodUsage != null) {
    const m = value.methodUsage
    if (!isObject(m) || typeof m.status!=='string' || typeof m.reviewed!=='boolean' || !Array.isArray(m.references)
      || !m.references.every((r) => isObject(r) && typeof r.reference==='string' && typeof r.characters==='number' && typeof r.sha256==='string')
      || !isObject(m.plan) || typeof m.plan.focus!=='string' || !Array.isArray(m.plan.checks)
      || !m.plan.checks.every((c) => isObject(c) && ['topic','question','evidenceNeeded','figureIdea','methodReference'].every((k) => typeof c[k]==='string'))
      || !Array.isArray(m.plan.unavailable) || !m.plan.unavailable.every((s) => typeof s==='string')) return false
  }
  if (value.researchSkill != null && (!isObject(value.researchSkill) || !['name','version','upstream'].every((k) => typeof (value.researchSkill as Record<string,unknown>)[k] === 'string'))) return false
  if (value.visualReadings != null && (!Array.isArray(value.visualReadings) || !value.visualReadings.every((r) => isObject(r)
    && typeof r.sourceId === 'string' && Array.isArray(r.pages) && r.pages.every((p) => Number.isInteger(p) && Number(p) > 0)
    && Array.isArray(r.observations) && r.observations.every((o) => isObject(o) && Number.isInteger(o.page) && typeof o.summary === 'string'
      && Array.isArray(o.uncertainties) && o.uncertainties.every((u) => typeof u === 'string'))))) return false
  return true
}

function validFinancialData(data: unknown, sources: EvidenceSource[]): data is FinancialData {
  const derived = new Set(['attributableMargin','grossMargin','liabilityRatio','rdExpenseRatio','rdInvestmentRatio'])
  const keys = new Set(['revenue','netProfit','recurringProfit','operatingCashFlow','totalAssets','netAssets','rdExpense',
    'operatingCost','totalLiabilities','cash','receivables','inventory','rdInvestment',...derived])
  if (!isObject(data) || data.schemaVersion !== 1 || !Array.isArray(data.datasets) || data.datasets.length > 4
    || !isObject(data.labels) || !Object.values(data.labels).every((s) => typeof s === 'string')
    || typeof data.method !== 'string' || !Array.isArray(data.gaps) || !data.gaps.every((g) => typeof g === 'string')) return false
  const ids = new Set<string>()
  for (const dataset of data.datasets) {
    if (!isObject(dataset) || typeof dataset.id !== 'string' || !['annual','h1','q1','q3'].includes(dataset.id) || ids.has(dataset.id)
      || typeof dataset.label !== 'string' || !Array.isArray(dataset.rows) || dataset.rows.length > 3) return false
    ids.add(dataset.id)
    let previous = 0
    for (const row of dataset.rows) {
      if (!isObject(row) || typeof row.periodLabel !== 'string' || typeof row.year !== 'number' || !Number.isInteger(row.year) || row.year <= previous
        || !isObject(row.values) || !isObject(row.yoy) || !isObject(row.evidence)) return false
      previous = row.year
      if (!Object.entries(row.values).every(([k,v]) => keys.has(k) && typeof v === 'number' && Number.isFinite(v))) return false
      if (!Object.entries(row.yoy).every(([k,v]) => keys.has(k) && isObject(v) && typeof v.reason === 'string'
        && (v.value === null || typeof v.value === 'number' && Number.isFinite(v.value)))) return false
      if (!Object.entries(row.evidence).every(([k,e]) => keys.has(k) && isObject(e) && Number.isInteger(e.page) && Number(e.page) > 0
        && typeof e.rawValue === 'string' && ['元','万元','亿元'].includes(String(e.unit)) && typeof e.verification === 'string'
        && sources.some((s) => s.kind === 'document' && s.sourceId === e.sourceId && Number(e.page) <= Number(s.pageCount)))) return false
      if (!Object.keys(row.values).every((k) => derived.has(k) || Object.hasOwn(row.evidence as object,k))) return false
    }
  }
  return Array.isArray(data.charts) && data.charts.length <= 36 && data.charts.every((c) => isObject(c) && typeof c.id === 'string'
    && typeof c.title === 'string' && ids.has(String(c.datasetId)) && ['bar','line'].includes(String(c.type))
    && ['amount','yoy','ratio'].includes(String(c.valueKind)) && ['亿元','%'].includes(String(c.unit))
    && Array.isArray(c.keys) && c.keys.length > 0 && c.keys.length <= 3 && c.keys.every((k) => typeof k === 'string' && keys.has(k)))
}

function validBusinessData(data: unknown, sources: EvidenceSource[]): data is BusinessData {
  const validEvidence = (e: unknown) => isObject(e) && typeof e.sourceId==='string' && Number.isInteger(e.page) && Number(e.page)>0
    && sources.some((s) => s.kind==='document' && s.sourceId===e.sourceId && Number(e.page)<=Number(s.pageCount))
  const number = (v: unknown): v is number => typeof v==='number' && Number.isFinite(v) && v>=0
  if (!isObject(data) || data.schemaVersion!==1 || typeof data.method!=='string' || !Array.isArray(data.gaps) || !data.gaps.every((g) => typeof g==='string')
    || !Array.isArray(data.datasets) || data.datasets.length>12) return false
  const ids = new Set<string>()
  return data.datasets.every((d) => {
    if (!isObject(d) || typeof d.id!=='string' || ids.has(d.id) || typeof d.label!=='string'
      || !['product','geography','industry'].includes(String(d.dimension)) || !['annual','h1','q1','q3'].includes(String(d.period))
      || !Array.isArray(d.rows) || d.rows.length<1 || d.rows.length>3) return false
    ids.add(d.id)
    let year = 0
    return d.rows.every((r) => {
      if (!isObject(r) || typeof r.year!=='number' || !Number.isInteger(r.year) || r.year<=year || typeof r.periodLabel!=='string'
        || !number(r.total) || r.total===0 || !validEvidence(r.totalEvidence) || !Array.isArray(r.items) || r.items.length<2 || r.items.length>30) return false
      year=r.year
      const labels = new Set<string>()
      let sum = 0
      return r.items.every((p) => {
        if (!isObject(p) || typeof p.label!=='string' || labels.has(p.label) || !number(p.value) || !number(p.share) || p.share>100.01
          || typeof p.derived!=='boolean' || Math.abs(p.share-p.value/Number(r.total)*100)>.01 || !p.derived && !validEvidence(p)) return false
        labels.add(p.label); sum+=p.value
        return true
      }) && Math.abs(sum-r.total)<=Math.max(.01,r.total*.0001)
    })
  })
}

function validFigurePlan(report: Record<string,unknown>): boolean {
  if (!Array.isArray(report.figurePlan) || !Array.isArray(report.sections) || report.figurePlan.length!==report.sections.length) return false
  const financial = report.financialData as FinancialData | undefined
  const business = report.businessData as BusinessData | undefined
  const sources = report.sources as EvidenceSource[]
  const seen = new Set<string>()
  return report.figurePlan.every((f,i) => {
    if (!isObject(f) || f.sectionIndex!==i || !Array.isArray(f.financialChartIds) || !Array.isArray(f.businessDatasetIds)
      || !f.financialChartIds.every((id) => financial?.charts.some((c) => c.id===id))
      || !f.businessDatasetIds.every((id) => business?.datasets.some((d) => d.id===id))) return false
    for (const id of [...f.financialChartIds,...f.businessDatasetIds]) { if (seen.has(String(id))) return false; seen.add(String(id)) }
    const d=f.diagram
    return d==null || isObject(d) && ['flow','cards'].includes(String(d.kind)) && typeof d.title==='string'
      && Array.isArray(d.nodes) && d.nodes.length>=2 && d.nodes.length<=6 && d.nodes.every((n) => isObject(n) && typeof n.label==='string' && typeof n.detail==='string'
        && Array.isArray(n.citations) && n.citations.length>0 && n.citations.every((c) => isObject(c) && sources.some((s) => s.sourceId===c.sourceId
          && (s.kind==='market' || Number.isInteger(c.page) && Number(c.page)>0 && Number(c.page)<=Number(s.pageCount)))))
  })
}

async function jobRequest(path: string, method: string, signal?: AbortSignal, body?: unknown): Promise<ResearchJob> {
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
    const code = isObject(result) && isObject(result.error) && typeof result.error.code === 'string' ? result.error.code : 'RESEARCH_FAILED'
    const extra: Record<string, string> = { RESEARCH_BUSY: '已有研究正在运行，请先恢复或停止该任务。', RESEARCH_NOT_FOUND: '任务不存在或服务已重启，请重新开始。' }
    throw new ResearchApiError(ERROR_MESSAGES[code] || extra[code] || '研究任务未能完成。', code)
  }
  if (!isObject(result) || typeof result.taskId !== 'string' || !/^[0-9a-f-]{36}$/i.test(result.taskId)
    || !['queued', 'running', 'completed', 'partial', 'failed', 'cancelled'].includes(String(result.status))
    || typeof result.progress !== 'string' || typeof result.modelCalls !== 'number' || !Array.isArray(result.events)
    || !result.events.every((e) => isObject(e) && typeof e.id === 'string' && typeof e.message === 'string' && typeof e.type === 'string')
    || !Array.isArray(result.coverage) || !result.coverage.every(validCoverage)
    || (result.report !== null && !isAgentReport(result.report))) throw new ResearchApiError('任务或报告格式不正确。', 'INVALID_REPORT')
  return result as ResearchJob
}

export async function cancelAgentJob(taskId: string) { return jobRequest(`/${taskId}`, 'DELETE') }
export async function getAgentJob(taskId: string, signal?: AbortSignal) { return jobRequest(`/${taskId}`, 'GET', signal) }

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
