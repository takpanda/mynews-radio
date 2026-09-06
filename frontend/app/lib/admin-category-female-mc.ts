export interface FemaleMcSample {
  url: string
  text: string
  media_type: string
  available: boolean
}

export interface FemaleMcOption {
  display_name: string
  value: string
  sample: FemaleMcSample
}

export type CategoryFemaleVoices = Record<string, string | null>

export interface CategoryFemaleMcSettings {
  categories: string[]
  category_female_voices: CategoryFemaleVoices
  default_voice: string
  voices: FemaleMcOption[]
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
function withRelaySampleUrls(data: CategoryFemaleMcSettings): CategoryFemaleMcSettings {
  return {
    ...data,
    voices: data.voices.map((voice) => ({
      ...voice,
      sample: {
        ...voice.sample,
        url: `/api/admin/settings/voices/categories/samples/${encodeURIComponent(voice.value)}`,
      },
    })),
  }
}

export async function fetchCategoryFemaleMc(): Promise<CategoryFemaleMcSettings> {
  const res = await fetch(`${SERVER_API_BASE}/settings/voices/categories`, {
    headers: await serverHeaders(),
    cache: 'no-store' as RequestCache,
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `Failed to fetch category female mc settings: ${res.status}`)
  }
  return withRelaySampleUrls((await res.json()) as CategoryFemaleMcSettings)
}

/** クライアントサイド専用：中継APIを経由してカテゴリ別女性MC設定を再取得する */
export async function fetchCategoryFemaleMcClient(): Promise<CategoryFemaleMcSettings> {
  const res = await fetch('/api/admin/settings/voices/categories', { cache: 'no-store' })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(parseCategoryFemaleMcError(res.status, body))
  }
  return withRelaySampleUrls((await res.json()) as CategoryFemaleMcSettings)
}

/** クライアントサイド専用：中継APIを経由してカテゴリ別女性MC設定を保存する */
export async function saveCategoryFemaleMcClient(
  categoryFemaleVoices: CategoryFemaleVoices,
): Promise<CategoryFemaleMcSettings> {
  const res = await fetch('/api/admin/settings/voices/categories', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ category_female_voices: categoryFemaleVoices }),
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(parseCategoryFemaleMcError(res.status, body))
  }
  return withRelaySampleUrls((await res.json()) as CategoryFemaleMcSettings)
}

function parseCategoryFemaleMcError(status: number, body: string): string {
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
