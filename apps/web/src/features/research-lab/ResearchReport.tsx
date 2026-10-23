import type { ResearchReport as Report } from '../../api/research'
import { OMENS } from './researchDraft'
import type { AgentResearchReport } from '../../api/research'
import { MarketChart } from './MarketChart'

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
  const labels: Record<string, string> = { find_documents: '查找报告', read_document: '阅读与回查', get_market_data: '查询行情' }
  return <>
    <span className="mock-badge">真实研究 · {report.run.status === 'completed' ? '已完成' : '部分结果'}</span>
    <h2 className="report-title">{report.title}</h2>
    <p className="report-summary">{report.summary}</p>
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
    {report.marketData && <MarketChart data={report.marketData} />}
    <div className="report-sections">
      {report.sections.map((section, i) => <section className="report-section" key={`${i}-${section.heading}`}>
        <h3>{section.heading}</h3><p>{section.content}</p>
        <div className="section-citations">{section.citations.map((citation, j) => {
          const source = report.sources.find((s) => s.sourceId === citation.sourceId)
          return source ? <a key={`${citation.sourceId}-${j}`} href={`${source.url}${citation.page ? `#page=${citation.page}` : ''}`} target="_blank" rel="noreferrer">
            {source.title}{citation.page ? ` · PDF第${citation.page}页` : ''} ↗
          </a> : null
        })}</div>
      </section>)}
    </div>
    <section className="report-evidence" aria-label="研究来源">
      <h3>本次资料来源</h3>
      <ol>{report.sources.map((source) => <li key={source.sourceId}><a href={source.url} target="_blank" rel="noreferrer">{source.title} ↗</a><p>{source.kind === 'document' ? '披露日期' : '数据截至'}：{source.publishedAt}</p></li>)}</ol>
    </section>
    <div className="report-limitations">{report.limitations.map((text) => <p key={text}>{text}</p>)}</div>
  </>
}
