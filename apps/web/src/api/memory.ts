import { z } from 'zod'

const episodeSchema = z.object({ runId: z.string(), rootTaskId: z.string(), nodeId: z.string(), target: z.string(),
  question: z.string(), kind: z.enum(['research', 'followup']), timestamp: z.string() })
const noteSchema = z.object({ id: z.string(), text: z.string(), category: z.enum(['research_preference', 'risk_focus', 'watch_company']),
  status: z.enum(['confirmed', 'suggested']), quote: z.string().optional(), runId: z.string().optional(), updatedAt: z.string() })
const memorySchema = z.object({ schemaVersion: z.literal(1), revision: z.number().int().nonnegative(), enabled: z.boolean(),
  notes: z.array(noteSchema), ignoredTargets: z.array(z.string()), episodes: z.array(episodeSchema),
  companies: z.array(z.object({ target: z.string(), researchCount: z.number(), followupCount: z.number(), lastSeen: z.string(), latestTaskId: z.string() })),
  themes: z.array(z.object({ name: z.string(), count: z.number(), evidence: z.array(episodeSchema) })),
  companyCount: z.number(), totalEpisodes: z.number(), matchedEpisodes: z.number(), observationScope: z.string() })

export type UserMemory = z.infer<typeof memorySchema>
export type MemoryNote = z.infer<typeof noteSchema>
export type MemoryEdit = { action: 'save' | 'forget' | 'toggle' | 'ignore_company' | 'restore_company';
  id?: string; text?: string; category?: MemoryNote['category']; enabled?: boolean; target?: string }

async function memoryRequest(body?: Record<string, unknown>, signal?: AbortSignal): Promise<UserMemory> {
  const response = await fetch('/api/research/memory', { method: body ? 'POST' : 'GET', signal,
    ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}) })
  const value: unknown = await response.json()
  if (!response.ok) {
    const parsed = z.object({ error: z.object({ message: z.string() }) }).safeParse(value)
    throw new Error(parsed.success ? parsed.data.error.message : '读取或保存研究记忆失败，请刷新后重试。')
  }
  const parsed = memorySchema.safeParse(value)
  if (!parsed.success) throw new Error('研究记忆格式不完整，未覆盖当前输入。')
  return parsed.data
}
export const getUserMemory = (signal?: AbortSignal) => memoryRequest(undefined, signal)
export const editUserMemory = (revision: number, edit: MemoryEdit) => memoryRequest({ revision, ...edit })
