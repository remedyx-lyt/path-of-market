import type { ResearchReport as Report } from '../../api/research'
import { OMENS } from './researchDraft'
import type { AgentResearchReport } from '../../api/research'
import { MarketChart } from './MarketChart'
import { FinancialCharts } from './FinancialCharts'
import { ReportText } from './ReportText'

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
  const labels: Record<string, string> = { find_documents: '查找报告', read_document: '阅读与回查', get_market_data: '查询行情', inspect_document_pages:'检查PDF原页', read_research_skill:'读取研究方法' }
  return <>
    <span className="mock-badge">真实研究 · {report.run.status === 'completed' ? '已完成' : '部分结果'}</span>
    <h2 className="report-title">{report.title}</h2>
    <div className="report-summary"><ReportText text={report.summary} /></div>
    <nav className="report-nav" aria-label="报告目录">
      {report.financialData?.datasets.length ? <a href="#financial-analysis">财务表图</a> : null}
      {report.sections.map((s,i) => <a key={i} href={`#analysis-${i}`}>{s.heading.replace(/^[一二三四五六七八九十]+[、.．]\s*/, '')}</a>)}
    </nav>
    <details className="report-task">
      <summary>研究任务与执行记录</summary>
      <dl className="preview-fields">
        <div><dt>研究对象 / 截止日期</dt><dd>{report.target} / {report.asOfDate}</dd></div>
        <div><dt>研究问题</dt><dd>{report.question}</dd></div>
        <div><dt>执行情况</dt><dd>{report.run.modelCalls} 次模型调用 · {report.run.steps} 轮决策 · {report.run.stopReason}</dd></div>
        <div><dt>资料阅读</dt><dd>{report.coverage.map((entry) => <p key={entry.sourceId}>
          {report.sources.find((s) => s.sourceId === entry.sourceId)?.title}：{entry.processedPages.length}/{entry.pageCount} 页文本
          {entry.textComplete ? '，文本阅读完成' : '，尚有未完成范围'}
        </p>)}</dd></div>
        <div><dt>工具动作</dt><dd><ol>{report.toolCalls.map((call) => <li key={call.toolCallId}>{labels[call.name] || call.name} · {call.status}{call.errorCode ? ` (${call.errorCode})` : ''}</li>)}</ol></dd></div>
        <div><dt>任务编号</dt><dd>{report.run.taskId}</dd></div>
      </dl>
    </details>
    {report.financialData && <FinancialCharts data={report.financialData} sources={report.sources} />}
    {report.marketData && <MarketChart data={report.marketData} />}
    <div className="report-sections">
      {report.sections.map((section, i) => <section className="report-section" id={`analysis-${i}`} key={`${i}-${section.heading}`}>
        <h3>{section.heading}</h3><ReportText text={section.content} />
        <div className="section-citations">{section.citations.map((citation, j) => {
          const source = report.sources.find((s) => s.sourceId === citation.sourceId)
          return source ? <a key={`${citation.sourceId}-${j}`} href={`${source.url}${citation.page ? `#page=${citation.page}` : ''}`} target="_blank" rel="noreferrer">
            {source.title}{citation.page ? ` · PDF第${citation.page}页` : ''} ↗
          </a> : null
        })}</div>
      </section>)}
    </div>
    {!!report.visualReadings?.length && <details className="visual-readings"><summary>PDF 原页视觉检查 · {new Set(report.visualReadings.flatMap((r) => r.pages.map((p) => `${r.sourceId}:${p}`))).size} 页</summary>
      {report.visualReadings.map((reading,i) => <div key={i}><strong>{report.sources.find((s) => s.sourceId===reading.sourceId)?.title}</strong><p>{reading.origin === 'automatic_financial_summary' ? '财务摘要自动检查' : '模型主动回查'}{reading.cacheReused ? ' · 复用已有视觉记录' : ''}</p>{reading.observations.map((o) => <p key={o.page}>PDF第{o.page}页：{o.summary}{o.uncertainties.length ? `；待核查：${o.uncertainties.join('；')}` : ''}</p>)}</div>)}
      <p>只检查以上页面，不能视为全本图片均已理解。</p>
    </details>}
    {report.researchSkill && <p className="report-skill">研究规范：{report.researchSkill.name} · {report.researchSkill.version} · 参考 {report.researchSkill.upstream}</p>}
    <section className="report-evidence" aria-label="研究来源">
      <h3>本次资料来源</h3>
      <ol>{report.sources.map((source) => <li key={source.sourceId}><a href={source.url} target="_blank" rel="noreferrer">{source.title} ↗</a><p>{source.kind === 'document' ? '披露日期' : '数据截至'}：{source.publishedAt}</p></li>)}</ol>
    </section>
    <div className="report-limitations">{report.limitations.map((text) => <p key={text}>{text}</p>)}</div>
  </>
}
