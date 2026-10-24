import { z } from 'zod'
import { OMENS } from '../features/research-lab/researchDraft'
import type { ReportOmen } from '../features/research-lab/researchDraft'

/**
 * 研究服务返回内容的运行时校验（zod）。
 * 结构检查写成 schema；需要对照来源或其他字段的规则（页码不超过资料页数、图表 ID 存在、分部合计等于总额）用 refine 写在报告层。
 * 只校验页面依赖的字段；未列出的字段原样保留（调用方使用原始响应，不使用解析后的副本）。
 */

const str = z.string()
const strings = z.array(z.string())
const int = z.number().int()
const finite = z.number()
const omen = z.enum(OMENS.map((o) => o.value) as [ReportOmen, ...ReportOmen[]])
const period = z.enum(['annual', 'h1', 'q1', 'q3'])
const draftFields = { target: str, question: str, userStyle: str, omens: z.array(omen) }
const plainSection = z.object({ heading: str, content: str })
const empty = z.array(z.unknown()).max(0)

export const mockReportSchema = z.object({
  ...draftFields, mode: z.literal('mock'), isMock: z.literal(true), title: str, summary: str,
  sections: z.array(plainSection).min(1), sources: empty, toolCalls: empty,
})

export const modelReportSchema = z.object({
  ...draftFields, mode: z.literal('model'), isMock: z.literal(false), evidenceStatus: z.literal('not_retrieved'),
  asOfDate: str, title: str, summary: str, sections: z.array(plainSection).min(2).max(6), sources: empty, toolCalls: empty,
  limitations: strings.min(1),
  run: z.object({
    status: z.literal('completed'), taskId: str, model: str, startedAt: str, finishedAt: str,
    stopReason: z.literal('model_response_received'), states: strings,
  }),
})

// pageCount 不单独校验类型，但页码范围检查要用；zod 默认丢弃未声明字段，所以这里显式保留。
const source = z.object({
  sourceId: str, title: str, publishedAt: str, url: str.startsWith('https://'), kind: z.enum(['document', 'market']), pageCount: z.unknown().optional(),
})
type Source = z.infer<typeof source>

export const coverageSchema = z.object({
  sourceId: str, pageCount: int, processedPages: z.array(int), textComplete: z.boolean(),
  processedCharacters: finite, batches: int, emptyTextPages: z.array(z.unknown()),
})

const citation = z.object({ sourceId: str, page: int.nullish() })

const sectionTable = z.object({
  title: str, unit: str, labelHeader: str.optional(), columns: strings.min(1), note: str,
  rows: z.array(z.object({ label: str, cells: strings, sourceId: str, page: int.positive().nullable(), alsoFrom: z.array(citation).optional(), note: str.optional() })).min(1),
  chart: z.enum(['none', 'bar', 'line']), chartColumns: z.array(int.nonnegative()),
  verification: z.object({ checkedCells: finite, matchedCells: finite, unmatched: z.array(z.array(int)) }).optional(),
}).refine((t) => t.rows.every((r) => r.cells.length === t.columns.length) && t.chartColumns.every((i) => i < t.columns.length), '表格行列不一致')

const marketData = z.object({
  series: z.array(z.object({ date: str, close: finite.positive(), adjustedClose: finite.positive() })).min(2),
  metrics: z.object({ tradingDays: finite, firstRawClose: finite, lastRawClose: finite, adjustedChangePct: finite, maxCloseDrawdownPct: finite }),
  provider: str, currency: str, actualStart: str, actualEnd: str, retrievedAt: str,
  sourceUrls: z.array(str.startsWith('https://')),
})

const DERIVED_KEYS = new Set(['attributableMargin', 'grossMargin', 'liabilityRatio', 'rdExpenseRatio', 'rdInvestmentRatio'])
const FINANCIAL_KEYS = new Set(['revenue', 'netProfit', 'recurringProfit', 'operatingCashFlow', 'totalAssets', 'netAssets', 'rdExpense',
  'operatingCost', 'totalLiabilities', 'cash', 'receivables', 'inventory', 'rdInvestment', ...DERIVED_KEYS])
/** 键只能是已知财务指标的对象。 */
const metricRecord = <T extends z.ZodType>(value: T) =>
  z.record(z.string(), value).refine((record) => Object.keys(record).every((key) => FINANCIAL_KEYS.has(key)), '未知财务指标')

/** 递增年份（从 1 起）。 */
const increasingYears = (rows: { year: number }[]) => rows.every((row, i) => row.year > (i ? rows[i - 1].year : 0))

const financialEvidence = z.object({
  sourceId: z.unknown(), page: int.positive(), rawValue: str, unit: z.enum(['元', '万元', '亿元']), verification: str,
})
const financialRow = z.object({
  periodLabel: str, year: int,
  values: metricRecord(finite),
  yoy: metricRecord(z.object({ reason: str, value: finite.nullable() })),
  evidence: metricRecord(financialEvidence),
}).refine((row) => Object.keys(row.values).every((key) => DERIVED_KEYS.has(key) || Object.hasOwn(row.evidence, key)), '非派生指标缺少原文依据')

const financialData = z.object({
  schemaVersion: z.literal(1),
  datasets: z.array(z.object({ id: period, label: str, rows: z.array(financialRow).max(3).refine(increasingYears, '年份需递增') })).max(4)
    .refine((sets) => new Set(sets.map((d) => d.id)).size === sets.length, '数据集 ID 重复'),
  labels: z.record(z.string(), str), method: str, gaps: strings,
  charts: z.array(z.object({
    id: str, title: str, datasetId: str, type: z.enum(['bar', 'line']), valueKind: z.enum(['amount', 'yoy', 'ratio']), unit: z.enum(['亿元', '%']),
    keys: z.array(str.refine((key) => FINANCIAL_KEYS.has(key), '未知财务指标')).min(1).max(3),
  })).max(36),
}).refine((data) => data.charts.every((chart) => data.datasets.some((d) => d.id === chart.datasetId)), '图表引用了不存在的数据集')

const nonNegative = finite.nonnegative()
const businessEvidence = z.object({ sourceId: str, page: int.positive() })
const businessItem = z.object({
  label: str, value: nonNegative, share: nonNegative.max(100.01), derived: z.boolean(),
  sourceId: z.unknown().optional(), page: z.unknown().optional(),
}).refine((item) => item.derived || businessEvidence.safeParse(item).success, '非派生项目缺少原文依据')
const businessRow = z.object({
  year: int, periodLabel: str, total: nonNegative.refine((total) => total !== 0, '总额不能为 0'),
  totalEvidence: businessEvidence, items: z.array(businessItem).min(2).max(30),
}).refine((row) => new Set(row.items.map((item) => item.label)).size === row.items.length, '项目名称重复')
  .refine((row) => row.items.every((item) => Math.abs(item.share - item.value / row.total * 100) <= 0.01), '占比与金额不一致')
  .refine((row) => Math.abs(row.items.reduce((sum, item) => sum + item.value, 0) - row.total) <= Math.max(0.01, row.total * 0.0001), '分项合计不等于总额')

const businessData = z.object({
  schemaVersion: z.literal(1), method: str, gaps: strings,
  datasets: z.array(z.object({
    id: str, label: str, dimension: z.enum(['product', 'geography', 'industry']), period,
    rows: z.array(businessRow).min(1).max(3).refine(increasingYears, '年份需递增'),
  })).max(12).refine((sets) => new Set(sets.map((d) => d.id)).size === sets.length, '数据集 ID 重复'),
})

const diagram = z.object({
  kind: z.enum(['flow', 'cards']), title: str,
  nodes: z.array(z.object({ label: str, detail: str, citations: z.array(z.object({ sourceId: z.unknown(), page: z.unknown().optional() })).min(1) })).min(2).max(6),
})
const figurePlanEntry = z.object({
  sectionIndex: z.number(), financialChartIds: z.array(z.unknown()), businessDatasetIds: z.array(z.unknown()), diagram: diagram.nullish(),
})

const methodUsage = z.object({
  status: str, reviewed: z.boolean(),
  references: z.array(z.object({ reference: str, characters: finite, sha256: str })),
  // 方法计划失败时 plan 为 null（研究继续进行，报告局限中注明）。
  plan: z.object({
    focus: str, unavailable: strings,
    checks: z.array(z.object({ topic: str, question: str, evidenceNeeded: str, figureIdea: str, methodReference: str })),
  }).nullable(),
}).refine((usage) => usage.plan !== null || usage.status === 'plan_failed', '只有计划失败时 plan 才能为空')

const omenCoverage = z.array(z.object({
  omen, name: str, covered: z.boolean(), coverageScope: str, verification: str, planChecks: finite,
  sections: strings, addressed: strings, missingItems: strings, capabilityGaps: strings, skillsRead: strings,
})).max(4)

const visualReading = z.object({
  sourceId: str, pages: z.array(int.positive()),
  observations: z.array(z.object({ page: int, summary: str, uncertainties: strings })),
})

/** 引用的资料页是否存在：必须是文件来源，且页码不超过该资料页数。 */
function documentPage(sources: Source[], sourceId: unknown, page: number) {
  return sources.some((s) => s.kind === 'document' && s.sourceId === sourceId && page <= Number(s.pageCount))
}

export const agentReportSchema = z.object({
  ...draftFields, mode: z.literal('agent'), isMock: z.literal(false), evidenceStatus: z.enum(['retrieved', 'partial']),
  asOfDate: str, title: str, summary: str,
  sources: z.array(source), coverage: z.array(coverageSchema),
  sections: z.array(z.object({ heading: str, content: str, citations: z.array(citation), omens: z.array(omen).nullish(), tables: z.array(sectionTable).nullish() })).min(2),
  limitations: strings,
  toolCalls: z.array(z.object({ toolCallId: str, name: str, status: str })),
  run: z.object({ status: z.enum(['completed', 'partial']), taskId: str, model: str, stopReason: str, modelCalls: finite }),
  marketData: marketData.nullable(),
  financialData: financialData.nullish(),
  businessData: businessData.nullish(),
  figurePlan: z.array(figurePlanEntry).nullish(),
  methodUsage: methodUsage.nullish(),
  omenCoverage: omenCoverage.nullish(),
  researchSkill: z.object({ name: str, version: str, upstream: str }).nullish(),
  visualReadings: z.array(visualReading).nullish(),
}).superRefine((report, ctx) => {
  const sources = report.sources as Source[]
  const fail = (message: string) => ctx.addIssue({ code: 'custom', message })
  for (const row of report.financialData?.datasets.flatMap((d) => d.rows) ?? []) {
    if (!Object.values(row.evidence).every((e) => documentPage(sources, e.sourceId, e.page))) fail('财务证据页不在来源范围内')
  }
  for (const row of report.sections.flatMap((s) => s.tables ?? []).flatMap((t) => t.rows.flatMap((r) => [r, ...(r.alsoFrom ?? []).map((c) => ({ ...c, page: c.page ?? null }))]))) {
    // 行情来源没有页码（与后端 check_citation 一致，不检查页码）；文件来源的页码须在资料范围内。
    const source = sources.find((s) => s.sourceId === row.sourceId)
    const ok = source != null && (source.kind === 'market' || row.page == null || documentPage(sources, row.sourceId, row.page))
    if (!ok) fail('表格来源页不在资料范围内')
  }
  for (const row of report.businessData?.datasets.flatMap((d) => d.rows) ?? []) {
    const evidence = [row.totalEvidence, ...row.items.filter((item) => !item.derived)]
    if (!evidence.every((e) => documentPage(sources, e.sourceId, Number(e.page)))) fail('业务证据页不在来源范围内')
  }
  if (report.figurePlan != null) {
    const charts = new Set(report.financialData?.charts.map((c) => c.id))
    const datasets = new Set(report.businessData?.datasets.map((d) => d.id))
    const seen = new Set<string>()
    if (report.figurePlan.length !== report.sections.length) fail('图表计划与章节数量不一致')
    report.figurePlan.forEach((figure, i) => {
      if (figure.sectionIndex !== i) fail('图表计划章节序号不连续')
      if (!figure.financialChartIds.every((id) => charts.has(id as string))) fail('引用了不存在的财务图')
      if (!figure.businessDatasetIds.every((id) => datasets.has(id as string))) fail('引用了不存在的业务数据')
      for (const id of [...figure.financialChartIds, ...figure.businessDatasetIds].map(String)) {
        if (seen.has(id)) fail('同一张图被多个章节引用')
        seen.add(id)
      }
      const cited = figure.diagram?.nodes.flatMap((node) => node.citations) ?? []
      if (!cited.every((c) => sources.some((s) => s.sourceId === c.sourceId
        && (s.kind === 'market' || Number.isInteger(c.page) && Number(c.page) > 0 && Number(c.page) <= Number(s.pageCount))))) fail('示意图引用的资料页不存在')
    })
  }
})

export const jobSchema = z.object({
  taskId: str.regex(/^[0-9a-f-]{36}$/i),
  status: z.enum(['queued', 'running', 'completed', 'partial', 'failed', 'cancelled']),
  progress: str, modelCalls: finite,
  events: z.array(z.object({ id: str, message: str, type: str })),
  coverage: z.array(coverageSchema),
  report: agentReportSchema.nullable(),
})

/** 研究记录列表（M2-1，来自 Java SessionStore）。 */
export const sessionListSchema = z.object({
  sessions: z.array(z.object({ sessionId: str, runId: str, createdAt: str, target: str, question: str, status: str, title: str.optional() })),
})

/** 错误响应：{ error: { code } } 与 FastAPI 422 的 { detail: [{ loc, type }] }。 */
export const errorBodySchema = z.object({ error: z.object({ code: str }) })
export const validationIssueSchema = z.object({ loc: z.array(z.unknown()), type: z.unknown().optional() })
