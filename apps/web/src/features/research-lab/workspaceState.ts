import type { AgentResearchReport, ResearchApiError, ResearchJob, ResearchMode, ResearchReport } from '../../api/research'
import { EMPTY_DRAFT, EXAMPLE_DRAFT } from './researchDraft'
import type { DraftErrors, ReportOmen, ResearchDraft } from './researchDraft'

/** 研究工作台的页面状态。每个用户操作或请求阶段对应一个 action，状态变化集中在 reducer 中。 */
export type WorkspaceState = {
  draft: ResearchDraft
  preview: ResearchDraft | null
  errors: DraftErrors
  message: string
  report: ResearchReport | null
  mode: ResearchMode
  job: ResearchJob | null
  resumeId: string | null
  asOfDate: string
  requestError: ResearchApiError | null
  isGenerating: boolean
}

export type WorkspaceAction =
  | { type: 'fieldEdited'; field: 'target' | 'question' | 'userStyle'; value: string }
  | { type: 'omenToggled'; value: ReportOmen }
  | { type: 'dateEdited'; value: string }
  | { type: 'modeChanged'; mode: ResearchMode }
  | { type: 'exampleFilled' }
  | { type: 'draftRejected'; errors: DraftErrors }
  | { type: 'previewed'; draft: ResearchDraft; message: string }
  | { type: 'submitStarted'; draft: ResearchDraft }
  | { type: 'submitProgress'; job: ResearchJob }
  | { type: 'submitSucceeded'; report: ResearchReport; message: string }
  | { type: 'resumeStarted' }
  | { type: 'jobProgress'; job: ResearchJob }
  | { type: 'jobOpened'; job: ResearchJob }
  | { type: 'agentReportLoaded'; report: AgentResearchReport; message: string }
  | { type: 'requestFailed'; error: ResearchApiError; errors?: DraftErrors; clearResume?: boolean }
  | { type: 'requestFinished' }
  | { type: 'cancelUnconfirmed'; taskId: string; message: string }
  | { type: 'reset'; message: string }

function today() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

export function initialWorkspaceState(): WorkspaceState {
  return {
    draft: { ...EMPTY_DRAFT }, preview: null, errors: {}, message: '', report: null, mode: 'agent', job: null,
    resumeId: sessionStorage.getItem('path-of-market-active-job'), asOfDate: today(), requestError: null, isGenerating: false,
  }
}

/** 输入变化后，之前的预览、报告、错误与任务进度都不再对应当前输入。 */
const invalidated = { preview: null, report: null, requestError: null, message: '', job: null } as const

const draftOf = (report: ResearchReport): ResearchDraft => ({ target: report.target, question: report.question, userStyle: report.userStyle, omens: report.omens })

export function workspaceReducer(state: WorkspaceState, action: WorkspaceAction): WorkspaceState {
  switch (action.type) {
    case 'fieldEdited':
      return { ...state, ...invalidated, draft: { ...state.draft, [action.field]: action.value }, errors: { ...state.errors, [action.field]: undefined } }
    case 'omenToggled': {
      const omens = state.draft.omens.includes(action.value) ? state.draft.omens.filter((omen) => omen !== action.value) : [...state.draft.omens, action.value]
      return { ...state, ...invalidated, draft: { ...state.draft, omens }, errors: { ...state.errors, omens: undefined } }
    }
    case 'dateEdited':
      return { ...state, ...invalidated, asOfDate: action.value, errors: { ...state.errors, asOfDate: undefined } }
    case 'modeChanged':
      return { ...state, ...invalidated, mode: action.mode, errors: {} }
    case 'exampleFilled':
      return { ...state, ...invalidated, draft: { ...EXAMPLE_DRAFT, omens: [...EXAMPLE_DRAFT.omens] }, errors: {}, message: '已填入示例，可修改或直接生成报告。' }
    case 'draftRejected':
      return { ...state, errors: action.errors, preview: null, message: '请检查标出的输入内容。' }
    case 'previewed':
      return { ...state, errors: {}, preview: action.draft, requestError: null, message: action.message }
    case 'submitStarted':
      return { ...state, errors: {}, preview: action.draft, report: null, requestError: null, message: '', isGenerating: true }
    case 'submitProgress':
      return { ...state, job: action.job, resumeId: action.job.taskId }
    case 'submitSucceeded':
      return {
        ...state, report: action.report, preview: draftOf(action.report), message: action.message,
        resumeId: action.report.mode === 'agent' ? null : state.resumeId,
      }
    case 'resumeStarted':
      return { ...state, isGenerating: true, requestError: null, mode: 'agent' }
    case 'jobProgress':
      return { ...state, job: action.job }
    case 'jobOpened':
      return { ...state, job: action.job, mode: 'agent', resumeId: action.job.taskId }
    case 'agentReportLoaded':
      return { ...state, mode: 'agent', report: action.report, draft: draftOf(action.report), asOfDate: action.report.asOfDate, resumeId: null, message: action.message }
    case 'requestFailed':
      return {
        ...state, requestError: action.error, errors: action.errors ?? state.errors,
        resumeId: action.clearResume ? null : state.resumeId,
      }
    case 'requestFinished':
      return { ...state, isGenerating: false }
    case 'cancelUnconfirmed':
      return { ...state, resumeId: action.taskId, message: action.message }
    case 'reset':
      return { ...state, ...invalidated, isGenerating: false, draft: { ...EMPTY_DRAFT }, errors: {}, resumeId: null, message: action.message }
  }
}
