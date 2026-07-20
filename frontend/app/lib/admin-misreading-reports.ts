export interface AdminMisreadingReport {
  id: number
  target_text: string
  correct_reading: string
  article_id: number | null
  notes: string
  approved: boolean
  approved_at: string | null
  approved_dictionary_entry_id: number | null
  created_at: string
}

export interface ApproveResult {
  status: 'approved' | 'skipped' | 'already_approved'
  report_id: number
  dictionary_entry_id?: number
  reason?: string
  existing_entry_id?: number
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

/** クライアントサイド専用：読み間違い報告を承認し辞書登録する */
export async function approveMisreadingReport(
  reportId: number,
): Promise<ApproveResult> {
  const res = await fetch(`/api/admin/reports/misreading/${reportId}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `Approve failed: ${res.status}`)
  }
  return res.json() as Promise<ApproveResult>
}
