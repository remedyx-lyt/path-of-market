import type { EvidenceSource, SectionTable } from '../../api/research'
import { ChartDataLabels } from './ChartDataLabels'

const COLORS = ['#20231f', '#70a895', '#8a8d86', '#abb18b']

/** 格子里的第一个数字（去千分位）；没有数字的格子不画图。 */
function numberIn(cell: string): number | null {
  const match = cell.replace(/,/g, '').match(/-?\d+(?:\.\d+)?/)
  return match ? Number(match[0]) : null
}

/** 模型根据原文做的数据表：表格始终展开；程序逐格核对，未在所引原页找到的数字标 *。 */
export function SectionTables({ tables, sources, showDataLabels = true }: { tables: SectionTable[]; sources: EvidenceSource[]; showDataLabels?: boolean }) {
  return <div className="section-tables">{tables.map((table, i) => <TableFigure key={i} table={table} sources={sources} showDataLabels={showDataLabels} />)}</div>
}

function TableFigure({ table, sources, showDataLabels }: { table: SectionTable; sources: EvidenceSource[]; showDataLabels: boolean }) {
  const unmatched = new Set((table.verification?.unmatched ?? []).map(([r, c]) => `${r}:${c}`))
  const link = (sourceId: string, page: number | null) => {
    const source = sources.find((s) => s.sourceId === sourceId)
    const label = { market: '行情数据', database: '财务报表数据', web: '网页', document: '原文' }[source?.kind ?? 'document']
    if (source && page == null) return <a href={source.url} target="_blank" rel="noreferrer" title={source.title}>{label} ↗</a>
    return source ? <a href={`${source.url}#page=${page}`} target="_blank" rel="noreferrer" title={source.title}>第{page}页 ↗</a> : null
  }
  const v = table.verification
  return <figure className="financial-chart section-table">
    <figcaption>{table.title}{table.unit ? <span className="chart-unit"> · {table.unit}</span> : null}</figcaption>
    {table.chart !== 'none' && <TableChart table={table} showDataLabels={showDataLabels} />}
    <div className="table-scroll"><table className="research-table">
      <thead><tr><th scope="col">{table.labelHeader || '项目'}</th>{table.columns.map((c) => <th scope="col" key={c}>{c}</th>)}<th scope="col">来源</th></tr></thead>
      <tbody>{table.rows.map((row, r) => <tr key={r}>
        <th scope="row" title={row.note || undefined}>{row.label}{row.note ? <span className="row-note">{row.note}</span> : null}</th>
        {row.cells.map((cell, c) => unmatched.has(`${r}:${c}`)
          ? <td key={c} className="cell-unverified" title="未在所引资料中找到该数字，可能是计算值">{cell}*</td>
          : <td key={c}>{cell}</td>)}
        <td>{link(row.sourceId, row.page)}{row.alsoFrom?.map((c, j) => <span key={j}> {link(c.sourceId, c.page ?? null)}</span>)}</td>
      </tr>)}</tbody>
    </table></div>
    <p className="chart-source">
      {table.note ? `${table.note} ` : ''}
      {v ? `程序核对：${v.matchedCells}/${v.checkedCells} 个数字在所引资料中找到${unmatched.size ? '；标 * 的未在资料中找到，多为计算值，请按说明核对' : ''}。` : ''}
      表格由模型根据已读原文整理。
    </p>
  </figure>
}

function TableChart({ table, showDataLabels }: { table: SectionTable; showDataLabels: boolean }) {
  const series = table.chartColumns.map((col) => ({ col, name: table.columns[col], values: table.rows.map((row) => numberIn(row.cells[col] ?? '')) }))
    .filter((s) => s.values.some((v) => v != null))
  const values = series.flatMap((s) => s.values).filter((v): v is number => v != null)
  if (!values.length) return null
  const low = Math.min(0, ...values), high = Math.max(0, ...values), spread = high - low || 1
  const w = 540, h = 285, left = 72, top = 24, plotW = 441, plotH = 205
  const y = (value: number) => top + (high - value) / spread * plotH
  const step = plotW / Math.max(table.rows.length, 1)
  const x = (i: number) => left + step * (i + .5)
  const barWidth = step * .6 / series.length - 3
  const maxChars = Math.max(2, Math.floor(step / 15))  // 横轴标签按柱宽截断，完整名称见悬浮提示与下方表格
  const barX = (i: number, k: number) => x(i) - step * .3 + k * step * .6 / series.length
  const labelPoints = series.flatMap((s, k) => s.values.flatMap((value, i) => value == null ? [] : [{
    id: `${s.col}-${i}`, x: table.chart === 'bar' ? barX(i, k) + barWidth / 2 : x(i), y: y(value), preferredY: y(value) + (value < 0 ? 19 : -9),
    text: table.rows[i].cells[s.col], description: `${table.rows[i].label} · ${s.name}：${table.rows[i].cells[s.col]}`,
  }]))
  return <>
    <div className="chart-legend">{series.map((s, k) => <span key={s.col}><i style={{ background: COLORS[k] }} />{s.name}</span>)}</div>
    <div className="chart-plot-scroll"><svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`${table.title}，数值见下方表格`}>
      {[0, 1, 2, 3, 4].map((i) => { const value = low + spread * i / 4; return <g key={i}><line x1={left} x2={left + plotW} y1={y(value)} y2={y(value)} stroke="#e5e5df" /><text x={left - 9} y={y(value) + 4} textAnchor="end" fill="#73756e" fontSize="13">{Number(value.toFixed(1))}</text></g> })}
      <line x1={left} x2={left + plotW} y1={y(0)} y2={y(0)} stroke="#a7aaa1" />
      {series.map((s, k) => {
        if (table.chart === 'bar') return <g key={s.col}>{s.values.map((value, i) => value == null ? null : <rect key={i} x={barX(i, k)} y={Math.min(y(value), y(0))} width={barWidth} height={Math.max(1, Math.abs(y(value) - y(0)))} fill={COLORS[k]}><title>{table.rows[i].label} · {s.name}：{table.rows[i].cells[s.col]}</title></rect>)}</g>
        let pen = false
        const d = s.values.map((value, i) => { if (value == null) { pen = false; return '' } const point = `${pen ? 'L' : 'M'}${x(i)},${y(value)}`; pen = true; return point }).join(' ')
        return <g key={s.col}><path d={d} fill="none" stroke={COLORS[k]} strokeWidth="2.5" />{s.values.map((value, i) => value == null ? null : <circle key={i} cx={x(i)} cy={y(value)} r="4.5" fill={COLORS[k]}><title>{table.rows[i].label} · {s.name}：{table.rows[i].cells[s.col]}</title></circle>)}</g>
      })}
      {showDataLabels && <ChartDataLabels points={labelPoints} bounds={{ left: left + 2, right: left + plotW - 2, top: 0, bottom: 248 }} />}
      {table.rows.map((row, i) => <text key={i} x={x(i)} y={h - 18} textAnchor="middle" fill="#686b63" fontSize="14"><title>{row.label}</title>{row.label.length > maxChars ? row.label.slice(0, maxChars) + '…' : row.label}</text>)}
    </svg></div>
  </>
}
