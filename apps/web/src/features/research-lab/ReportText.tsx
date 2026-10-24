import { Fragment } from 'react'
import type { ReactNode } from 'react'

/**
 * 报告正文的轻量排版：段落、要点列表（- / • 开头）、编号列表（1. 或 1、开头）、小标题（【…】或 ### 开头）与 **加粗**。
 * 只解析这几种标记，所有外部文字仍通过 React 转义，不接受模型 HTML。
 */
export function ReportText({ text }: { text: string }) {
  const blocks: ReactNode[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  const flush = () => {
    if (!list) return
    const items = list.items.map((item, i) => <li key={i}>{inline(item)}</li>)
    blocks.push(list.ordered ? <ol key={blocks.length}>{items}</ol> : <ul key={blocks.length}>{items}</ul>)
    list = null
  }
  for (const raw of text.split(/\n/)) {
    const line = raw.trim()
    const bullet = line.match(/^[-•·*]\s+(.*)$/)
    const numbered = line.match(/^\d{1,2}[.、）)]\s*(.*)$/)
    const heading = line.match(/^(?:#{2,4}\s+(.+)|【([^】]{1,40})】\s*(.*))$/)
    if (!line) { flush(); continue }
    if (bullet || numbered) {
      const ordered = !bullet
      if (list && list.ordered !== ordered) flush()
      list ??= { ordered, items: [] }
      list.items.push((bullet ?? numbered)![1])
      continue
    }
    flush()
    if (heading) {
      blocks.push(<h4 key={blocks.length} className="report-subhead">{inline(heading[1] ?? heading[2])}</h4>)
      if (heading[3]) blocks.push(<p key={blocks.length}>{inline(heading[3])}</p>)
      continue
    }
    blocks.push(<p key={blocks.length}>{inline(line)}</p>)
  }
  flush()
  return <div className="report-prose">{blocks}</div>
}

function inline(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, j) => part.startsWith('**') && part.endsWith('**') && part.length > 4
    ? <strong key={j}>{part.slice(2, -2)}</strong>
    : <Fragment key={j}>{part}</Fragment>)
}
