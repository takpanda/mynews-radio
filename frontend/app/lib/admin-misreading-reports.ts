export interface AdminMisreadingReport {
  id: number
  target_text: string
  correct_reading: string
  article_id: number | null
  notes: string
  created_at: string
}

const API_BASE = process.env.API_BASE ?? 'http://api:8010'
const API_KEY = process.env.API_KEY

function serverHeaders(): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (API_KEY) {
    headers['Authorization'] = `Bearer ${API_KEY}`
  }
  return headers
}

/** サーバーサイド専用：バックエンドへ直接アクセス（認証ヘッダー付与） */
export async function fetchAdminMisreadingReports(): Promise<AdminMisreadingReport[]> {
  const res = await fetch(`${API_BASE}/admin/reports/misreading`, {
    headers: serverHeaders(),
    cache: 'no-store' as RequestCache,
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `Failed to fetch misreading reports: ${res.status}`)
  }
  return res.json() as Promise<AdminMisreadingReport[]>
}
