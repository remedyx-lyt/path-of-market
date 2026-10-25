/** 展示偏好不进入研究参数；存储不可用时仍可使用。 */
export function readPanelNumber(key: string, fallback: number, min: number, max: number) {
  try {
    const value = typeof window === 'undefined' ? null : window.localStorage.getItem(key)
    return value !== null && Number.isFinite(Number(value)) ? Math.max(min, Math.min(max, Number(value))) : fallback
  } catch { return fallback }
}

export function savePanelNumber(key: string, value: number) {
  try { window.localStorage.setItem(key, String(value)) } catch { /* 非必需的展示偏好 */ }
}

export function clampChatWidth(value: number, available: number) {
  return Math.round(Math.max(320, Math.min(Math.max(320, available - 308), value)))
}
