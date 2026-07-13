export interface DictionaryEntry {
  id: number
  word: string
  reading: string
  category: string
  status: 'active' | 'inactive'
  notes: string
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
const CLIENT_API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? ''

function dictionaryPath(): string {
  return typeof window === 'undefined'
    ? `${SERVER_API_BASE}/admin/dictionary`
    : `${CLIENT_API_BASE}/admin/dictionary`
}

function toQueryString(params: Record<string, string | number | undefined>): string {
  const parts: string[] = []
  for (const [key, val] of Object.entries(params)) {
    if (val !== undefined && val !== '') {
      parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(val))}`)
    }
  }
  return parts.length ? `?${parts.join('&')}` : ''
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
  const base = dictionaryPath()
  const qs = toQueryString({
    search: params.search,
    category: params.category,
    status: params.status,
    limit: params.limit ?? 20,
    offset: params.offset ?? 0,
  })
  const res = await fetch(`${base}${qs}`, { cache: 'no-store', signal })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `Failed to fetch dictionary: ${res.status}`)
  }
  return res.json() as Promise<PaginatedDictionaryResponse>
}

function clientBase(): string {
  return process.env.NEXT_PUBLIC_API_BASE ?? ''
}

export async function createDictionaryEntry(data: {
  word: string
  reading: string
  category: string
  notes?: string
}): Promise<DictionaryEntry> {
  const base = clientBase()
  const res = await fetch(`${base}/admin/dictionary`, {
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
  const base = clientBase()
  const res = await fetch(`${base}/admin/dictionary/${id}`, {
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
  const base = clientBase()
  const res = await fetch(`${base}/admin/dictionary/${id}/status`, {
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
