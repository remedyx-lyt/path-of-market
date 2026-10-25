import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'

// 原生 dialog 负责焦点限制、Esc 关闭与关闭后恢复焦点；弹窗不挤压报告/聊天。
export function WorkbenchDialog({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const trigger = document.activeElement
    const dialog = ref.current
    dialog?.showModal()
    return () => {
      dialog?.close()
      if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus()
    }
  }, [])
  return <dialog ref={ref} className="workbench-dialog" aria-label={title} onCancel={onClose} onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
    <header><h2>{title}</h2><button type="button" aria-label="关闭面板" onClick={onClose}>关闭 ×</button></header>
    <div className="workbench-dialog-body">{children}</div>
  </dialog>
}
