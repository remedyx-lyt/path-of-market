export type ChartLabelPoint = {
  id: string
  x: number
  y: number
  preferredY: number
  text: string
  description: string
}

type Bounds = { left: number; right: number; top: number; bottom: number }

/** 标签留在绘图区内，相邻数值接近时上下错开，并用引线保留对应关系。 */
export function positionChartLabels(points: ChartLabelPoint[], bounds: Bounds) {
  const placed: { left: number; right: number; top: number; bottom: number }[] = []
  return [...points].sort((a,b) => a.preferredY-b.preferredY || a.x-b.x).map((point) => {
    const width = point.text.length*10 + 8
    const x = Math.max(bounds.left+width/2,Math.min(bounds.right-width/2,point.x))
    const candidates = [0,...Array.from({length:12},(_,i) => [-(i+1)*24,(i+1)*24]).flat()]
    const preferred = Math.max(bounds.top+18,Math.min(bounds.bottom,point.preferredY))
    let y = preferred
    for (const offset of candidates) {
      const candidate = preferred+offset
      if (candidate-18 < bounds.top || candidate > bounds.bottom) continue
      const box = {left:x-width/2,right:x+width/2,top:candidate-18,bottom:candidate+3}
      if (placed.every((p) => box.right+4<=p.left || box.left>=p.right+4 || box.bottom+2<=p.top || box.top>=p.bottom+2)) {
        y=candidate
        break
      }
    }
    placed.push({left:x-width/2,right:x+width/2,top:y-18,bottom:y+3})
    return {...point,labelX:x,labelY:y}
  })
}

export function ChartDataLabels({ points, bounds }: { points: ChartLabelPoint[]; bounds: Bounds }) {
  return <g className="chart-data-labels" aria-label="数据标签">
    {positionChartLabels(points,bounds).map((point) => <g key={point.id}>
      {(Math.abs(point.labelY-point.preferredY)>2 || Math.abs(point.labelX-point.x)>2) && <line
        x1={point.x} y1={point.y} x2={point.labelX} y2={point.labelY-7} stroke="#92998e" strokeWidth="1" />}
      <text className="chart-data-label" x={point.labelX} y={point.labelY} textAnchor="middle" aria-label={point.description}>
        <title>{point.description}</title>{point.text}
      </text>
    </g>)}
  </g>
}
