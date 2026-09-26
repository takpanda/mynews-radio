export interface AdminEpisodeSummary {
  id: number
  episode_date: string
  seq: number
  status: string
  phase: string | null
  generation_message: string | null
  review_mode: string | null
  updated_at: string
}

/** バックエンドの一覧APIは1回のリクエストで最大この件数までしか返さない */
export const AWAITING_REVIEW_LIST_LIMIT = 200

/** 一覧が上限件数に達している＝実際の総件数がこれより多い可能性がある、を示す */
export function isAwaitingReviewListTruncated(episodes: AdminEpisodeSummary[]): boolean {
  return episodes.length >= AWAITING_REVIEW_LIST_LIMIT
}

const SERVER_API_BASE = process.env.API_BASE ?? 'http://api:8010'

async function serverHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const { cookies } = await import('next/headers')
  const cookie = (await cookies()).get('admin_session')?.value
  if (cookie) headers['Cookie'] = `admin_session=${cookie}`
  return headers
}

/** サーバーサイド専用：バックエンドへ直接アクセス（認証ヘッダー付与） */
export async function fetchAwaitingReviewEpisodes(): Promise<AdminEpisodeSummary[]> {
  const res = await fetch(`${SERVER_API_BASE}/admin/episodes?status=awaiting_review`, {
    headers: await serverHeaders(),
    cache: 'no-store' as RequestCache,
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `Failed to fetch awaiting review episodes: ${res.status}`)
  }
  return res.json() as Promise<AdminEpisodeSummary[]>
}

/** クライアントサイド専用：中継APIを経由して確認待ち一覧を取得する（AdminNavのバッジ表示にも使う） */
export async function fetchAwaitingReviewEpisodesClient(): Promise<AdminEpisodeSummary[]> {
  const res = await fetch('/api/admin/episodes?status=awaiting_review', {
    headers: { 'Content-Type': 'application/json' },
    cache: 'no-store' as RequestCache,
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `Failed to fetch awaiting review episodes: ${res.status}`)
  }
  return res.json() as Promise<AdminEpisodeSummary[]>
}
