import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { editUserMemory, getUserMemory } from '../../api/memory'
import type { MemoryEdit, MemoryNote, UserMemory } from '../../api/memory'

const CATEGORIES = { research_preference: '研究偏好', risk_focus: '风险关注点', watch_company: '观察对象' } as const

function MemoryNoteRow({ note, busy, save }: { note: MemoryNote; busy: boolean; save: (edit: MemoryEdit) => Promise<boolean> }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(note.text)
  const [category, setCategory] = useState(note.category)
  useEffect(() => { if (!editing) { setText(note.text); setCategory(note.category) } }, [note.text, note.category, editing])
  return <li className="memory-note">
    <p className="memory-note-label">{CATEGORIES[note.category]} · {note.status === 'confirmed' ? '你已确认' : '模型建议 · 待确认'}</p>
    {editing ? <form onSubmit={(event) => {
      event.preventDefault()
      void save({ action: 'save', id: note.id, text: text.trim(), category }).then((ok) => { if (ok) setEditing(false) })
    }}>
      <label htmlFor={`memory-text-${note.id}`}>修改记忆</label>
      <textarea id={`memory-text-${note.id}`} value={text} onChange={(e) => setText(e.target.value)} rows={3} maxLength={500} required disabled={busy} />
      <label htmlFor={`memory-category-${note.id}`}>记忆类型</label>
      <select id={`memory-category-${note.id}`} value={category} onChange={(e) => setCategory(e.target.value as MemoryNote['category'])} disabled={busy}>
        {Object.entries(CATEGORIES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
      <div className="memory-actions"><button className="secondary-button" disabled={busy || !text.trim()}>保存记忆</button><button className="text-button" type="button" onClick={() => setEditing(false)}>取消</button></div>
    </form> : <>
      <p>{note.text}</p>
      {note.quote && <details><summary>查看建议依据</summary><blockquote>{note.quote}</blockquote>{note.runId && <a href={`?task=${note.runId}`}>打开来源研究 ↗</a>}</details>}
      <div className="memory-actions">
        {note.status === 'suggested' && <button type="button" className="secondary-button" disabled={busy} onClick={() => { void save({ action: 'save', id: note.id, text: note.text, category: note.category }) }}>确认采用</button>}
        <button type="button" className="text-button" disabled={busy} onClick={() => setEditing(true)}>修改</button>
        <button type="button" className="text-button" disabled={busy} onClick={() => { void save({ action: 'forget', id: note.id }) }}>{note.status === 'suggested' ? '忽略建议' : '移除记忆'}</button>
      </div>
    </>}
  </li>
}

/** 用户可见、可改的长期记忆；GET和手动整理不调用模型，候选由正常研究中的工具调用产生。 */
export function UserMemoryPanel({ refreshKey }: { refreshKey: unknown }) {
  const [data, setData] = useState<UserMemory | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [text, setText] = useState('')
  const [category, setCategory] = useState<MemoryNote['category']>('research_preference')
  useEffect(() => {
    const controller = new AbortController()
    const load = () => { void getUserMemory(controller.signal).then((next) => { if (!controller.signal.aborted) { setData(next); setError('') } })
      .catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message) }) }
    load()
    window.addEventListener('path-of-market-memory-changed', load)
    return () => { controller.abort(); window.removeEventListener('path-of-market-memory-changed', load) }
  }, [refreshKey])

  async function save(edit: MemoryEdit) {
    if (!data || busy) return false
    setBusy(true); setError(''); setMessage('')
    try {
      setData(await editUserMemory(data.revision, edit)); setMessage('研究记忆已保存，下次研究或追问会读取更新。'); return true
    } catch (reason) { setError(reason instanceof Error ? reason.message : '保存失败，原输入保留。'); return false }
    finally { setBusy(false) }
  }
  function add(event: FormEvent) {
    event.preventDefault()
    if (text.trim()) void save({ action: 'save', text: text.trim(), category }).then((ok) => { if (ok) setText('') })
  }
  return <section className="user-memory" aria-label="研究记忆与偏好">
    <details><summary>研究记忆与偏好 <span>{data ? `${data.companyCount} 个研究对象 · ${data.notes.filter((n) => n.status === 'confirmed').length} 条确认偏好` : '正在读取'}</span></summary>
      <p>记住研究经历与关注点，让下一次研究接得上。</p>
      {data && <>
        <label className="memory-toggle"><input type="checkbox" checked={data.enabled} disabled={busy} onChange={(e) => { void save({ action: 'toggle', enabled: e.target.checked }) }} />研究时使用记忆</label>
        <p className="memory-help">{data.enabled ? '新任务读取相关记忆；本次输入优先。' : '已关闭：新任务不使用偏好，也不新增建议。原研究记录保留。'}</p>
        <h3>已确认的偏好</h3>
        {!data.notes.some((n) => n.status === 'confirmed') && <p>还没有确认偏好，可直接添加，也可确认下方建议。</p>}
        <ol className="memory-notes">{data.notes.filter((n) => n.status === 'confirmed').map((note) => <MemoryNoteRow key={note.id} note={note} busy={busy} save={save} />)}</ol>
        <form className="memory-add" onSubmit={add}>
          <label htmlFor="new-memory-text">添加长期偏好</label>
          <textarea id="new-memory-text" value={text} onChange={(e) => setText(e.target.value)} maxLength={500} rows={3} required disabled={busy} placeholder="例如：每次分析都列出反方证据，重点解释现金流。" />
          <label htmlFor="new-memory-category">记忆类型</label>
          <select id="new-memory-category" value={category} disabled={busy} onChange={(e) => setCategory(e.target.value as MemoryNote['category'])}>
            {Object.entries(CATEGORIES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <button className="secondary-button" disabled={busy || !text.trim()}>保存偏好</button>
        </form>
        <h3>待确认建议</h3>
        <p className="memory-help">模型从用户表达中提出，附原话依据；确认后才作为长期偏好使用。</p>
        {!data.notes.some((n) => n.status === 'suggested') && <p>暂无建议。</p>}
        <ol className="memory-notes">{data.notes.filter((n) => n.status === 'suggested').map((note) => <MemoryNoteRow key={note.id} note={note} busy={busy} save={save} />)}</ol>
        <h3>研究经历与主题观察</h3>
        <p className="memory-help">{data.observationScope}</p>
        {!!data.themes.length && <ul className="memory-themes">{data.themes.map((theme) => <li key={theme.name}><details><summary>{theme.name} · {theme.count} 次</summary><ul>{theme.evidence.map((e) => <li key={e.nodeId}><a href={`?task=${e.rootTaskId}`}>{e.target}：{e.question.slice(0, 90)} ↗</a></li>)}</ul></details></li>)}</ul>}
        <ul className="memory-companies">{data.companies.map((company) => <li key={company.target}>
          <a href={`?task=${company.latestTaskId}`}>{company.target} ↗</a><span>{company.researchCount} 次研究 · {company.followupCount} 次追问</span>
          <button type="button" className="text-button" disabled={busy} onClick={() => { void save({ action: 'ignore_company', target: company.target }) }}>忽略经历</button>
        </li>)}</ul>
        {!!data.ignoredTargets.length && <details><summary>已忽略的对象</summary>{data.ignoredTargets.map((target) => <p key={target}>{target} <button type="button" className="text-button" disabled={busy} onClick={() => { void save({ action: 'restore_company', target }) }}>重新纳入</button></p>)}</details>}
        <details><summary>最近研究问题 · {data.totalEpisodes} 条经历</summary><ol className="memory-history">{data.episodes.map((e) => <li key={e.nodeId}><a href={`?task=${e.rootTaskId}`}>{e.target} · {e.kind === 'research' ? '研究' : '追问'} ↗</a><p>{e.question}</p></li>)}</ol></details>
      </>}
      <button type="button" className="text-button" disabled={busy} onClick={() => { window.dispatchEvent(new Event('path-of-market-memory-changed')) }}>刷新记忆</button>
      {message && <p role="status">{message}</p>}
    </details>
    {error && <p className="field-error" role="alert">{error}</p>}
  </section>
}
