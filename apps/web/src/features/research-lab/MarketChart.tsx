import { useState } from 'react'
import type { MarketData } from '../../api/research'

export function MarketChart({ data }: { data: MarketData }) {
  const [mode, setMode] = useState<'normalized' | 'raw'>('normalized')
  const [selected, setSelected] = useState(data.series.length - 1)
  const rows = data.series
  const base = rows[0].adjustedClose
  const values = rows.map((r) => mode === 'raw' ? r.close : r.adjustedClose / base * 100)
  const low = Math.min(...values), high = Math.max(...values), spread = high - low || 1
  const width = 600, height = 250, left = 60, top = 18, plotWidth = 520, plotHeight = 195
  const x = (i: number) => left + i / (rows.length - 1) * plotWidth
  const y = (value: number) => top + (high - value) / spread * plotHeight
  const path = values.map((value, i) => `${i ? 'L' : 'M'}${x(i).toFixed(2)},${y(value).toFixed(2)}`).join(' ')
  const row = rows[Math.min(selected, rows.length - 1)]
  const metrics = data.metrics
  return <section className="market-section" aria-labelledby="market-chart-title">
    <h3 id="market-chart-title">股票行情</h3>
    <p className="market-caption">{data.actualStart} — {data.actualEnd} · 日线 · {data.provider}</p>
    <div className="chart-switch" role="group" aria-label="图表口径">
      <button type="button" aria-pressed={mode === 'normalized'} onClick={() => setMode('normalized')}>复权走势（起点100）</button>
      <button type="button" aria-pressed={mode === 'raw'} onClick={() => setMode('raw')}>实际价格（元）</button>
    </div>
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={mode === 'raw' ? '不复权日线价格图，单位人民币元' : '后复权收盘归一化走势图，区间起点为100'}>
      {[0, 1, 2, 3, 4].map((i) => { const value = low + spread * i / 4; return <g key={i}>
        <line x1={left} x2={left + plotWidth} y1={y(value)} y2={y(value)} stroke="#484844" strokeWidth="1" />
        <text x={left - 8} y={y(value) + 4} textAnchor="end" fill="#aaa" fontSize="11">{value.toFixed(1)}</text>
      </g> })}
      <path d={path} fill="none" stroke="#e9e9df" strokeWidth="2" />
      <line x1={x(selected)} x2={x(selected)} y1={top} y2={top + plotHeight} stroke="#70d6bd" strokeDasharray="4 4" />
      <circle cx={x(selected)} cy={y(values[selected])} r="4" fill="#70d6bd" />
      <text x={left} y={height - 10} fill="#aaa" fontSize="11">{rows[0].date}</text>
      <text x={left + plotWidth} y={height - 10} textAnchor="end" fill="#aaa" fontSize="11">{rows[rows.length - 1].date}</text>
    </svg>
    <label className="chart-cursor">查看交易日：{row.date} · 实际价格 {row.close.toFixed(2)} 元 · 复权指数 {(row.adjustedClose / base * 100).toFixed(2)}
      <input aria-label="选择交易日" type="range" min={0} max={rows.length - 1} value={selected} onChange={(e) => setSelected(Number(e.target.value))} />
    </label>
    <div className="table-scroll"><table className="research-table"><caption>区间指标（程序计算）</caption><tbody>
      <tr><th scope="row">交易日数</th><td>{metrics.tradingDays}</td></tr>
      <tr><th scope="row">期初 / 期末实际价格</th><td>{metrics.firstRawClose.toFixed(2)} / {metrics.lastRawClose.toFixed(2)} 元</td></tr>
      <tr><th scope="row">后复权区间变化</th><td>{metrics.adjustedChangePct.toFixed(2)}%</td></tr>
      <tr><th scope="row">按收盘序列的最大回撤</th><td>{metrics.maxCloseDrawdownPct.toFixed(2)}%</td></tr>
      <tr><th scope="row">该次回撤的峰值 / 低点日期</th><td>{metrics.drawdownPeakDate} / {metrics.drawdownTroughDate}</td></tr>
      <tr><th scope="row">日收益年化波动率</th><td>{metrics.annualizedDailyVolatilityPct == null ? '数据不足' : `${metrics.annualizedDailyVolatilityPct.toFixed(2)}%`}</td></tr>
    </tbody></table></div>
    <p className="market-caption">实际价格为不复权字段；走势与收益指标采用同源后复权数据。复权数值不是实际成交价。<br />{metrics.formula}</p>
  </section>
}
