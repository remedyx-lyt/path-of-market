import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { generateMockReport, ResearchApiError } from '../../api/research'
import type { MockResearchReport } from '../../api/research'
import { ResearchPreview } from './ResearchPreview'
import { characterCount, EMPTY_DRAFT, EXAMPLE_DRAFT, normalizeDraft, OMENS, validateDraft } from './researchDraft'
import type { DraftErrors, ReportOmen, ResearchDraft } from './researchDraft'

export function ResearchWorkspace() {
  const [draft, setDraft] = useState<ResearchDraft>({ ...EMPTY_DRAFT })
  const [preview, setPreview] = useState<ResearchDraft | null>(null)
  const [errors, setErrors] = useState<DraftErrors>({})
  const [message, setMessage] = useState('')
  const [report, setReport] = useState<MockResearchReport | null>(null)
  const [requestError, setRequestError] = useState<ResearchApiError | null>(null)
  const [isGenerating, setIsGenerating] = useState(false)
  const requestRef = useRef<AbortController | null>(null)
  const pendingFocusRef = useRef<DraftErrors | null>(null)
  const targetRef = useRef<HTMLInputElement>(null)
  const questionRef = useRef<HTMLTextAreaElement>(null)
  const styleRef = useRef<HTMLTextAreaElement>(null)
  const optionsRef = useRef<HTMLDetailsElement>(null)

  const focusErrors = useCallback((fieldErrors: DraftErrors) => {
    if (fieldErrors.target) targetRef.current?.focus()
    else if (fieldErrors.question) questionRef.current?.focus()
    else if (fieldErrors.userStyle || fieldErrors.omens) {
      if (optionsRef.current) optionsRef.current.open = true
      if (fieldErrors.userStyle) styleRef.current?.focus()
      else optionsRef.current?.querySelector<HTMLInputElement>('input[type="checkbox"]')?.focus()
    }
  }, [])

  useEffect(() => () => { requestRef.current?.abort(); requestRef.current = null }, [])
  useEffect(() => {
    if (!isGenerating && pendingFocusRef.current) {
      focusErrors(pendingFocusRef.current)
      pendingFocusRef.current = null
    }
  }, [isGenerating, focusErrors])

  function invalidateResult() {
    setPreview(null)
    setReport(null)
    setRequestError(null)
    setMessage('')
  }

  function updateField(field: 'target' | 'question' | 'userStyle', value: string) {
    setDraft((current) => ({ ...current, [field]: value }))
    setErrors((current) => ({ ...current, [field]: undefined }))
    invalidateResult()
  }

  function toggleOmen(value: ReportOmen) {
    setDraft((current) => ({
      ...current,
      omens: current.omens.includes(value) ? current.omens.filter((omen) => omen !== value) : [...current.omens, value],
    }))
    setErrors((current) => ({ ...current, omens: undefined }))
    invalidateResult()
  }

  function prepareDraft() {
    const nextErrors = validateDraft(draft)
    setErrors(nextErrors)
    if (Object.keys(nextErrors).length) {
      setPreview(null)
      setMessage('请检查标出的输入内容。')
      focusErrors(nextErrors)
      return null
    }
    return normalizeDraft(draft)
  }

  function previewTask() {
    if (requestRef.current) return
    const prepared = prepareDraft()
    if (!prepared) return
    setPreview(prepared)
    setRequestError(null)
    setMessage(report ? '研究任务已预览，右侧保留本次演示报告。' : '研究任务已预览，可以生成演示报告。')
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (requestRef.current) return
    const prepared = prepareDraft()
    if (!prepared) return
    const controller = new AbortController()
    requestRef.current = controller
    setPreview(prepared)
    setReport(null)
    setRequestError(null)
    setMessage('')
    setIsGenerating(true)
    try {
      const result = await generateMockReport(prepared, controller.signal)
      if (requestRef.current !== controller) return
      setReport(result)
      setPreview({ target: result.target, question: result.question, userStyle: result.userStyle, omens: result.omens })
      setMessage('演示报告已返回，尚未进行真实资料研究。')
    } catch (error) {
      if (requestRef.current !== controller) return
      const failure = error instanceof ResearchApiError ? error : new ResearchApiError('报告生成失败，请稍后重试。', 'UNKNOWN_ERROR')
      setRequestError(failure)
      setErrors(failure.fieldErrors)
      pendingFocusRef.current = failure.fieldErrors
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null
        setIsGenerating(false)
      }
    }
  }

  function fillExample() {
    setDraft({ ...EXAMPLE_DRAFT, omens: [...EXAMPLE_DRAFT.omens] })
    invalidateResult()
    setErrors({})
    setMessage('已填入示例，可修改或直接生成演示报告。')
    targetRef.current?.focus()
  }

  function reset() {
    const wasGenerating = requestRef.current !== null
    requestRef.current?.abort()
    requestRef.current = null
    pendingFocusRef.current = null
    setIsGenerating(false)
    setDraft({ ...EMPTY_DRAFT })
    invalidateResult()
    setErrors({})
    setMessage(wasGenerating ? '已取消请求并清空研究任务。' : '已清空研究任务。')
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
        <form className="research-form" onSubmit={submit} noValidate aria-busy={isGenerating}>
          <div className="form-heading">
            <h2>准备研究任务</h2>
            <button className="text-button" type="button" onClick={fillExample} disabled={isGenerating}>填入示例 <span aria-hidden="true">↗</span></button>
          </div>
          <div className="form-field">
            <label htmlFor="research-target">研究对象 <span>必填</span></label>
            <input
              ref={targetRef} id="research-target" name="target" required autoComplete="off" disabled={isGenerating}
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
              ref={questionRef} id="research-question" name="question" required rows={4} disabled={isGenerating}
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
              <span className="options-note">{draft.userStyle.trim() || draft.omens.length ? '已设置' : '选填'} <span aria-hidden="true">＋</span></span>
            </summary>
            <div className="options-content">
              <div className="form-field">
                <label htmlFor="research-style">研究偏好</label>
                <textarea
                  ref={styleRef} id="research-style" name="userStyle" rows={2} disabled={isGenerating}
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
              <fieldset className="omens-fieldset" disabled={isGenerating} aria-describedby={errors.omens ? 'omens-error' : undefined}>
                <legend>研究预兆 <span>可多选</span></legend>
                <div className="omen-options">
                  {OMENS.map((omen) => (
                    <label className={`omen-option${draft.omens.includes(omen.value) ? ' omen-option--selected' : ''}`} key={omen.value}>
                      <input type="checkbox" name="omens" value={omen.value} checked={draft.omens.includes(omen.value)} onChange={() => toggleOmen(omen.value)} />
                      <span><strong>{omen.name}</strong><span>{omen.description}</span></span>
                    </label>
                  ))}
                </div>
                {errors.omens && <p className="field-error" id="omens-error">{errors.omens}</p>}
              </fieldset>
            </div>
          </details>
          <div className="form-actions">
            <button className="primary-button" type="submit" disabled={isGenerating}>{isGenerating ? '正在获取报告…' : '生成演示报告'} <span aria-hidden="true">→</span></button>
            <button className="secondary-button" type="button" onClick={previewTask} disabled={isGenerating}>预览任务</button>
            <button className="secondary-button" type="button" onClick={reset}>{isGenerating ? '取消并清空' : '清空'}</button>
          </div>
          {requestError && <div className="request-error" role="alert"><strong>报告未生成</strong><p>{requestError.message}</p></div>}
          <p className="form-message" role="status">{message || (isGenerating ? '正在等待研究服务返回演示报告。' : '可先预览任务，也可以直接生成演示报告。')}</p>
        </form>
      </section>
      <ResearchPreview draft={preview} report={report} isGenerating={isGenerating} hasError={!!requestError} />
    </div>
  )
}
