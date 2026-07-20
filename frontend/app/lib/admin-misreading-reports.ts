export interface AdminMisreadingReport {
  id: number
  target_text: string
  correct_reading: string
  article_id: number | null
  notes: string
  created_at: string
}

const SERVER_API_BASE = process.env.API_BASE ?? 'http://api:8010'
const API_KEY = process.env.API_KEY

function serverHeaders(): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (API_KEY) {
    headers['Authorization'] = `Bearer ${API_KEY}`
  }
  return headers
}

export async function fetchAdminMisreadingReports(): Promise<AdminMisreadingReport[]> {
  const isServer = typeof window === 'undefined'
  const url = isServer
    ? `${SERVER_API_BASE}/admin/reports/misreading`
    : '/api/admin/reports/misreading'
  const options: RequestInit = isServer
    ? { headers: serverHeaders(), cache: 'no-store' as RequestCache }
    : { cache: 'no-store' as RequestCache }
  const res = await fetch(url, options)
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `Failed to fetch misreading reports: ${res.status}`)
  }
  return res.json() as Promise<AdminMisreadingReport[]>
}
