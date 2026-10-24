import { Fragment } from 'react'

/** 只解析段落和加粗，所有外部文字仍通过React转义，不接受模型HTML。 */
export function ReportText({ text }: { text: string }) {
  return <div className="report-prose">{text.split(/\n+/).map((line,i) => line.trim() ? <p key={i}>{line.split(/(\*\*[^*]+\*\*)/g).map((part,j) => part.startsWith('**') && part.endsWith('**') ? <strong key={j}>{part.slice(2,-2)}</strong> : <Fragment key={j}>{part}</Fragment>)}</p> : null)}</div>
}
