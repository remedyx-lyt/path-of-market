import type { ResearchReport as Report } from '../../api/research'
import { OMENS } from './researchDraft'

export function ResearchReport({ report }: { report: Report }) {
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
