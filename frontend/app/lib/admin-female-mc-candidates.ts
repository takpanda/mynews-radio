export interface FemaleMcCandidateSample {
  url: string
  text: string
  media_type: string
  available: boolean
}

export interface FemaleMcCandidate {
  id: number
  voice_name: string
  display_name: string
  sample_text: string
  is_active: boolean
  sample: FemaleMcCandidateSample
}

export interface FemaleMcCandidateCreateInput {
  voice_name: string
  display_name: string
  sample_text?: string
}

export interface FemaleMcCandidateUpdateInput {
  display_name?: string
  sample_text?: string
  is_active?: boolean
}

const SERVER_API_BASE = process.env.API_BASE ?? 'http://api:8010'

/** サーバーサイド専用：バックエンドへ直接アクセス（認証ヘッダー付与） */
async function serverHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const { cookies } = await import('next/headers')
  const cookie = (await cookies()).get('admin_session')?.value
  if (cookie) headers['Cookie'] = `admin_session=${cookie}`
  return headers
}

/**
 * バックエンドが返す sample.url はバックエンド自身のパスであり、ブラウザから直接到達できない。
 * ブラウザからは中継API（/api/admin/...）経由でのみアクセスできるため、値は使わずボイス名から組み立て直す。
 */
function withRelaySampleUrl(candidate: FemaleMcCandidate): FemaleMcCandidate {
  return {
    ...candidate,
    sample: {
      ...candidate.sample,
      url: `/api/admin/settings/voices/categories/samples/${encodeURIComponent(candidate.voice_name)}`,
    },
  }
}

export async function fetchFemaleMcCandidates(): Promise<FemaleMcCandidate[]> {
  const res = await fetch(`${SERVER_API_BASE}/settings/voices/female-mc-candidates`, {
    headers: await serverHeaders(),
    cache: 'no-store' as RequestCache,
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `Failed to fetch female mc candidates: ${res.status}`)
  }
  const data = (await res.json()) as FemaleMcCandidate[]
  return data.map(withRelaySampleUrl)
}

/** クライアントサイド専用：中継APIを経由して女性MC候補マスタを再取得する */
export async function fetchFemaleMcCandidatesClient(): Promise<FemaleMcCandidate[]> {
  const res = await fetch('/api/admin/settings/voices/female-mc-candidates', { cache: 'no-store' })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(parseFemaleMcCandidateError(res.status, body))
  }
  const data = (await res.json()) as FemaleMcCandidate[]
  return data.map(withRelaySampleUrl)
}

/** クライアントサイド専用：中継APIを経由して女性MC候補を追加する */
export async function createFemaleMcCandidateClient(
  input: FemaleMcCandidateCreateInput,
): Promise<FemaleMcCandidate> {
  const res = await fetch('/api/admin/settings/voices/female-mc-candidates', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(parseFemaleMcCandidateError(res.status, body))
  }
  return withRelaySampleUrl((await res.json()) as FemaleMcCandidate)
}

/** クライアントサイド専用：中継APIを経由して女性MC候補を更新する（表示名・試聴文・有効状態） */
export async function updateFemaleMcCandidateClient(
  voiceName: string,
  input: FemaleMcCandidateUpdateInput,
): Promise<FemaleMcCandidate> {
  const res = await fetch(`/api/admin/settings/voices/female-mc-candidates/${encodeURIComponent(voiceName)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(parseFemaleMcCandidateError(res.status, body))
  }
  return withRelaySampleUrl((await res.json()) as FemaleMcCandidate)
}

function parseFemaleMcCandidateError(status: number, body: string): string {
  try {
    const parsed = JSON.parse(body)
    if (typeof parsed.detail === 'string' && parsed.detail) return parsed.detail
  } catch {
    /* not JSON, fall through */
  }
  switch (true) {
    case status === 401:
      return 'ログインが必要です。再度ログインしてください。'
    case status === 404:
      return '候補が見つかりませんでした。'
    case status === 409:
      return '同じボイス名の候補が既に存在します。'
    case status === 422:
      return '入力内容を確認してください。'
    case status === 503:
      return '保存できませんでした。しばらく後でもう一度お試しください。'
    default:
      return body || `処理に失敗しました（status: ${status}）`
  }
}
