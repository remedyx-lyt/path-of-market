import type { ResearchActivity } from '../../api/research'

export function parentRun(job: ResearchActivity) {
  // 兼容修复前的Java快照：run_resumed本来就保存了父任务，无需迁移旧JSONL。
  return job.parentTaskId ?? job.events.find(e => e.type === 'run_resumed')?.parentTaskId
}

/** 只追溯明确的parentTaskId；不按公司名拼接，也不把兄弟接续重复累计。 */
export async function loadAncestors(current: ResearchActivity, read: (id: string, signal?: AbortSignal) => Promise<ResearchActivity>, signal?: AbortSignal) {
  const runs: ResearchActivity[] = [], seen = new Set([current.taskId])
  let next = parentRun(current), warning = ''
  while (next) {
    if (signal?.aborted) break
    if (!/^[0-9a-f-]{36}$/i.test(next) || seen.has(next) || seen.size >= 100) { warning = '接续关系无效、存在循环或超过100次，未继续追溯；以下累计仅含已读取记录。'; break }
    seen.add(next)
    try {
      const run = await read(next, signal)
      if (run.taskId !== next) throw new Error('任务标识不一致')
      runs.push(run); next = parentRun(run)
    } catch {
      warning = '部分历史记录暂时无法读取，未把它算作0次；以下累计仅含已读取记录。'
      break
    }
  }
  return { runs: runs.reverse(), warning }
}

export function activityTotals(runs: ResearchActivity[]) {
  const seen = new Set<string>(), usage: Record<string, number> = {}
  let calls = 0, elapsed = 0
  for (const run of runs) {
    if (seen.has(run.taskId)) continue
    seen.add(run.taskId); calls += run.modelCalls
    for (const [key, value] of Object.entries(run.usage)) usage[key] = (usage[key] ?? 0) + value
    const duration = Date.parse(run.events.at(-1)?.timestamp ?? '') - Date.parse(run.events[0]?.timestamp ?? '')
    if (Number.isFinite(duration) && duration > 0) elapsed += duration
  }
  return { calls, usage, elapsed, count: seen.size }
}
