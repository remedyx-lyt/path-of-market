import { OMENS } from './researchDraft'
import type { ResearchDraft } from './researchDraft'
import type { ResearchReport as Report } from '../../api/research'
import { ResearchReport } from './ResearchReport'

type Props = { draft: ResearchDraft | null; report: Report | null; isGenerating: boolean; hasError: boolean }

export function ResearchPreview({ draft, report, isGenerating, hasError }: Props) {
  const status = isGenerating ? '正在获取报告' : hasError ? '生成失败' : report ? '报告已返回' : draft ? '任务已预览' : '等待输入'
  return (
    <aside className={`research-preview${report ? ' research-preview--report' : ''}${report?.mode === 'agent' ? ' research-preview--agent' : ''}`} aria-label={report ? report.mode === 'agent' ? '真实研究报告' : report.mode === 'model' ? '模型分析报告' : '演示研究报告' : '研究任务预览'} aria-busy={isGenerating}>
      <div className="preview-topline">
        <span className="eyebrow">RESEARCH BRIEF</span>
        <span className={`preview-status${report || draft && !isGenerating && !hasError ? ' preview-status--ready' : ''}`}>
          <span className="status-dot" aria-hidden="true" />
          {status}
        </span>
      </div>
      {report ? <ResearchReport report={report} /> : <>
      <h2>这次研究，<br />关注什么？</h2>
      <dl className="preview-fields">
        <div>
          <dt>研究对象</dt>
          <dd className={!draft ? 'preview-placeholder' : ''}>{draft?.target || '一家公司，或一个板块。'}</dd>
        </div>
        <div>
          <dt>研究问题</dt>
          <dd className={!draft ? 'preview-placeholder' : ''}>{draft?.question || '写下值得深入了解的问题。'}</dd>
        </div>
        <div>
          <dt>研究偏好</dt>
          <dd className={!draft?.userStyle ? 'preview-placeholder' : ''}>{draft?.userStyle || '未指定'}</dd>
        </div>
        <div>
          <dt>研究预兆</dt>
          <dd>
            {draft?.omens.length ? (
              <div className="omen-tags">
                {OMENS.filter((omen) => draft.omens.includes(omen.value)).map((omen) => (
                  <span key={omen.value}>{omen.name}</span>
                ))}
              </div>
            ) : <span className="preview-placeholder">未选择</span>}
          </dd>
        </div>
      </dl>
      <div className="report-placeholder">
        <span className="report-placeholder-label">研究报告</span>
        <p>{isGenerating ? '正在获取报告…' : '报告尚未生成'}</p>
        <span>{isGenerating ? '请稍候，也可以取消并清空任务。' : '填写研究任务，选择生成方式后提交。'}</span>
      </div>
      </>}
    </aside>
  )
}
