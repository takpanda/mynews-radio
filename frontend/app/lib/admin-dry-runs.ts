import { extractErrorMessage } from './admin-programs'
import type { AdminScriptReviewScript, ValidationFinding } from './admin-script-review'

export type DryRunStatus = 'queued' | 'running' | 'completed' | 'failed'
export type DryRunVariant = 'current' | 'draft'

export interface DryRunCreateInput {
  draft_program_definition?: Record<string, unknown> | null
  draft_prompt_version_id?: number | null
  input_episode_id?: number | null
}

export interface DryRunCreateResult {
  id: number
  status: 'queued' | 'running'
}

export interface DryRunDetail {
  id: number
  program_id: string
  program_definition: Record<string, unknown>
  draft_program_definition: Record<string, unknown> | null
  prompt_version_id: number | null
  input_episode_id: number | null
  script_json: Partial<Record<DryRunVariant, AdminScriptReviewScript>> | null
  validation_json: Partial<Record<DryRunVariant, ValidationFinding[]>> | null
  status: DryRunStatus
  error: string | null
  created_at: string
  updated_at: string
}

export class DryRunApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'DryRunApiError'
    this.status = status
  }
}

/** 生成キューが上限（MAX_QUEUED_JOBS）に達した際の429応答。Retry-Afterヘッダーの秒数を保持する。 */
export class DryRunQueueFullError extends DryRunApiError {
  retryAfterSeconds: number | null

  constructor(retryAfterSeconds: number | null) {
    super(429, '生成キューが上限に達しています。しばらく待ってから再実行してください。')
    this.name = 'DryRunQueueFullError'
    this.retryAfterSeconds = retryAfterSeconds
  }
}

/**
 * idempotencyKeyは呼び出し側が管理する。応答が届かず結果不明のまま再試行する場合は
 * 同じキーを渡してバックエンドの重複排除（owner・operation・key）に乗せ、
 * 同一入力のジョブが二重登録されるのを防ぐ。省略時のみ新規キーを発行する。
 */
export async function createDryRunClient(
  programId: string,
  input: DryRunCreateInput,
  idempotencyKey?: string,
): Promise<DryRunCreateResult> {
  const res = await fetch(`/api/admin/programs/${encodeURIComponent(programId)}/dry-run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey ?? crypto.randomUUID() },
    body: JSON.stringify(input),
    cache: 'no-store' as RequestCache,
  })
  if (res.status === 429) {
    const retryAfterHeader = res.headers.get('Retry-After')
    throw new DryRunQueueFullError(retryAfterHeader ? Number(retryAfterHeader) : null)
  }
  if (!res.ok) throw new DryRunApiError(res.status, await extractErrorMessage(res))
  return res.json() as Promise<DryRunCreateResult>
}

export async function fetchDryRunClient(id: number): Promise<DryRunDetail> {
  const res = await fetch(`/api/admin/dry-runs/${id}`, { cache: 'no-store' as RequestCache })
  if (!res.ok) throw new DryRunApiError(res.status, await extractErrorMessage(res))
  return res.json() as Promise<DryRunDetail>
}
