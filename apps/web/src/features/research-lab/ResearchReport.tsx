import type { MockResearchReport } from '../../api/research'
import { OMENS } from './researchDraft'

export function ResearchReport({ report }: { report: MockResearchReport }) {
  return (
    <>
      <span className="mock-badge">演示报告 · MOCK</span>
      <h2 className="report-title">{report.title}</h2>
      <p className="report-summary">{report.summary}</p>
      <details className="report-task">
        <summary>查看研究任务</summary>
        <dl className="preview-fields">
          <div><dt>研究对象</dt><dd>{report.target}</dd></div>
          <div><dt>研究问题</dt><dd>{report.question}</dd></div>
          <div><dt>研究偏好</dt><dd>{report.userStyle || '未指定'}</dd></div>
          <div><dt>研究预兆</dt><dd>{OMENS.filter((omen) => report.omens.includes(omen.value)).map((omen) => omen.name).join('、') || '未选择'}</dd></div>
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
    </>
  )
}
