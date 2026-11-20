export type DashboardRange = '7d' | '30d'

export interface DashboardPhaseDuration {
  phase: string
  count: number
  avg_ms: number | null
  max_ms: number | null
}

export interface DashboardRecentFailure {
  occurred_at: string
  episode_id: number
  phase: string | null
  reason: string
}

export interface DashboardLlmLatency {
  phase: string
  call_count: number
  avg_latency_ms: number | null
  max_latency_ms: number | null
}

export interface DashboardLlmAnomaly {
  phase: string
  retry_count: number
  json_parse_failed_count: number
}

export interface DashboardStats {
  range: DashboardRange
  since: string
  generated_at: string
  episodes: {
    completed: number
    failed: number
    in_progress: number
    success_rate: number | null
  }
  phase_durations: DashboardPhaseDuration[]
  failures: {
    by_reason: Record<string, number>
    llm_error_count: number
    episodes_without_phase_log: number
    recent: DashboardRecentFailure[]
  }
  llm: {
    latency_by_phase: DashboardLlmLatency[]
    retry_count: number
    json_parse_failed_count: number
    anomalies_by_phase: DashboardLlmAnomaly[]
  }
  pending: {
    unapproved_misreading_reports: number
    awaiting_review_episodes: number
  }
}

export const DASHBOARD_RANGES: DashboardRange[] = ['7d', '30d']

const API_BASE = process.env.API_BASE ?? 'http://api:8010'

/** サーバーサイド専用：バックエンドへ直接アクセス（認証ヘッダー付与） */
export async function fetchDashboardStats(range: DashboardRange = '7d'): Promise<DashboardStats> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const { cookies } = await import('next/headers')
  const cookie = (await cookies()).get('admin_session')?.value
  if (cookie) headers['Cookie'] = `admin_session=${cookie}`
  const res = await fetch(`${API_BASE}/admin/dashboard/stats?range=${range}`, {
    headers,
    cache: 'no-store' as RequestCache,
  })
  if (!res.ok) throw new Error(`Failed to fetch dashboard stats: ${res.status}`)
  return res.json() as Promise<DashboardStats>
}

/** クライアントサイド専用：Next.js のプロキシ経由で集計を取得する */
export async function fetchDashboardStatsClient(range: DashboardRange): Promise<DashboardStats> {
  const res = await fetch(`/api/admin/dashboard/stats?range=${range}`, { cache: 'no-store' })
  if (!res.ok) throw new Error(`Failed to fetch dashboard stats: ${res.status}`)
  return res.json() as Promise<DashboardStats>
}

export const FAILURE_REASON_LABELS: Record<string, string> = {
  script_missing: '台本なし',
  tts_no_lines_succeeded: '音声合成が全行失敗',
  tts_synthesis_exception: '音声合成で例外',
  wav_combine_failed: 'WAV結合の失敗',
  mp3_encode_failed: 'MP3エンコードの失敗',
  build_exception: '生成処理で例外',
  no_phase_log: '音声合成前の失敗',
}

export function failureReasonLabel(reason: string): string {
  return FAILURE_REASON_LABELS[reason] ?? reason
}

export function formatSuccessRate(rate: number | null): string {
  if (rate === null || Number.isNaN(rate)) return '—'
  // API は 0〜1 の比率で返す
  return `${Math.round(rate * 1000) / 10}%`
}

export function formatMs(value: number | null): string {
  if (value === null || Number.isNaN(value)) return '—'
  return `${Math.round(value).toLocaleString('ja-JP')} ms`
}
