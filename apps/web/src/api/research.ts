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

function validationErrors(body: Record<string, unknown>): DraftErrors {
  const errors: DraftErrors = {}
  if (!Array.isArray(body.detail)) return errors
  const labels = { target: '研究对象', question: '研究问题', userStyle: '研究偏好', omens: '研究预兆' }
  const limits = { target: 120, question: 2000, userStyle: 500 }
  for (const issue of body.detail) {
    if (!isObject(issue) || !Array.isArray(issue.loc)) continue
    const field = issue.loc[1]
    if (typeof field !== 'string' || !Object.hasOwn(labels, field)) continue
    const key = field as keyof typeof labels
    if (key === 'omens') errors.omens = '请选择列表中的研究预兆。'
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
}

/** 浏览器只请求同源 Java API；限制完整响应等待时间，支持主动取消。 */
export async function generateMockReport(draft: ResearchDraft, signal: AbortSignal): Promise<MockResearchReport> {
  const controller = new AbortController()
  let timedOut = false
  const cancel = () => controller.abort()
  signal.addEventListener('abort', cancel, { once: true })
  if (signal.aborted) cancel()
  const timer = window.setTimeout(() => { timedOut = true; controller.abort() }, 15_000)
  try {
    const response = await fetch('/api/research/mock', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8', Accept: 'application/json' },
      body: JSON.stringify(draft),
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
    if (!isMockReport(body)) throw new ResearchApiError('返回的报告格式不正确，请稍后重试。', 'INVALID_REPORT')
    return body
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
