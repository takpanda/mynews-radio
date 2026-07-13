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

export async function fetchDictionaryEntries(
  params: {
    search?: string
    category?: string
    status?: string
    limit?: number
    offset?: number
  } = {},
): Promise<PaginatedDictionaryResponse> {
  const url = new URL('/admin/dictionary', window.location.origin)
  if (params.search) url.searchParams.set('search', params.search)
  if (params.category) url.searchParams.set('category', params.category)
  if (params.status) url.searchParams.set('status', params.status)
  url.searchParams.set('limit', String(params.limit ?? 20))
  url.searchParams.set('offset', String(params.offset ?? 0))
  const res = await fetch(url.pathname + url.search, { cache: 'no-store' })
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
  const res = await fetch('/admin/dictionary', {
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
  const res = await fetch(`/admin/dictionary/${id}`, {
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
  const res = await fetch(`/admin/dictionary/${id}/status`, {
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

function parseErrorDetail(body: string): string {
  try {
    const parsed = JSON.parse(body)
    if (typeof parsed.detail === 'string') return parsed.detail
  } catch {}
  return body
}
