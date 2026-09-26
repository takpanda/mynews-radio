export type ProgramKind = 'radio' | 'commentary'
export type ReviewMode = 'always' | 'on_failure' | 'auto'

export const SEGMENT_KINDS_BY_PROGRAM_KIND: Record<ProgramKind, string[]> = {
  radio: ['intro', 'transition', 'headline', 'news', 'discussion', 'corner', 'outro'],
  commentary: ['intro', 'headline', 'news', 'corner', 'outro'],
}

export const SEGMENT_KIND_LABELS: Record<string, string> = {
  intro: 'オープニング',
  transition: 'つなぎ',
  headline: 'ヘッドライン',
  news: 'ニュース',
  discussion: '討論',
  corner: 'コーナー',
  outro: 'エンディング',
}

export const MAX_SEGMENTS = 6

export interface ProgramCastValue {
  key: string
  name: string
  role: string
  mc_id: string | null
  voice_fishs2pro: string | null
  voice_aivispeech: number | null
  voice_voicevox: number | null
}

export interface ProgramSegmentValue {
  id: string
  kind: string
  order: number
  min_lines: number
  max_lines: number
  speaker_keys: string[]
  label: string
}

export interface ProgramOptionsValue {
  style: string | null
  mc_gender: string | null
  narrative_arc: boolean
  review_mode: ReviewMode
}

export interface ProgramDefinitionValue {
  id: string
  name: string
  kind: ProgramKind
  cast: ProgramCastValue[]
  segments: ProgramSegmentValue[]
  options: ProgramOptionsValue
}

export interface Program {
  id: string
  name: string
  kind: ProgramKind
  definition: ProgramDefinitionValue
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface ProgramSaveInput extends ProgramDefinitionValue {
  is_active: boolean
}

export interface Mc {
  id: string
  name: string
  role: string
  voice_fishs2pro: string | null
  voice_aivispeech: number | null
  voice_voicevox: number | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface McSaveInput {
  id: string
  name: string
  role: string
  voice_fishs2pro: string | null
  voice_aivispeech: number | null
  voice_voicevox: number | null
  is_active: boolean
}

const SERVER_API_BASE = process.env.API_BASE ?? 'http://api:8010'

function toQueryString(params: Record<string, string | undefined>): string {
  const parts: string[] = []
  for (const [key, val] of Object.entries(params)) {
    if (val !== undefined && val !== '') {
      parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(val)}`)
    }
  }
  return parts.length ? `?${parts.join('&')}` : ''
}

async function serverHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const { cookies } = await import('next/headers')
  const cookie = (await cookies()).get('admin_session')?.value
  if (cookie) headers['Cookie'] = `admin_session=${cookie}`
  return headers
}

async function serverFetch(path: string, options?: RequestInit): Promise<Response> {
  const headers = await serverHeaders()
  return fetch(`${SERVER_API_BASE}${path}`, {
    ...options,
    headers: { ...headers, ...(options?.headers as Record<string, string>) },
  })
}

async function clientFetch(path: string, options?: RequestInit): Promise<Response> {
  return fetch(`/api${path}`, options)
}

export async function extractErrorMessage(res: Response): Promise<string> {
  const body = await res.text().catch(() => '')
  try {
    const parsed = JSON.parse(body)
    if (typeof parsed.detail === 'string') return parsed.detail
    if (Array.isArray(parsed.detail)) {
      const messages = parsed.detail
        .map((item: { msg?: string }) => item?.msg)
        .filter((msg: unknown): msg is string => typeof msg === 'string')
      if (messages.length > 0) return messages.join('; ')
    }
  } catch {
    /* not JSON, fall through */
  }
  switch (true) {
    case res.status === 401:
      return '認証されていません。再度ログインしてください。'
    case res.status === 404:
      return '対象が見つかりませんでした。'
    case res.status === 409:
      return body || 'IDが既に使用されています。'
    case res.status >= 500:
      return 'サーバーエラーが発生しました。時間をおいて再度お試しください。'
    default:
      return body || `リクエストに失敗しました（status: ${res.status}）`
  }
}

/* ---- 番組 ---- */

export async function fetchPrograms(
  includeInactive = false,
  signal?: AbortSignal,
): Promise<Program[]> {
  const qs = toQueryString({ include_inactive: includeInactive ? 'true' : undefined })
  const isServer = typeof window === 'undefined'
  const res = await (isServer
    ? serverFetch(`/admin/programs${qs}`, { cache: 'no-store', signal })
    : clientFetch(`/admin/programs${qs}`, { cache: 'no-store', signal }))
  if (!res.ok) throw new Error(await extractErrorMessage(res))
  return res.json() as Promise<Program[]>
}

export async function fetchProgram(id: string): Promise<Program> {
  const isServer = typeof window === 'undefined'
  const res = await (isServer
    ? serverFetch(`/admin/programs/${encodeURIComponent(id)}`, { cache: 'no-store' })
    : clientFetch(`/admin/programs/${encodeURIComponent(id)}`, { cache: 'no-store' }))
  if (!res.ok) throw new Error(await extractErrorMessage(res))
  return res.json() as Promise<Program>
}

export async function createProgram(input: ProgramSaveInput): Promise<Program> {
  const res = await clientFetch('/admin/programs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) throw new Error(await extractErrorMessage(res))
  return res.json() as Promise<Program>
}

export async function replaceProgram(id: string, input: ProgramSaveInput): Promise<Program> {
  const res = await clientFetch(`/admin/programs/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) throw new Error(await extractErrorMessage(res))
  return res.json() as Promise<Program>
}

/* ---- MC ---- */

export async function fetchMcs(includeInactive = false, signal?: AbortSignal): Promise<Mc[]> {
  const qs = toQueryString({ include_inactive: includeInactive ? 'true' : undefined })
  const isServer = typeof window === 'undefined'
  const res = await (isServer
    ? serverFetch(`/admin/mcs${qs}`, { cache: 'no-store', signal })
    : clientFetch(`/admin/mcs${qs}`, { cache: 'no-store', signal }))
  if (!res.ok) throw new Error(await extractErrorMessage(res))
  return res.json() as Promise<Mc[]>
}

export async function createMc(input: McSaveInput): Promise<Mc> {
  const res = await clientFetch('/admin/mcs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) throw new Error(await extractErrorMessage(res))
  return res.json() as Promise<Mc>
}

export async function replaceMc(id: string, input: McSaveInput): Promise<Mc> {
  const res = await clientFetch(`/admin/mcs/${encodeURIComponent(id)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) throw new Error(await extractErrorMessage(res))
  return res.json() as Promise<Mc>
}
