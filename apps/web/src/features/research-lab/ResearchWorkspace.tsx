import { useCallback, useEffect, useReducer, useRef } from 'react'
import type { FormEvent } from 'react'
import { generateReport, waitForAgent, cancelAgentJob, getAgentJob, ResearchApiError } from '../../api/research'
import { ResearchPreview } from './ResearchPreview'
import { RecentSessions } from './RecentSessions'
import { characterCount, normalizeDraft, OMENS, validateDraft } from './researchDraft'
import type { DraftErrors } from './researchDraft'
import { initialWorkspaceState, workspaceReducer } from './workspaceState'

export function ResearchWorkspace() {
  const [state, dispatch] = useReducer(workspaceReducer, undefined, initialWorkspaceState)
  const { draft, preview, errors, message, report, mode, job, resumeId, asOfDate, requestError, isGenerating } = state
  const requestRef = useRef<AbortController | null>(null)
  const pendingFocusRef = useRef<DraftErrors | null>(null)
  const targetRef = useRef<HTMLInputElement>(null)
  const questionRef = useRef<HTMLTextAreaElement>(null)
  const styleRef = useRef<HTMLTextAreaElement>(null)
  const dateRef = useRef<HTMLInputElement>(null)
  const optionsRef = useRef<HTMLDetailsElement>(null)

  const focusErrors = useCallback((fieldErrors: DraftErrors) => {
    if (fieldErrors.target) targetRef.current?.focus()
    else if (fieldErrors.question) questionRef.current?.focus()
    else if (fieldErrors.asOfDate || fieldErrors.userStyle || fieldErrors.omens) {
      if (optionsRef.current) optionsRef.current.open = true
      if (fieldErrors.asOfDate) dateRef.current?.focus()
      else if (fieldErrors.userStyle) styleRef.current?.focus()
      else optionsRef.current?.querySelector<HTMLInputElement>('input[type="checkbox"]')?.focus()
    }
  }, [])

  useEffect(() => () => { requestRef.current?.abort(); requestRef.current = null }, [])
  useEffect(() => {
    const taskId = new URLSearchParams(window.location.search).get('task')
    if (!taskId || !/^[0-9a-f-]{36}$/i.test(taskId)) return
    const controller = new AbortController()
    void getAgentJob(taskId, controller.signal).then((next) => {
      if (controller.signal.aborted || requestRef.current) return
      if (next.report) {
        dispatch({ type: 'jobProgress', job: next })
        dispatch({ type: 'agentReportLoaded', report: next.report, message: '已打开研究结果，本次查看不调用模型。' })
      } else {
        sessionStorage.setItem('path-of-market-active-job', taskId)
        dispatch({ type: 'jobOpened', job: next })
      }
    }).catch((error) => { if (!controller.signal.aborted && error instanceof ResearchApiError) dispatch({ type: 'requestFailed', error }) })
    return () => controller.abort()
  }, [])
  useEffect(() => {
    if (!isGenerating && pendingFocusRef.current) {
      focusErrors(pendingFocusRef.current)
      pendingFocusRef.current = null
    }
  }, [isGenerating, focusErrors])

  function prepareDraft() {
    const nextErrors = validateDraft(draft)
    if (mode !== 'mock' && (!/^\d{4}-\d{2}-\d{2}$/.test(asOfDate) || Number.isNaN(Date.parse(asOfDate)))) nextErrors.asOfDate = '请填写有效的研究截止日期。'
    if (Object.keys(nextErrors).length) {
      dispatch({ type: 'draftRejected', errors: nextErrors })
      focusErrors(nextErrors)
      return null
    }
    return normalizeDraft(draft)
  }

  function previewTask() {
    if (requestRef.current) return
    const prepared = prepareDraft()
    if (!prepared) return
    dispatch({ type: 'previewed', draft: prepared, message: report ? '研究任务已预览，右侧保留本次报告。' : '研究任务已预览，可以生成报告。' })
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (requestRef.current) return
    const prepared = prepareDraft()
    if (!prepared) return
    const controller = new AbortController()
    requestRef.current = controller
    dispatch({ type: 'submitStarted', draft: prepared })
    try {
      const result = await generateReport(prepared, controller.signal, mode, asOfDate, (next) => {
        if (requestRef.current === controller) dispatch({ type: 'submitProgress', job: next })
      })
      if (requestRef.current !== controller) return
      dispatch({
        type: 'submitSucceeded', report: result,
        message: result.mode === 'agent' ? result.run.status === 'completed' ? '研究已完成，可查看来源、阅读覆盖与行情。' : '研究部分完成，请查看停止原因与资料缺口。' : result.mode === 'model' ? '模型分析已返回；本次未检索真实资料。' : '演示报告已返回，尚未进行真实资料研究。',
      })
    } catch (error) {
      if (requestRef.current !== controller) return
      const failure = error instanceof ResearchApiError ? error : new ResearchApiError('报告生成失败，请稍后重试。', 'UNKNOWN_ERROR')
      dispatch({ type: 'requestFailed', error: failure, errors: failure.fieldErrors })
      pendingFocusRef.current = failure.fieldErrors
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null
        dispatch({ type: 'requestFinished' })
      }
    }
  }

  async function resumeResearch() {
    if (!resumeId || requestRef.current) return
    const controller = new AbortController()
    requestRef.current = controller
    dispatch({ type: 'resumeStarted' })
    try {
      const result = await waitForAgent(resumeId, controller.signal, (next) => { if (requestRef.current === controller) dispatch({ type: 'jobProgress', job: next }) })
      if (requestRef.current !== controller) return
      dispatch({ type: 'agentReportLoaded', report: result, message: '已恢复研究结果，请查看来源与完成范围。' })
    } catch (error) {
      if (requestRef.current !== controller) return
      const failure = error instanceof ResearchApiError ? error : new ResearchApiError('无法恢复研究。', 'RESEARCH_FAILED')
      const notFound = failure.code === 'RESEARCH_NOT_FOUND'
      if (notFound) sessionStorage.removeItem('path-of-market-active-job')
      dispatch({ type: 'requestFailed', error: failure, clearResume: notFound })
    } finally {
      if (requestRef.current === controller) { requestRef.current = null; dispatch({ type: 'requestFinished' }) }
    }
  }

  function fillExample() {
    dispatch({ type: 'exampleFilled' })
    targetRef.current?.focus()
  }

  function reset() {
    const wasGenerating = requestRef.current !== null
    requestRef.current?.abort()
    const stoppingId = job?.taskId || resumeId
    if (stoppingId) void cancelAgentJob(stoppingId).then(() => sessionStorage.removeItem('path-of-market-active-job')).catch(() => {
      sessionStorage.setItem('path-of-market-active-job', stoppingId)
      dispatch({ type: 'cancelUnconfirmed', taskId: stoppingId, message: '已停止等待；取消未确认，可恢复研究核对任务状态。' })
    })
    requestRef.current = null
    pendingFocusRef.current = null
    dispatch({ type: 'reset', message: wasGenerating ? '已取消请求并清空研究任务。' : '已清空研究任务。' })
    targetRef.current?.focus()
  }

  return (
    <div className={`workspace-layout${report?.mode === 'agent' ? ' workspace-layout--report' : ''}`}>
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
          <fieldset className="mode-selector" disabled={isGenerating}>
            <legend>生成方式</legend>
            {([{ value: 'agent', label: '真实研究' }, { value: 'model', label: '模型思路' }, { value: 'mock', label: '演示报告' }] as const).map((option) => (
              <label key={option.value}><input type="radio" name="researchMode" value={option.value} checked={mode === option.value}
                onChange={() => dispatch({ type: 'modeChanged', mode: option.value })} />{option.label}</label>
            ))}
            <p>{mode === 'agent' ? '自动获取报告、分批阅读并分析行情，需要多次模型调用；进度会持续显示。' : mode === 'model' ? '调用模型生成研究思路，不检索资料。' : '使用固定内容检查应用，不调用模型。'}</p>
          </fieldset>
          <div className="form-field">
            <label htmlFor="research-target">研究对象 <span>必填</span></label>
            <input
              ref={targetRef} id="research-target" name="target" required autoComplete="off" disabled={isGenerating}
              value={draft.target} onChange={(event) => dispatch({ type: 'fieldEdited', field: 'target', value: event.target.value })}
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
              value={draft.question} onChange={(event) => dispatch({ type: 'fieldEdited', field: 'question', value: event.target.value })}
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
                <label htmlFor="research-date">研究截止日期</label>
                <input ref={dateRef} id="research-date" type="date" value={asOfDate} disabled={isGenerating}
                  onChange={(event) => dispatch({ type: 'dateEdited', value: event.target.value })}
                  aria-invalid={!!errors.asOfDate} aria-describedby={errors.asOfDate ? 'date-error' : undefined} />
                {errors.asOfDate && <p className="field-error" id="date-error">{errors.asOfDate}</p>}
              </div>
              <div className="form-field">
                <label htmlFor="research-style">研究偏好</label>
                <textarea
                  ref={styleRef} id="research-style" name="userStyle" rows={2} disabled={isGenerating}
                  value={draft.userStyle} onChange={(event) => dispatch({ type: 'fieldEdited', field: 'userStyle', value: event.target.value })}
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
                      <input type="checkbox" name="omens" value={omen.value} checked={draft.omens.includes(omen.value)} onChange={() => dispatch({ type: 'omenToggled', value: omen.value })} />
                      <span><strong>{omen.name}</strong><span>{omen.description}</span></span>
                    </label>
                  ))}
                </div>
                {errors.omens && <p className="field-error" id="omens-error">{errors.omens}</p>}
              </fieldset>
            </div>
          </details>
          <div className="form-actions">
            <button className="primary-button" type="submit" disabled={isGenerating}>{isGenerating ? '研究进行中…' : mode === 'agent' ? '开始真实研究' : mode === 'model' ? '生成模型分析' : '生成演示报告'} <span aria-hidden="true">→</span></button>
            <button className="secondary-button" type="button" onClick={previewTask} disabled={isGenerating}>预览任务</button>
            <button className="secondary-button" type="button" onClick={reset}>{isGenerating ? '取消并清空' : '清空'}</button>
          </div>
          {resumeId && !isGenerating && <button className="text-button" type="button" onClick={() => void resumeResearch()}>恢复上次研究 ↗</button>}
          {job && <div className="research-progress" aria-live="polite">
            <strong>{job.progress}</strong>
            <p>模型调用 {job.modelCalls} 次{typeof job.usage.total_tokens === 'number' ? ` · 累计 ${job.usage.total_tokens.toLocaleString()} token` : ''}</p>
            {job.coverage.map((entry) => <p key={entry.sourceId}>{entry.processedPages.length}/{entry.pageCount} 页文本已处理{entry.textComplete ? ' · 文本阅读完成' : ''}</p>)}
            <details><summary>查看最近动作</summary><ol>{job.events.slice(-8).map((entry) => <li key={entry.id}>{entry.message}</li>)}</ol></details>
          </div>}
          {requestError && <div className="request-error" role="alert"><strong>报告未生成</strong><p>{requestError.message}</p></div>}
          <p className="form-message" role="status">{message || (isGenerating ? '正在等待研究服务返回报告。' : '可先预览任务，也可以直接生成报告。')}</p>
        </form>
        <RecentSessions refreshKey={isGenerating ? 'running' : report} />
      </section>
      <ResearchPreview draft={preview} report={report} isGenerating={isGenerating} hasError={!!requestError} job={mode === 'agent' ? job : null} />
    </div>
  )
}
