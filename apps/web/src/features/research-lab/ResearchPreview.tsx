import { OMENS } from './researchDraft'
import type { ResearchDraft } from './researchDraft'

type Props = { draft: ResearchDraft | null }

export function ResearchPreview({ draft }: Props) {
  return (
    <aside className="research-preview" aria-label="研究任务预览">
      <div className="preview-topline">
        <span className="eyebrow">RESEARCH BRIEF</span>
        <span className={`preview-status${draft ? ' preview-status--ready' : ''}`}>
          <span className="status-dot" aria-hidden="true" />
          {draft ? '任务已预览' : '等待输入'}
        </span>
      </div>
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
        <p>报告尚未生成</p>
        <span>当前可预览任务，报告生成将在下一步接入。</span>
      </div>
    </aside>
  )
}
