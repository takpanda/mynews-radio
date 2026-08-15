export interface VoiceSettings {
  aivispeech_speaker_male: number
  aivispeech_speaker_female: number
  voicevox_speaker_male: number
  voicevox_speaker_female: number
  fishs2pro_voice_male: string
  fishs2pro_voice_female: string
}

export type VoiceEngineKey = 'aivispeech' | 'voicevox' | 'fishs2pro'
export type VoiceGender = 'male' | 'female'

export interface VoiceOption {
  display_name: string
  value: number | string
  speaker_name: string | null
  style_name: string | null
}

export interface EngineVoiceOptions {
  status: 'ok' | 'error'
  options: VoiceOption[]
  error: string | null
}

export interface VoiceOptionsResponse {
  aivispeech: EngineVoiceOptions
  voicevox: EngineVoiceOptions
  fishs2pro: EngineVoiceOptions
}

export const VOICE_ENGINES: { key: VoiceEngineKey; label: string }[] = [
  { key: 'aivispeech', label: 'AivisSpeech' },
  { key: 'voicevox', label: 'VOICEVOX' },
  { key: 'fishs2pro', label: 'Fish S2 Pro' },
]

export const VOICE_FIELD_MAP: Record<VoiceEngineKey, Record<VoiceGender, keyof VoiceSettings>> = {
  aivispeech: { male: 'aivispeech_speaker_male', female: 'aivispeech_speaker_female' },
  voicevox: { male: 'voicevox_speaker_male', female: 'voicevox_speaker_female' },
  fishs2pro: { male: 'fishs2pro_voice_male', female: 'fishs2pro_voice_female' },
}

const SERVER_API_BASE = process.env.API_BASE ?? 'http://api:8010'

/** サーバーサイド専用：バックエンドへ直接アクセス（認証ヘッダー付与） */
async function serverHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const { cookies } = await import('next/headers')
  const cookie = cookies().get('admin_session')?.value
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
