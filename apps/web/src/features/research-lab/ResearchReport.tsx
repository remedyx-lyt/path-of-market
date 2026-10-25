import { useState } from 'react'
import type { ResearchReport as Report } from '../../api/research'
import { OMENS } from './researchDraft'
import type { AgentResearchReport } from '../../api/research'
import { MarketChart } from './MarketChart'
import { FinancialCharts } from './FinancialCharts'
import { ReportText } from './ReportText'
import { BusinessCharts, EvidenceDiagram } from './BusinessCharts'
import { SectionTables } from './SectionTables'

export function ResearchReport({ report }: { report: Report }) {
  if (report.mode === 'agent') return <AgentReportView report={report} />
  return (
    <>
      <span className="mock-badge">{report.mode === 'model' ? '模型分析 · 未检索资料' : '演示报告 · MOCK'}</span>
      <h2 className="report-title">{report.title}</h2>
      <p className="report-summary">{report.summary}</p>
      <details className="report-task">
        <summary>查看研究任务</summary>
        <dl className="preview-fields">
          <div><dt>研究对象</dt><dd>{report.target}</dd></div>
          <div><dt>研究问题</dt><dd>{report.question}</dd></div>
          <div><dt>研究偏好</dt><dd>{report.userStyle || '未指定'}</dd></div>
          <div><dt>研究预兆</dt><dd>{OMENS.filter((omen) => report.omens.includes(omen.value)).map((omen) => omen.name).join('、') || '未选择'}</dd></div>
          {report.mode === 'model' && <>
            <div><dt>截止日期</dt><dd>{report.asOfDate}</dd></div>
            <div><dt>任务状态</dt><dd>已完成模型调用 · {report.run.model}</dd></div>
            <div><dt>执行记录</dt><dd>任务创建 → 调用模型 → 返回分析</dd></div>
            <div><dt>任务编号</dt><dd>{report.run.taskId}</dd></div>
          </>}
        </dl>
      </details>
      <div className="report-sections">
        {report.sections.map((section, index) => (
          <section className="report-section" key={`${index}-${section.heading}`}>
            <h3>{section.heading}</h3>
            <p>{section.content}</p>
          </section>
        ))}
      </div>
      <div className="report-evidence">
        <p><span>资料来源</span>本次未读取真实资料</p>
        <p><span>研究工具</span>本次未执行研究工具</p>
      </div>
      {report.mode === 'model' && <div className="report-limitations">{report.limitations.map((text) => <p key={text}>{text}</p>)}</div>}
    </>
  )
}

function AgentReportView({ report }: { report: AgentResearchReport }) {
  const [showDataLabels,setShowDataLabels] = useState(true)
  const labels: Record<string, string> = { find_documents: '查找报告', read_document: '阅读与回查', get_market_data: '查询行情', inspect_document_pages:'检查PDF原页', read_research_skill:'读取研究方法',extract_report_data:'提取业务与财务数据' }
  const placedFigures = report.figurePlan?.some((f) => f.financialChartIds.length || f.businessDatasetIds.length || f.diagram)
  return <>
    <span className="mock-badge">真实研究 · {report.run.status === 'completed' ? '已完成' : '部分结果'}</span>
    <h2 className="report-title">{report.title}</h2>
    <div className="report-summary"><ReportText text={report.summary} /></div>
    <nav className="report-nav" aria-label="报告目录">
      {!placedFigures && report.financialData?.datasets.length ? <a href="#financial-analysis">财务表图</a> : null}
      {report.sections.map((s,i) => <a key={i} href={`#analysis-${i}`}>{s.heading.replace(/^[一二三四五六七八九十]+[、.．]\s*/, '')}</a>)}
    </nav>
    <label className="report-chart-options" title="控制财务柱状图、折线图和业务堆叠图上的数值">
      <input type="checkbox" checked={showDataLabels} onChange={(event) => setShowDataLabels(event.target.checked)} aria-label="显示图表数据标签" />显示数据标签
    </label>
    <details className="report-task">
      <summary>研究任务与执行记录</summary>
      <dl className="preview-fields">
        <div><dt>研究对象 / 截止日期</dt><dd>{report.target} / {report.asOfDate}</dd></div>
        <div><dt>研究问题</dt><dd>{report.question}</dd></div>
        <div><dt>研究预兆</dt><dd>{OMENS.filter((omen) => report.omens.includes(omen.value)).map((omen) => omen.name).join('、') || '未选择（按研究问题选择方法）'}</dd></div>
        <div><dt>执行情况</dt><dd>{report.run.modelCalls} 次模型调用 · {report.run.steps} 轮决策 · {report.run.stopReason}</dd></div>
        <div><dt>模型用量</dt><dd>{usageText(report.run.usage)}</dd></div>
        <div><dt>资料阅读</dt><dd>{report.coverage.map((entry) => <p key={entry.sourceId}>
          {report.sources.find((s) => s.sourceId === entry.sourceId)?.title}：{entry.unit === 'segment' ? `${entry.processedCharacters}/${entry.fetchedCharacters ?? '?'} 字网页正文` : `${entry.processedPages.length}/${entry.pageCount} 页文本`}
          {entry.textComplete ? '，文本阅读完成' : '，尚有未完成范围'}
        </p>)}</dd></div>
        <div><dt>工具动作</dt><dd><ol>{report.toolCalls.map((call) => <li key={call.toolCallId}>{labels[call.name] || call.name} · {call.status}{call.errorCode ? ` (${call.errorCode})` : ''}</li>)}</ol></dd></div>
        <div><dt>任务编号</dt><dd>{report.run.taskId}</dd></div>
      </dl>
    </details>
    {!!report.omenCoverage?.length && <OmenCoveragePanel coverage={report.omenCoverage} />}
    {report.methodUsage && <MethodUsagePanel usage={report.methodUsage} />}
    {!placedFigures && report.financialData && <FinancialCharts data={report.financialData} sources={report.sources} showDataLabels={showDataLabels} />}
    {report.marketData && <MarketChart data={report.marketData} />}
    <div className="report-sections">
      {report.sections.map((section, i) => <section className="report-section" id={`analysis-${i}`} key={`${i}-${section.heading}`}>
        <h3>{section.heading}</h3>
        {!!section.omens?.length && <p className="section-omens">{section.omens.map((id) => OMENS.find((o) => o.value === id)?.name || id).join(' · ')}</p>}
        <ReportText text={section.content} />
        {placedFigures && report.figurePlan?.filter((f) => f.sectionIndex===i).map((f) => <div className="section-visuals" key={i}>
          {report.businessData && f.businessDatasetIds.length>0 && <BusinessCharts data={report.businessData} sources={report.sources} ids={f.businessDatasetIds} showDataLabels={showDataLabels} />}
          {report.financialData && f.financialChartIds.length>0 && <FinancialCharts data={report.financialData} sources={report.sources} chartIds={f.financialChartIds} showDataLabels={showDataLabels} />}
          {f.diagram && <EvidenceDiagram diagram={f.diagram} sources={report.sources} />}
        </div>)}
        {!!section.tables?.length && <SectionTables tables={section.tables} sources={report.sources} showDataLabels={showDataLabels} />}
        <div className="section-citations">{section.citations.map((citation, j) => {
          const source = report.sources.find((s) => s.sourceId === citation.sourceId)
          return source ? <a key={`${citation.sourceId}-${j}`} href={`${source.url}${citation.page ? `#page=${citation.page}` : ''}`} target="_blank" rel="noreferrer">
            {source.title}{citation.page ? ` · PDF第${citation.page}页` : ''} ↗
          </a> : null
        })}</div>
      </section>)}
    </div>
    {placedFigures && <details className="financial-gaps"><summary>图表数据来源与取数限制</summary><p>{report.businessData?.method}</p>{[...new Set([...(report.financialData?.gaps || []),...(report.businessData?.gaps || [])])].map((g) => <p key={g}>{g}</p>)}</details>}
    {!!report.visualReadings?.length && <details className="visual-readings"><summary>PDF 原页视觉检查 · {new Set(report.visualReadings.flatMap((r) => r.pages.map((p) => `${r.sourceId}:${p}`))).size} 页</summary>
      {report.visualReadings.map((reading,i) => <div key={i}><strong>{report.sources.find((s) => s.sourceId===reading.sourceId)?.title}</strong><p>{reading.origin === 'automatic_financial_summary' ? '财务摘要自动检查' : '模型主动回查'}{reading.cacheReused ? ' · 复用已有视觉记录' : ''}</p>{reading.observations.map((o) => <p key={o.page}>PDF第{o.page}页：{o.summary}{o.uncertainties.length ? `；待核查：${o.uncertainties.join('；')}` : ''}</p>)}</div>)}
      <p>只检查以上页面，不能视为全本图片均已理解。</p>
    </details>}
    {report.researchSkill && <p className="report-skill">研究规范：{report.researchSkill.name} · {report.researchSkill.version} · 参考 {report.researchSkill.upstream}</p>}
    <section className="report-evidence" aria-label="研究来源">
      <h3>本次资料来源</h3>
      <ol>{report.sources.map((source) => <li key={source.sourceId}><a href={source.url} target="_blank" rel="noreferrer">{source.title} ↗</a><p>{source.kind === 'document' ? '披露日期' : source.kind === 'web' ? '网页发布日期' : '数据截至'}：{source.publishedAt || '未知（不作为截止日事实引用）'}{source.kind === 'web' && source.retrievedAt ? ` · 获取于 ${source.retrievedAt.slice(0, 10)}` : ''}</p></li>)}</ol>
    </section>
    <div className="report-limitations">{report.limitations.map((text) => <p key={text}>{text}</p>)}</div>
  </>
}

function usageText(usage: Record<string, number>) {
  const total = usage.total_tokens ?? 0
  const hit = usage.prompt_cache_hit_tokens
  const miss = usage.prompt_cache_miss_tokens
  if (typeof hit !== 'number' || typeof miss !== 'number' || hit + miss === 0) return `${total.toLocaleString()} tokens`
  // DeepSeek 缓存命中部分约为未命中价格的 1/50，实际费用主要取决于未命中部分。
  return `${total.toLocaleString()} tokens · 输入缓存命中 ${Math.round(hit / (hit + miss) * 100)}%（未命中 ${miss.toLocaleString()}）`
}

function skillName(path: string) {
  return path.split('/skills/')[1]?.replace(/\/SKILL\.md$/, '').replace(/\.md$/, '') || path
}

function OmenCoveragePanel({ coverage }: { coverage: NonNullable<AgentResearchReport['omenCoverage']> }) {
  return <details className="method-usage omen-coverage" open>
    <summary>研究预兆覆盖 · {coverage.filter((c) => c.covered).length}/{coverage.length} 在现有工具范围内完成</summary>
    {coverage.map((c) => <div key={c.omen}>
      <strong>{c.name} · {c.covered ? '已覆盖' : '未完全覆盖'}</strong>
      <p>专属章节：{c.sections.join('、') || '无'}；方法计划检查 {c.planChecks} 项；使用 Skill：{c.skillsRead.map(skillName).join('、') || '无'}</p>
      {c.addressed.length > 0 && <p>已回答：{c.addressed.join('；')}</p>}
      {c.missingItems.length > 0 && <p>未覆盖：{c.missingItems.join('；')}</p>}
      {c.capabilityGaps.map((g) => <p key={g}>工具缺口：{g}</p>)}
    </div>)}
    <p>{coverage[0]?.verification}</p>
  </details>
}

function MethodUsagePanel({ usage }: { usage: NonNullable<AgentResearchReport['methodUsage']> }) {
  const extra = usage.onDemandReads?.length ? `；研究中另按需读取 ${usage.onDemandReads.map(skillName).join('、')}` : ''
  return <details className="method-usage"><summary>研究主线与方法</summary>
    {usage.plan ? <>
      <p>{usage.plan.focus}</p>
      <ul>{usage.plan.checks.map((c,i) => <li key={i}><strong>{c.question}</strong>{c.omen ? <span className="section-omens"> · {OMENS.find((o) => o.value === c.omen)?.name || c.omen}</span> : null}<p>{c.evidenceNeeded}</p></li>)}</ul>
    </> : <p>本次方法计划未通过格式校验，研究按已加载的基础方法进行。</p>}
    <ul>{usage.references.map((r) => <li key={r.reference}>{skillName(r.reference)}{r.selectedBecause?.length ? `（${r.selectedBecause.join('、')}）` : ''}</li>)}</ul>
    <p>本轮读取 {usage.references.length} 份相关原版方法{usage.planCacheReused ? '（计划复用自先前相同任务）' : ''}{extra}，{!usage.plan ? '方法计划未形成' : usage.reviewed ? '已结合方法计划复核报告' : '已形成计划，尚未完成报告复核'}；方法阅读与模型复核不等于独立事实审计。</p>
    {usage.plan?.unavailable.map((s,i) => <p key={i}>{s}</p>)}
  </details>
}
