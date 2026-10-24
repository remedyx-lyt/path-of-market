import { useState } from 'react'
import type { ReactNode } from 'react'
import type { EvidenceSource, FinancialData, FinancialRow } from '../../api/research'

const COLORS = ['#20231f', '#70a895', '#8a8d86']
const FLOW = new Set(['revenue','netProfit','recurringProfit','operatingCashFlow','rdExpense'])
const METRICS = ['revenue','netProfit','recurringProfit','operatingCashFlow','totalAssets','netAssets','rdExpense']

function valueFor(row: FinancialRow, key: string, kind: string): number | null {
  if (kind === 'yoy') return row.yoy[key]?.value ?? null
  const value = row.values[key]
  return value == null ? null : kind === 'amount' ? value / 1e8 : value
}

export function FinancialCharts({ data, sources }: { data: FinancialData; sources: EvidenceSource[] }) {
  const [selected, setSelected] = useState('annual')
  const dataset = data.datasets.find((d) => d.id === selected) || data.datasets[0]
  if (!dataset) return <section className="financial-section"><h3>财务表图</h3><p>本次尚无可核查的财务底稿。</p>{data.gaps.map((g) => <p key={g}>{g}</p>)}</section>
  const metrics = METRICS.filter((k) => dataset.rows.some((r) => r.values[k] != null))
  const charts = data.charts.filter((c) => c.datasetId === dataset.id)
  function citation(row: FinancialRow, key: string) {
    const evidence = row.evidence[key]
    const source = sources.find((s) => s.sourceId === evidence?.sourceId)
    return source && evidence ? <a href={`${source.url}#page=${evidence.page}`} target="_blank" rel="noreferrer"
      title={`${source.title} PDF第${evidence.page}页：原值 ${evidence.rawValue}${evidence.unit}`} aria-label={`${row.periodLabel}${data.labels[key]}来源第${evidence.page}页`}>↗</a> : null
  }
  return <section className="financial-section" id="financial-analysis" aria-labelledby="financial-heading">
    <div className="report-section-heading"><div><span className="report-kicker">FINANCIAL OVERVIEW</span><h3 id="financial-heading">经营数据与同比趋势</h3></div><span>金额 · 亿元</span></div>
    <div className="chart-switch" role="group" aria-label="财务比较期间">{data.datasets.map((d) => <button type="button" key={d.id} aria-pressed={dataset.id === d.id} onClick={() => setSelected(d.id)}>{d.label}</button>)}</div>
    <p className="financial-note">仅比较相同期间；年度与半年分开展示。↗ 可核对原始金额、单位和 PDF 页码。</p>
    <div className="financial-grid">{charts.map((chart) => <DataChart key={chart.id} chart={chart} rows={dataset.rows} labels={data.labels} sources={sources} />)}</div>
    <details className="financial-table-details" open><summary>核对数据与同比</summary><div className="table-scroll"><table className="research-table financial-table">
      <caption>{dataset.label}财务对照表 · 金额单位亿元，同比单位%</caption>
      <thead><tr><th scope="col">指标</th>{dataset.rows.map((r) => <th scope="col" key={r.year}>{r.periodLabel}</th>)}</tr></thead>
      <tbody>{metrics.map((key) => <MetricRows key={key} metric={key} rows={dataset.rows} label={data.labels[key]} citation={citation} />)}
        {dataset.rows.some((r) => r.values.attributableMargin != null) && <tr><th scope="row">归母净利率（计算）</th>{dataset.rows.map((r) => <td key={r.year}>{r.values.attributableMargin == null ? '—' : `${r.values.attributableMargin.toFixed(2)}%`}</td>)}</tr>}
      </tbody>
    </table></div></details>
    <p className="financial-note">归母净利率＝归母净利润÷营收；经营现金流与归母利润的归属口径不同，对比只作研究线索。同比为本期/上年同期间−1；零或负基数、缺数据时不显示常规百分比。</p>
    {data.gaps.length > 0 && <details className="financial-gaps"><summary>数据缺口与取数限制（{data.gaps.length}）</summary><p>以下记录各次取数尝试的限制；同一指标在其他原页通过核对的数据，仍可保留在表中。</p>{data.gaps.map((g) => <p key={g}>{g}</p>)}</details>}
  </section>
}

function MetricRows({ metric, rows, label, citation }: { metric: string; rows: FinancialRow[]; label: string; citation: (row: FinancialRow,key: string) => ReactNode }) {
  return <><tr><th scope="row">{label}</th>{rows.map((row) => <td key={row.year}>{row.values[metric] == null ? '—' : <>{(row.values[metric] / 1e8).toFixed(2)} {citation(row,metric)}</>}</td>)}</tr>
    {FLOW.has(metric) && <tr className="yoy-row"><th scope="row">同比</th>{rows.map((row) => <td key={row.year} title={row.yoy[metric]?.reason}>{row.yoy[metric]?.value == null ? '—' : `${row.yoy[metric].value! > 0 ? '+' : ''}${row.yoy[metric].value!.toFixed(2)}%`}</td>)}</tr>}
  </>
}

function DataChart({ chart, rows, labels, sources }: { chart: FinancialData['charts'][number]; rows: FinancialRow[]; labels: Record<string,string>; sources: EvidenceSource[] }) {
  const values = rows.flatMap((row) => chart.keys.map((key) => valueFor(row,key,chart.valueKind))).filter((v): v is number => v != null)
  if (!values.length) return null
  const low = Math.min(0,...values), high = Math.max(0,...values), spread = high - low || 1
  const w = 540, h = 285, left = 72, top = 24, plotW = 441, plotH = 205
  const y = (v: number) => top + (high - v) / spread * plotH
  const step = plotW / Math.max(rows.length,1)
  const x = (i: number) => left + step * (i + .5)
  const unit = chart.valueKind === 'amount' ? '亿元' : '%'
  const sourceIds = new Set(rows.flatMap((r) => chart.keys.flatMap((key) => key === 'attributableMargin' ? [r.evidence.revenue?.sourceId,r.evidence.netProfit?.sourceId] : [r.evidence[key]?.sourceId])).filter(Boolean))
  return <figure className="financial-chart" aria-label={chart.title}>
    <figcaption>{chart.title}</figcaption>
    <div className="chart-legend">{chart.keys.map((key,i) => <span key={key}><i style={{ background:COLORS[i] }} />{labels[key]}{chart.valueKind==='yoy' ? '同比' : ''}</span>)}<span className="chart-unit">{unit}</span></div>
    <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`${chart.title}，单位${unit}，对应数值见下方数据表`}>
      {[0,1,2,3,4].map((i) => { const v = low + spread * i/4; return <g key={i}><line x1={left} x2={left+plotW} y1={y(v)} y2={y(v)} stroke="#e5e5df" /><text x={left-9} y={y(v)+4} textAnchor="end" fill="#73756e" fontSize="13">{v.toFixed(1)}</text></g> })}
      <line x1={left} x2={left+plotW} y1={y(0)} y2={y(0)} stroke="#a7aaa1" />
      {chart.keys.map((key,k) => {
        const series = rows.map((r) => valueFor(r,key,chart.valueKind))
        if (chart.type === 'bar') return <g key={key}>{series.map((v,i) => v == null ? null : <rect key={rows[i].year} x={x(i)-step*.3+k*step*.6/chart.keys.length} y={Math.min(y(v),y(0))} width={step*.6/chart.keys.length-3} height={Math.max(1,Math.abs(y(v)-y(0)))} fill={COLORS[k]}><title>{rows[i].periodLabel} · {labels[key]}：{v.toFixed(2)}{unit}</title></rect>)}</g>
        let pen = false
        const d = series.map((v,i) => { if (v == null) { pen=false; return '' } const point=`${pen?'L':'M'}${x(i)},${y(v)}`; pen=true; return point }).join(' ')
        return <g key={key}><path d={d} fill="none" stroke={COLORS[k]} strokeWidth="2.5" />{series.map((v,i) => v == null ? null : <circle key={rows[i].year} cx={x(i)} cy={y(v)} r="4.5" fill={COLORS[k]}><title>{rows[i].periodLabel} · {labels[key]}：{v.toFixed(2)}{unit}</title></circle>)}</g>
      })}
      {rows.map((r,i) => <text key={r.year} x={x(i)} y={h-18} textAnchor="middle" fill="#686b63" fontSize="14">{r.periodLabel}</text>)}
    </svg>
    <p className="chart-source">来源：{sources.filter((s) => sourceIds.has(s.sourceId)).map((s,i) => <span key={s.sourceId}>{i>0?'；':''}<a href={s.url} target="_blank" rel="noreferrer">{s.title} ↗</a></span>)}；计算及页码见数据表。</p>
  </figure>
}
