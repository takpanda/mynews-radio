import type { VoiceOptionsResponse, VoiceSettings } from './tts-engines'

// 既存の import 互換のため、純粋な型・定数を再エクスポートする。
// クライアントコンポーネントは './tts-engines' から直接 import すること。
export * from './tts-engines'

const SERVER_API_BASE = process.env.API_BASE ?? 'http://api:8010'

/** サーバーサイド専用：バックエンドへ直接アクセス（認証ヘッダー付与） */
async function serverHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const { cookies } = await import('next/headers')
  const cookie = (await cookies()).get('admin_session')?.value
  if (cookie) headers['Cookie'] = `admin_session=${cookie}`
  return headers
}

export async function fetchVoiceSettings(): Promise<VoiceSettings> {
  const res = await fetch(`${SERVER_API_BASE}/settings/voices`, {
    headers: await serverHeaders(),
    cache: 'no-store' as RequestCache,
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `Failed to fetch voice settings: ${res.status}`)
  }
  return res.json() as Promise<VoiceSettings>
}

export async function fetchVoiceOptions(): Promise<VoiceOptionsResponse> {
  const res = await fetch(`${SERVER_API_BASE}/settings/voices/options`, {
    headers: await serverHeaders(),
    cache: 'no-store' as RequestCache,
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `Failed to fetch voice options: ${res.status}`)
  }
  return res.json() as Promise<VoiceOptionsResponse>
}

/** クライアントサイド専用：中継APIを経由してボイス選択肢を再取得する（一覧取得失敗時の再試行用） */
export async function fetchVoiceOptionsClient(): Promise<VoiceOptionsResponse> {
  const res = await fetch('/api/admin/settings/voices/options', { cache: 'no-store' })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(parseVoiceError(res.status, body))
  }
  return res.json() as Promise<VoiceOptionsResponse>
}

/** クライアントサイド専用：中継APIを経由してボイス設定を保存する */
export async function saveVoiceSettingsClient(settings: VoiceSettings): Promise<VoiceSettings> {
  const res = await fetch('/api/admin/settings/voices', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(settings),
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(parseVoiceError(res.status, body))
  }
  return res.json() as Promise<VoiceSettings>
}

function parseVoiceError(status: number, body: string): string {
  try {
    const parsed = JSON.parse(body)
    if (typeof parsed.detail === 'string' && parsed.detail) return parsed.detail
  } catch {
    /* not JSON, fall through */
  }
  switch (true) {
    case status === 401:
      return 'ログインが必要です。再度ログインしてください。'
    case status === 422:
      return '入力内容を確認してください。'
    case status === 503:
      return '保存できませんでした。しばらく後でもう一度お試しください。'
    default:
      return body || `処理に失敗しました（status: ${status}）`
  }
}
