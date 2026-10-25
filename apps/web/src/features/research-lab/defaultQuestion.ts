import type { ResearchDraft, ReportOmen } from './researchDraft'

const focuses: Record<ReportOmen, string> = {
  exalted: '深入拆解商业模式、竞争优势与关键经营指标，核对结论背后的证据',
  ancient: '放回公司发展历程和行业周期中，比较历史阶段与当前的异同',
  opportunity: '关注未来变化、潜在催化因素及其兑现条件，区分事实与假设',
  abyssal_echoes: '寻找反方证据、主要风险与可能推翻研究判断的条件',
}

/** 本地模板，不调用模型；勾选顺序不影响问题文字。 */
export function defaultQuestion(draft: Pick<ResearchDraft, 'target' | 'omens'>, asOfDate: string): string {
  const target = draft.target.trim() || '这家公司'
  const cutoff = /^\d{4}-\d{2}-\d{2}$/.test(asOfDate) ? `截至 ${asOfDate} ` : ''
  const years = draft.omens.includes('ancient') ? 10 : 5
  const base = `研究${target}最近${years}年的经营变化，通读研究截止日前已披露的完整年报并补充最新定期报告：收入与利润的来源、业务与客户结构、产能与产销、现金流与资产负债的质量；结合${cutoff}约 24 个月的股价走势、区间涨跌和回撤，分析经营与价格之间的联系和主要风险。仅使用研究截止日之前已公开的资料，区分已知事实、推断与资料缺口。`
  const selected = (Object.keys(focuses) as ReportOmen[]).filter((omen) => draft.omens.includes(omen))
  return base + (selected.length ? `重点关注：${selected.map((omen) => focuses[omen]).join('；')}。` : '')
}
