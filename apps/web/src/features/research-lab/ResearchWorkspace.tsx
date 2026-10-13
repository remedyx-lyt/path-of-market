import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ResearchPreview } from './ResearchPreview'
import { characterCount, EMPTY_DRAFT, EXAMPLE_DRAFT, normalizeDraft, OMENS, validateDraft } from './researchDraft'
import type { DraftErrors, ReportOmen, ResearchDraft } from './researchDraft'

export function ResearchWorkspace() {
  const [draft, setDraft] = useState<ResearchDraft>({ ...EMPTY_DRAFT })
  const [preview, setPreview] = useState<ResearchDraft | null>(null)
  const [errors, setErrors] = useState<DraftErrors>({})
  const [message, setMessage] = useState('')
  const targetRef = useRef<HTMLInputElement>(null)
  const questionRef = useRef<HTMLTextAreaElement>(null)
  const styleRef = useRef<HTMLTextAreaElement>(null)
  const optionsRef = useRef<HTMLDetailsElement>(null)

  function updateField(field: 'target' | 'question' | 'userStyle', value: string) {
    setDraft((current) => ({ ...current, [field]: value }))
    setErrors((current) => ({ ...current, [field]: undefined }))
    setPreview(null)
    setMessage('')
  }

  function toggleOmen(value: ReportOmen) {
    setDraft((current) => ({
      ...current,
      omens: current.omens.includes(value) ? current.omens.filter((omen) => omen !== value) : [...current.omens, value],
    }))
    setPreview(null)
    setMessage('')
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const nextErrors = validateDraft(draft)
    setErrors(nextErrors)
    if (Object.keys(nextErrors).length) {
      setPreview(null)
      setMessage('请检查标出的输入内容。')
      if (nextErrors.target) targetRef.current?.focus()
      else if (nextErrors.question) questionRef.current?.focus()
      else {
        if (optionsRef.current) optionsRef.current.open = true
        styleRef.current?.focus()
      }
      return
    }
    setPreview(normalizeDraft(draft))
    setMessage('研究任务已预览，当前还未生成报告。')
  }

  function fillExample() {
    setDraft({ ...EXAMPLE_DRAFT, omens: [...EXAMPLE_DRAFT.omens] })
    setPreview(null)
    setErrors({})
    setMessage('已填入示例，可修改后预览。')
    targetRef.current?.focus()
  }

  function reset() {
    setDraft({ ...EMPTY_DRAFT })
    setPreview(null)
    setErrors({})
    setMessage('已清空研究任务。')
    targetRef.current?.focus()
  }

  return (
    <div className="workspace-layout">
      <section className="research-input" aria-labelledby="workspace-title">
        <div className="workspace-intro">
          <p className="eyebrow">深研室 <span>/</span> THE RESEARCH LAB</p>
          <h1 id="workspace-title">把问题，<br />研究清楚。</h1>
          <p className="workspace-description">围绕公司与板块，整理你关心的变化、机会与风险。</p>
        </div>
        <form className="research-form" onSubmit={submit} noValidate>
          <div className="form-heading">
            <h2>准备研究任务</h2>
            <button className="text-button" type="button" onClick={fillExample}>填入示例 <span aria-hidden="true">↗</span></button>
          </div>
          <div className="form-field">
            <label htmlFor="research-target">研究对象 <span>必填</span></label>
            <input
              ref={targetRef} id="research-target" name="target" required autoComplete="off"
              value={draft.target} onChange={(event) => updateField('target', event.target.value)}
              placeholder="公司名称或板块，例如：半导体"
              aria-invalid={!!errors.target}
              aria-describedby={`target-help${errors.target ? ' target-error' : ''}`}
            />
            <div className="field-help" id="target-help">
              <span>这次想了解谁？</span>
              <span className={characterCount(draft.target) > 120 ? 'counter-over' : ''}>{characterCount(draft.target)} / 120</span>
            </div>
            {errors.target && <p className="field-error" id="target-error">{errors.target}</p>}
          </div>
          <div className="form-field">
            <label htmlFor="research-question">研究问题 <span>必填</span></label>
            <textarea
              ref={questionRef} id="research-question" name="question" required rows={4}
              value={draft.question} onChange={(event) => updateField('question', event.target.value)}
              placeholder="想了解哪些变化？希望验证什么判断？"
              aria-invalid={!!errors.question}
              aria-describedby={`question-help${errors.question ? ' question-error' : ''}`}
            />
            <div className="field-help" id="question-help">
              <span>问题越具体，研究方向越清晰。</span>
              <span className={characterCount(draft.question) > 2000 ? 'counter-over' : ''}>{characterCount(draft.question)} / 2000</span>
            </div>
            {errors.question && <p className="field-error" id="question-error">{errors.question}</p>}
          </div>
          <details className="research-options" ref={optionsRef}>
            <summary>
              <span>研究偏好与预兆</span>
              <span className="options-note">{draft.userStyle || draft.omens.length ? '已设置' : '选填'} <span aria-hidden="true">＋</span></span>
            </summary>
            <div className="options-content">
              <div className="form-field">
                <label htmlFor="research-style">研究偏好</label>
                <textarea
                  ref={styleRef} id="research-style" name="userStyle" rows={2}
                  value={draft.userStyle} onChange={(event) => updateField('userStyle', event.target.value)}
                  placeholder="例如：关注长期增长，同时重视风险。"
                  aria-invalid={!!errors.userStyle}
                  aria-describedby={`style-help${errors.userStyle ? ' style-error' : ''}`}
                />
                <div className="field-help" id="style-help">
                  <span>希望研究更侧重什么？</span>
                  <span className={characterCount(draft.userStyle) > 500 ? 'counter-over' : ''}>{characterCount(draft.userStyle)} / 500</span>
                </div>
                {errors.userStyle && <p className="field-error" id="style-error">{errors.userStyle}</p>}
              </div>
              <fieldset className="omens-fieldset">
                <legend>研究预兆 <span>可多选</span></legend>
                <div className="omen-options">
                  {OMENS.map((omen) => (
                    <label className={`omen-option${draft.omens.includes(omen.value) ? ' omen-option--selected' : ''}`} key={omen.value}>
                      <input type="checkbox" name="omens" value={omen.value} checked={draft.omens.includes(omen.value)} onChange={() => toggleOmen(omen.value)} />
                      <span><strong>{omen.name}</strong><span>{omen.description}</span></span>
                    </label>
                  ))}
                </div>
              </fieldset>
            </div>
          </details>
          <div className="form-actions">
            <button className="primary-button" type="submit">预览研究任务 <span aria-hidden="true">→</span></button>
            <button className="secondary-button" type="button" onClick={reset}>清空</button>
          </div>
          <p className="form-message" role="status">{message || '先整理任务，再开始深入研究。'}</p>
        </form>
      </section>
      <ResearchPreview draft={preview} />
    </div>
  )
}
