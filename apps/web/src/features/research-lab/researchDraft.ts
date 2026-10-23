export const OMENS = [
  { value: 'exalted', name: '崇高预兆', description: '深入理解' },
  { value: 'ancient', name: '远古预兆', description: '历史参照' },
  { value: 'opportunity', name: '机遇预兆', description: '未来变化' },
  { value: 'abyssal_echoes', name: '深渊回响', description: '风险与反方' },
] as const

export type ReportOmen = (typeof OMENS)[number]['value']

export type ResearchDraft = {
  target: string
  question: string
  userStyle: string
  omens: ReportOmen[]
}

export type DraftErrors = Partial<Record<'target' | 'question' | 'userStyle' | 'omens' | 'asOfDate', string>>

export const EMPTY_DRAFT: ResearchDraft = { target: '', question: '', userStyle: '', omens: [] }

export const EXAMPLE_DRAFT: ResearchDraft = {
  target: '中际旭创',
  question: '研究最近两年的经营变化，阅读最近两份年报并补充当年已披露的半年报，分析最近约24个月股票价格走势、区间变化、回撤，以及经营与价格之间可能的联系和风险。',
  userStyle: '关注长期增长，同时检查风险和反方证据。',
  omens: ['opportunity', 'abyssal_echoes'],
}

// 按 Unicode 码点计数，去除首尾空白，不将非 BMP 字符计为两个。
export function characterCount(value: string) {
  return Array.from(value.trim()).length
}

export function validateDraft(draft: ResearchDraft): DraftErrors {
  const errors: DraftErrors = {}
  if (!draft.target.trim()) errors.target = '请填写研究对象。'
  else if (characterCount(draft.target) > 120) errors.target = '研究对象最多 120 个字符。'
  if (!draft.question.trim()) errors.question = '请写下你想研究的问题。'
  else if (characterCount(draft.question) > 2000) errors.question = '研究问题最多 2000 个字符。'
  if (characterCount(draft.userStyle) > 500) errors.userStyle = '研究偏好最多 500 个字符。'
  return errors
}

export function normalizeDraft(draft: ResearchDraft): ResearchDraft {
  return {
    target: draft.target.trim(),
    question: draft.question.trim(),
    userStyle: draft.userStyle.trim(),
    omens: [...draft.omens],
  }
}
