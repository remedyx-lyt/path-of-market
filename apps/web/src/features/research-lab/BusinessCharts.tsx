import { useState } from 'react'
import type { BusinessData, EvidenceSource, SectionDiagram } from '../../api/research'
import { ChartDataLabels } from './ChartDataLabels'

const COLORS = ['#20231f','#70a895','#a5b8ac','#d0d3c8','#626e65','#abb18b','#879497','#c2bba8']

export function BusinessCharts({ data, sources, ids, showDataLabels = true }: { data: BusinessData; sources: EvidenceSource[]; ids: string[]; showDataLabels?: boolean }) {
  const [period,setPeriod] = useState('annual')
  const all = data.datasets.filter((d) => ids.includes(d.id))
  const periods = [...new Set(all.map((d) => d.period))]
  const active = periods.includes(period) ? period : periods[0]
  const datasets = all.filter((d) => d.period===active)
  return <div className="business-figures section-figures">
    <div className="chart-switch" role="group" aria-label="业务比较期间">{periods.map((p) => <button key={p} type="button" aria-pressed={p===active} onClick={() => setPeriod(p)}>{({annual:'年度',h1:'上半年',q1:'一季度',q3:'前三季度'} as Record<string,string>)[p]}</button>)}</div>
    {datasets.map((dataset) => {
      const latest = dataset.rows.at(-1)!
      const labels = [...new Set(dataset.rows.flatMap((r) => r.items.map((p) => p.label)))]
      const color = (label: string) => COLORS[labels.indexOf(label)%COLORS.length]
      const max = Math.max(...dataset.rows.map((r) => r.total))/1e8 || 1
      const stackLabels=dataset.rows.flatMap((row,i) => {
        const x=72+438/dataset.rows.length*(i+.5)
        let top=230
        const labels=row.items.flatMap((item) => {
          const height=item.value/1e8/max*196
          top-=height
          // 极小分项不塞进窄色块，仍可在悬浮提示与下方表格核对。
          return height<32 ? [] : [{id:`${row.year}-${item.label}`,x,y:top+height/2,preferredY:top+height/2+5,
            text:(item.value/1e8).toFixed(2),description:`${row.periodLabel} ${item.label}：${(item.value/1e8).toFixed(2)}亿元`}]
        })
        return [...labels,{id:`${row.year}-total`,x,y:top,preferredY:top-10,text:(row.total/1e8).toFixed(2),
          description:`${row.periodLabel} 总收入：${(row.total/1e8).toFixed(2)}亿元`}]
      })
      const sourceLink = (sourceId: string | undefined,page: number | null | undefined) => {
        const s=sources.find((s) => s.sourceId===sourceId)
        return s && page ? <a href={`${s.url}#page=${page}`} target="_blank" rel="noreferrer" title={s.title}>{s.title} · PDF第{page}页 ↗ </a> : null
      }
      const refs = (rows: typeof dataset.rows) => [...new Set(rows.flatMap((r) => [r.totalEvidence,...r.items.filter((p) => !p.derived)].map((e) => `${e.sourceId}:${e.page}`)))].map((ref) => { const [id,page]=ref.split(':');return <span key={ref}>{sourceLink(id,Number(page))}</span> })
      let offset=0
      return <div key={dataset.id} className="business-dataset">
        <div className="financial-grid">
          <figure className="business-chart financial-chart"><figcaption>{latest.periodLabel} · {dataset.label}占比</figcaption>
            <svg viewBox="0 0 420 235" role="img" aria-label={`${dataset.label}占比，具体金额和比例见下表`}>
              <circle cx="210" cy="116" r="77" fill="none" stroke="#eee" strokeWidth="38" />
              {latest.items.map((item) => { const start=offset;offset+=item.share;return <circle key={item.label} cx="210" cy="116" r="77" fill="none" stroke={color(item.label)} strokeWidth="38" pathLength="100" strokeDasharray={`${item.share} ${100-item.share}`} strokeDashoffset={-start} transform="rotate(-90 210 116)"><title>{item.label}：{item.share.toFixed(2)}%</title></circle> })}
              <text x="210" y="112" textAnchor="middle" fontSize="22" fontWeight="600">{(latest.total/1e8).toFixed(2)}</text><text x="210" y="138" textAnchor="middle" fontSize="15" fill="#656b63">总收入 · 亿元</text>
            </svg>
            <div className="business-legend">{latest.items.map((p) => <span key={p.label}><i style={{background:color(p.label)}} />{p.label} <strong>{p.share.toFixed(2)}%</strong></span>)}</div>
            <p className="chart-source">来源：{refs([latest])}；占比使用实际总收入，不将已知分项重新归一到100%。</p>
          </figure>
          {dataset.rows.length>1 && <figure className="business-chart financial-chart"><figcaption>{dataset.label} · 金额与结构变化</figcaption>
            <div className="chart-plot-scroll"><svg viewBox="0 0 540 285" role="img" aria-label={`${dataset.label}历年堆叠柱图，单位亿元，显示总额与可读分项金额标签`}>
              {[0,1,2,3,4].map((n) => <g key={n}><line x1="72" x2="510" y1={230-n*49} y2={230-n*49} stroke="#e5e5df" /><text x="62" y={235-n*49} fontSize="14" textAnchor="end">{(max*n/4).toFixed(1)}</text></g>)}
              {dataset.rows.map((row,i) => { let base=230; const step=438/dataset.rows.length;return <g key={row.year}>{row.items.map((p) => { const height=p.value/1e8/max*196;base-=height;return <rect key={p.label} x={72+step*(i+.22)} y={base} width={step*.56} height={height} fill={color(p.label)}><title>{row.periodLabel} {p.label}：{(p.value/1e8).toFixed(2)}亿元（{p.share.toFixed(2)}%）</title></rect> })}<text x={72+step*(i+.5)} y="264" textAnchor="middle" fontSize="14"><title>{row.periodLabel}</title>{dataset.rows.length > 5 ? row.year : row.periodLabel}</text></g> })}
              {showDataLabels && <ChartDataLabels points={stackLabels} bounds={{left:74,right:510,top:0,bottom:245}} />}
            </svg></div>
            <div className="chart-legend">{labels.map((label) => <span key={label}><i style={{background:color(label)}} />{label}</span>)}<span>亿元</span></div>
            <p className="chart-source">来源：{refs(dataset.rows)}；同一维度、同期间展示，分类变化保留原披露名称。</p>
          </figure>}
        </div>
        <details className="financial-table-details" open><summary>核对{dataset.label}金额与占比</summary><div className="table-scroll"><table className="research-table business-table"><thead><tr><th>期间</th><th>分项</th><th>收入（亿元）</th><th>占合并收入</th><th>来源</th></tr></thead><tbody>{dataset.rows.flatMap((r) => r.items.map((p) => <tr key={`${r.year}-${p.label}`}><td>{r.periodLabel}</td><td>{p.label}</td><td title={`${p.rawValue || p.value}${p.unit || '元'}`}>{(p.value/1e8).toFixed(2)}</td><td>{p.share.toFixed(2)}%</td><td>{p.derived ? <>总额减已知项；{sourceLink(r.totalEvidence.sourceId,r.totalEvidence.page)}</> : sourceLink(p.sourceId,p.page)}</td></tr>))}</tbody></table></div></details>
      </div>
    })}
  </div>
}

export function EvidenceDiagram({ diagram, sources }: { diagram: SectionDiagram; sources: EvidenceSource[] }) {
  return <figure className={`evidence-diagram ${diagram.kind}`} aria-label={diagram.title}>
    <figcaption>{diagram.title}<span>定性分析 · 非数值预测</span></figcaption>
    <ol>{diagram.nodes.map((node,i) => <li key={i}><span className="diagram-index">{String(i+1).padStart(2,'0')}</span><div><strong>{node.label}</strong><p>{node.detail}</p><div className="chart-source">{node.citations.map((c,j) => { const s=sources.find((s) => s.sourceId===c.sourceId);return s ? <a key={j} href={`${s.url}${c.page ? `#page=${c.page}` : ''}`} target="_blank" rel="noreferrer">{s.title}{c.page ? ` · PDF第${c.page}页` : ''} ↗ </a> : null })}</div></div></li>)}</ol>
  </figure>
}
