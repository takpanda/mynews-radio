const SERVER_API_BASE = process.env.API_BASE ?? 'http://api:8010'

/** 台本の1行。article_id/start_time/segment/spoken_textなど、この画面が編集しないフィールドも
 * そのまま保持して往復させる必要があるため、既知フィールド以外はindex signatureで温存する。 */
export interface AdminScriptReviewLine {
  speaker: string
  text: string
  section: string
  [key: string]: unknown
}

/** title/style/segments/program_profile_idなど、この画面が編集しないフィールドも温存する。 */
export interface AdminScriptReviewScript {
  lines: AdminScriptReviewLine[]
  [key: string]: unknown
}

/** 番組の出演者定義（生成時点のprogram_snapshot由来）。過去回にはsnapshotが無くcastはnull。 */
export interface AdminScriptReviewCastMember {
  key: string
  name: string
  role?: string
}

export interface AdminScriptReviewResponse {
  episode_id: number
  revision: number
  script: AdminScriptReviewScript
  cast?: AdminScriptReviewCastMember[] | null
}

export interface ValidationFinding {
  code: string
  message: string
  line_indices: number[]
  severity: 'error' | 'warning'
}

export interface ValidationResult {
  can_approve: boolean
  results: ValidationFinding[]
  revision?: number
}

export class ScriptApiError extends Error {
  status: number
  detail?: unknown

  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.name = 'ScriptApiError'
    this.status = status
    this.detail = detail
  }
}

export class ScriptRevisionConflictError extends ScriptApiError {
  latestRevision: number

  constructor(latestRevision: number, detail?: unknown) {
    super(409, 'Script revision conflict', detail)
    this.name = 'ScriptRevisionConflictError'
    this.latestRevision = latestRevision
  }
}

export class ScriptValidationBlockedError extends ScriptApiError {
  results: ValidationFinding[]

  constructor(results: ValidationFinding[], detail?: unknown) {
    super(409, 'Script has validation errors', detail)
    this.name = 'ScriptValidationBlockedError'
    this.results = results
  }
}

async function readJsonSafe(res: Response): Promise<unknown> {
  try {
    return await res.json()
  } catch {
    return null
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

async function serverHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const { cookies } = await import('next/headers')
  const cookie = (await cookies()).get('admin_session')?.value
  if (cookie) headers['Cookie'] = `admin_session=${cookie}`
  return headers
}

/** サーバーサイド専用：バックエンドへ直接アクセス（認証ヘッダー付与） */
export async function fetchScript(episodeId: number): Promise<AdminScriptReviewResponse | null> {
  const res = await fetch(`${SERVER_API_BASE}/admin/episodes/${episodeId}/script`, {
    headers: await serverHeaders(),
    cache: 'no-store' as RequestCache,
  })
  if (res.status === 404) return null
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `Failed to fetch script: ${res.status}`)
  }
  return res.json() as Promise<AdminScriptReviewResponse>
}

/** クライアントサイド専用：中継APIを経由して最新の台本を取得する（409後の再取得にも使う） */
export async function fetchScriptClient(episodeId: number): Promise<AdminScriptReviewResponse> {
  const res = await fetch(`/api/admin/episodes/${episodeId}/script`, {
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store' as RequestCache,
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `Failed to fetch script: ${res.status}`)
  }
  return res.json() as Promise<AdminScriptReviewResponse>
}

export async function saveScriptClient(
  episodeId: number,
  revision: number,
  script: AdminScriptReviewScript,
): Promise<AdminScriptReviewResponse> {
  const res = await fetch(`/api/admin/episodes/${episodeId}/script`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ revision, script }),
    cache: 'no-store' as RequestCache,
  })
  if (res.status === 409) {
    const body = await readJsonSafe(res)
    const detail = isRecord(body) ? body.detail : undefined
    if (isRecord(detail) && typeof detail.latest_revision === 'number') {
      throw new ScriptRevisionConflictError(detail.latest_revision, detail)
    }
    throw new ScriptApiError(409, typeof detail === 'string' ? detail : '保存できませんでした。台本は確認待ちの状態ではない可能性があります。', detail)
  }
  if (!res.ok) {
    throw new ScriptApiError(res.status, `保存に失敗しました（status ${res.status}）`)
  }
  return res.json() as Promise<AdminScriptReviewResponse>
}

export async function validateScriptClient(episodeId: number): Promise<ValidationResult> {
  const res = await fetch(`/api/admin/episodes/${episodeId}/validate`, {
    method: 'POST',
    cache: 'no-store' as RequestCache,
  })
  if (res.status === 409) {
    const body = await readJsonSafe(res)
    const detail = isRecord(body) ? body.detail : undefined
    throw new ScriptApiError(409, typeof detail === 'string' ? detail : '検査できませんでした。台本は確認待ちの状態ではない可能性があります。', detail)
  }
  if (!res.ok) {
    throw new ScriptApiError(res.status, `検査に失敗しました（status ${res.status}）`)
  }
  return res.json() as Promise<ValidationResult>
}

export async function approveScriptClient(episodeId: number): Promise<{ episode_id: number; status: string; job_id: number }> {
  const res = await fetch(`/api/admin/episodes/${episodeId}/approve`, {
    method: 'POST',
    cache: 'no-store' as RequestCache,
  })
  if (res.status === 409) {
    const body = await readJsonSafe(res)
    const detail = isRecord(body) ? body.detail : undefined
    if (isRecord(detail) && Array.isArray(detail.results)) {
      throw new ScriptValidationBlockedError(detail.results as ValidationFinding[], detail)
    }
    throw new ScriptApiError(409, typeof detail === 'string' ? detail : '承認できませんでした。台本は確認待ちの状態ではない可能性があります。', detail)
  }
  if (!res.ok) {
    throw new ScriptApiError(res.status, `承認に失敗しました（status ${res.status}）`)
  }
  return res.json()
}

export async function rejectScriptClient(episodeId: number, action: 'discard'): Promise<{ episode_id: number; status: string }> {
  const res = await fetch(`/api/admin/episodes/${episodeId}/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action }),
    cache: 'no-store' as RequestCache,
  })
  if (res.status === 409) {
    const body = await readJsonSafe(res)
    const detail = isRecord(body) ? body.detail : undefined
    throw new ScriptApiError(409, typeof detail === 'string' ? detail : '破棄できませんでした。台本は確認待ちの状態ではない可能性があります。', detail)
  }
  if (!res.ok) {
    throw new ScriptApiError(res.status, `破棄に失敗しました（status ${res.status}）`)
  }
  return res.json()
}

/** 1行だけのTTS試し聴き。保存済み最新版の内容が対象（未保存の編集内容は反映されない）。 */
export async function previewAudioClient(episodeId: number, lineIndex: number): Promise<Blob> {
  const res = await fetch(`/api/admin/episodes/${episodeId}/lines/${lineIndex}/preview-audio`, {
    method: 'POST',
    cache: 'no-store' as RequestCache,
  })
  if (!res.ok) {
    let message = `試し聴きに失敗しました（status ${res.status}）`
    if (res.status === 429) message = '試し聴きの利用回数が上限に達しました。しばらく待ってからもう一度お試しください。'
    else if (res.status === 502) message = '音声の生成に失敗しました。もう一度お試しください。'
    else if (res.status === 404 || res.status === 422) message = 'この行は試し聴きできません。'
    throw new ScriptApiError(res.status, message)
  }
  return res.blob()
}

/** 台本内に登場するspeaker keyを、初出順に重複なく返す */
export function collectSpeakerKeys(lines: AdminScriptReviewLine[]): string[] {
  const seen: string[] = []
  for (const line of lines) {
    if (!seen.includes(line.speaker)) seen.push(line.speaker)
  }
  return seen
}

export interface SpeakerOption {
  key: string
  label: string
}

/**
 * 話者選択の選択肢を作る。castがあればその全員を（台本に未登場でも）候補にし、
 * castに無いspeaker keyを持つ行があっても、現在値が誤って別の出演者に見えないよう
 * 元のkeyをそのまま表示名にした選択肢を追加する。
 * castが無い/空の過去回では、台本に登場するspeaker keyから作る既存動作にする。
 */
export function buildSpeakerOptions(
  cast: AdminScriptReviewCastMember[] | null | undefined,
  lines: AdminScriptReviewLine[],
): SpeakerOption[] {
  if (cast && cast.length > 0) {
    const options: SpeakerOption[] = cast.map((member) => ({ key: member.key, label: member.name }))
    const known = new Set(options.map((option) => option.key))
    for (const line of lines) {
      if (!known.has(line.speaker)) {
        known.add(line.speaker)
        options.push({ key: line.speaker, label: line.speaker })
      }
    }
    return options
  }
  return collectSpeakerKeys(lines).map((key) => ({ key, label: key }))
}

/** 話者選択UIの表示要否。castがあればcastの人数、無ければ台本に登場するspeaker keyの種類数で決める。 */
export function shouldShowSpeakerSelect(
  cast: AdminScriptReviewCastMember[] | null | undefined,
  lines: AdminScriptReviewLine[],
): boolean {
  if (cast && cast.length > 0) return cast.length > 1
  return collectSpeakerKeys(lines).length > 1
}

/** 行追加時の初期話者。castがあればその先頭のkey、無ければ既存動作（登場済みの先頭 or 'male'）。 */
export function initialSpeakerKey(
  cast: AdminScriptReviewCastMember[] | null | undefined,
  lines: AdminScriptReviewLine[],
): string {
  if (cast && cast.length > 0) return cast[0].key
  return collectSpeakerKeys(lines)[0] ?? 'male'
}

export type ScriptDiffOp =
  | { kind: 'same'; line: AdminScriptReviewLine }
  | { kind: 'local-only'; line: AdminScriptReviewLine }
  | { kind: 'server-only'; line: AdminScriptReviewLine }

function diffLineKey(line: AdminScriptReviewLine): string {
  return `${line.speaker}\u0000${line.section}\u0000${line.text}`
}

/** 端末の編集内容とサーバー最新版の行を、LCSベースで比較する（同一行/端末のみ/サーバーのみ） */
export function diffScriptLines(local: AdminScriptReviewLine[], server: AdminScriptReviewLine[]): ScriptDiffOp[] {
  const n = local.length
  const m = server.length
  const localKeys = local.map(diffLineKey)
  const serverKeys = server.map(diffLineKey)

  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = localKeys[i] === serverKeys[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }

  const ops: ScriptDiffOp[] = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (localKeys[i] === serverKeys[j]) {
      ops.push({ kind: 'same', line: local[i] })
      i++
      j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      ops.push({ kind: 'local-only', line: local[i] })
      i++
    } else {
      ops.push({ kind: 'server-only', line: server[j] })
      j++
    }
  }
  while (i < n) {
    ops.push({ kind: 'local-only', line: local[i] })
    i++
  }
  while (j < m) {
    ops.push({ kind: 'server-only', line: server[j] })
    j++
  }
  return ops
}

const DRAFT_STORAGE_PREFIX = 'admin-script-review-draft:'

export interface ScriptDraft {
  episodeId: number
  baseRevision: number
  script: AdminScriptReviewScript
  savedAt: string
}

function draftStorageKey(episodeId: number): string {
  return `${DRAFT_STORAGE_PREFIX}${episodeId}`
}

/** 端末下書きの保存。localStorageが使えない環境（プライベートブラウズ等）では静かに諦める。 */
export function saveDraftToStorage(episodeId: number, baseRevision: number, script: AdminScriptReviewScript): void {
  if (typeof window === 'undefined') return
  try {
    const draft: ScriptDraft = { episodeId, baseRevision, script, savedAt: new Date().toISOString() }
    window.localStorage.setItem(draftStorageKey(episodeId), JSON.stringify(draft))
  } catch {
    // 保存できない場合は下書き機能を諦めるだけで、画面自体は継続して使える
  }
}

export function loadDraftFromStorage(episodeId: number): ScriptDraft | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(draftStorageKey(episodeId))
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<ScriptDraft> | null
    if (!parsed || typeof parsed.baseRevision !== 'number' || !isRecord(parsed.script) || !Array.isArray((parsed.script as AdminScriptReviewScript).lines)) {
      return null
    }
    return parsed as ScriptDraft
  } catch {
    return null
  }
}

export function clearDraftFromStorage(episodeId: number): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.removeItem(draftStorageKey(episodeId))
  } catch {
    // 削除できなくても画面動作に支障はない
  }
}
