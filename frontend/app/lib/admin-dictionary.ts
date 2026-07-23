export interface DictionaryEntry {
  id: number
  word: string
  reading: string
  category: string
  status: 'active' | 'inactive'
  notes: string
  source_misreading_report_id: number | null
  updated_at: string
}

export interface DictionaryStats {
  total: number
  active: number
  inactive: number
}

export interface PaginatedDictionaryResponse {
  items: DictionaryEntry[]
  total: number
  has_next: boolean
  stats: DictionaryStats
}

const SERVER_API_BASE = process.env.API_BASE ?? 'http://api:8010'

function toQueryString(params: Record<string, string | number | undefined>): string {
  const parts: string[] = []
  for (const [key, val] of Object.entries(params)) {
    if (val !== undefined && val !== '') {
      parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(val))}`)
    }
  }
  return parts.length ? `?${parts.join('&')}` : ''
}

/** サーバーサイド専用：バックエンドへ直接アクセス（認証ヘッダー付与） */
async function serverHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const { cookies } = await import('next/headers')
  const cookie = cookies().get('admin_session')?.value
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

/** クライアントサイド専用：同一オリジンの Route Handler 経由 */
async function clientFetch(path: string, options?: RequestInit): Promise<Response> {
  return fetch(`/api${path}`, options)
}

export async function fetchDictionaryEntries(
  params: {
    search?: string
    category?: string
    status?: string
    limit?: number
    offset?: number
  } = {},
  signal?: AbortSignal,
): Promise<PaginatedDictionaryResponse> {
  const qs = toQueryString({
    search: params.search,
    category: params.category,
    status: params.status,
    limit: params.limit ?? 20,
    offset: params.offset ?? 0,
  })
  const isServer = typeof window === 'undefined'
  const res = await (isServer
    ? serverFetch(`/admin/dictionary${qs}`, { cache: 'no-store' as RequestCache, signal })
    : clientFetch(`/admin/dictionary${qs}`, { cache: 'no-store' as RequestCache, signal }))
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `Failed to fetch dictionary: ${res.status}`)
  }
  return res.json() as Promise<PaginatedDictionaryResponse>
}

export async function createDictionaryEntry(data: {
  word: string
  reading: string
  category: string
  notes?: string
}): Promise<DictionaryEntry> {
  const res = await clientFetch('/admin/dictionary', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `Create failed: ${res.status}`)
  }
  return res.json() as Promise<DictionaryEntry>
}

export async function updateDictionaryEntry(
  id: number,
  data: {
    word: string
    reading: string
    category: string
    notes?: string
  },
): Promise<DictionaryEntry> {
  const res = await clientFetch(`/admin/dictionary/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `Update failed: ${res.status}`)
  }
  return res.json() as Promise<DictionaryEntry>
}

export async function updateDictionaryStatus(
  id: number,
  status: 'active' | 'inactive',
): Promise<DictionaryEntry> {
  const res = await clientFetch(`/admin/dictionary/${id}/status`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `Status update failed: ${res.status}`)
  }
  return res.json() as Promise<DictionaryEntry>
}
