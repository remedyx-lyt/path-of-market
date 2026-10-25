import { useRef } from 'react'
import type { PointerEvent, KeyboardEvent } from 'react'
import { clampChatWidth } from './panelLayout'

export function PanelResizeHandle({ width, onChange }: { width: number; onChange: (width: number) => void }) {
  const drag = useRef<{ x: number; width: number; current: number; host: HTMLElement } | null>(null)
  function start(event: PointerEvent<HTMLDivElement>) {
    const host = event.currentTarget.parentElement
    if (!host) return
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    drag.current = { x: event.clientX, width: host.lastElementChild?.getBoundingClientRect().width ?? width, current: width, host }
  }
  function move(event: PointerEvent<HTMLDivElement>) {
    const state = drag.current
    if (!state) return
    state.current = clampChatWidth(state.width + state.x - event.clientX, state.host.clientWidth)
    state.host.style.setProperty('--chat-width', `${state.current}px`)
  }
  function end() {
    if (!drag.current) return
    onChange(drag.current.current)
    drag.current.host.style.removeProperty('--chat-width')
    drag.current = null
  }
  function key(event: KeyboardEvent<HTMLDivElement>) {
    if (!['ArrowLeft', 'ArrowRight', 'Home'].includes(event.key)) return
    event.preventDefault()
    const available = event.currentTarget.parentElement?.clientWidth ?? 1000
    onChange(clampChatWidth(event.key === 'Home' ? 480 : width + (event.key === 'ArrowLeft' ? 32 : -32), available))
  }
  return <div className="panel-resizer" role="separator" tabIndex={0} aria-label="调整对话宽度" aria-orientation="vertical"
    aria-valuemin={320} aria-valuenow={width} aria-valuetext={`对话宽度 ${width} 像素；向左拖动可放大`}
    onPointerDown={start} onPointerMove={move} onPointerUp={end} onPointerCancel={end} onKeyDown={key}
    title="向左拖宽对话；也可用左右方向键调整"><span /></div>
}
