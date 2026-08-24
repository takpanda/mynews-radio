export interface AdminEpisodeLogsEpisode {
  id: number
  episode_date: string
  seq: number
  status: string
  type: string
  created_at: string
  updated_at: string
}

export interface AdminEpisodeLogsJob {
  id: number
  operation: string
  owner: { id: number; username: string }
  client_ip_hash: string | null
  status: string
  claimed_at: string | null
  finished_at: string | null
}

export type AdminEpisodeLogsTimelineSource = 'audit' | 'phase' | 'llm'
export type AdminEpisodeLogsPhase = 'synthesize' | 'wav_combine' | 'mp3_encode'

export interface AdminEpisodeLogsTimelineEvent {
  source: AdminEpisodeLogsTimelineSource
  source_id: number
  call_id?: string
  generation_job_id: number | null
  operation: string | null
  phase: string | null
  attempt_no: number | null
  result: string | null
  occurred_at: string | null
  started_at: string | null
  ended_at: string | null
  duration_ms: number | null
  reason: string | null
  tts_engine: string | null
  line_success_count: number | null
  line_total_count: number | null
  model?: string | null
  provider?: string | null
}

export type AdminEpisodeLogsLlmCallStatus = 'success' | 'retry' | 'json_parse_failed' | 'error'

export interface AdminEpisodeLogsLlmCallMeta {
  id: number
  call_id: string
  episode_id: number | null
  phase: string
  provider: string
  model: string
  base_url: string
  attempt: number
  status: AdminEpisodeLogsLlmCallStatus
  latency_ms: number | null
  created_at: string
}

export interface AdminEpisodeLogsLlmCallDetail extends AdminEpisodeLogsLlmCallMeta {
  prompt_text: string
  response_text: string
  thinking_text: string
}

export interface AdminEpisodeLogsLine {
  phase_log_id: number
  attempt_no: number
  script_line_index: number
  article_id: number | null
  speaker: string | null
  section: string | null
  delivery: string | null
  tts_engine: string | null
  speaking_rate: number | null
  processing_duration_ms: number | null
  synth_result: 'success' | 'failure'
  retry_count: number
  wav_file: string | null
  silence_before_sec: number | null
  start_time_sec: number | null
  failure_reason: string | null
}

export interface AdminEpisodeLogs {
  episode: AdminEpisodeLogsEpisode
  generation_jobs: AdminEpisodeLogsJob[]
  timeline: AdminEpisodeLogsTimelineEvent[]
  llm_calls: AdminEpisodeLogsLlmCallMeta[]
  lines: AdminEpisodeLogsLine[]
}

const API_BASE = process.env.API_BASE ?? 'http://api:8010'

async function serverHeaders(): Promise<Record<string, string>> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const { cookies } = await import('next/headers')
  const cookie = (await cookies()).get('admin_session')?.value
  if (cookie) headers['Cookie'] = `admin_session=${cookie}`
  return headers
}

/** サーバーサイド専用：バックエンドへ直接アクセス（認証ヘッダー付与） */
export async function fetchAdminEpisodeLogs(
  episodeId: number,
  phaseLogId?: number,
): Promise<AdminEpisodeLogs | null> {
  const query = phaseLogId ? `?phase_log_id=${phaseLogId}` : ''
  const res = await fetch(`${API_BASE}/admin/episodes/${episodeId}/logs${query}`, {
    headers: await serverHeaders(),
    cache: 'no-store' as RequestCache,
  })
  if (res.status === 404) return null
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `Failed to fetch episode logs: ${res.status}`)
  }
  return res.json() as Promise<AdminEpisodeLogs>
}

/** クライアントサイド専用：中継APIを経由して過去の合成試行の行ログを取得する */
export async function fetchAdminEpisodeLogsClient(
  episodeId: number,
  phaseLogId?: number,
): Promise<AdminEpisodeLogs> {
  const query = phaseLogId ? `?phase_log_id=${phaseLogId}` : ''
  const res = await fetch(`/api/admin/episodes/${episodeId}/logs${query}`, {
    headers: { 'Content-Type': 'application/json' },
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `Failed to fetch episode logs: ${res.status}`)
  }
  return res.json() as Promise<AdminEpisodeLogs>
}

/** クライアントサイド専用：1件のLLM呼び出し本文（prompt/response/thinking）を取得する */
export async function fetchAdminEpisodeLlmCallClient(
  episodeId: number,
  callId: string,
): Promise<AdminEpisodeLogsLlmCallDetail> {
  const res = await fetch(`/api/admin/episodes/${episodeId}/llm-calls/${encodeURIComponent(callId)}`, {
    headers: { 'Content-Type': 'application/json' },
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `Failed to fetch llm call: ${res.status}`)
  }
  return res.json() as Promise<AdminEpisodeLogsLlmCallDetail>
}

/** エピソード別JSONLのダウンロードURL（中継APIを経由） */
export function llmCallsDownloadUrl(episodeId: number): string {
  return `/api/admin/episodes/${episodeId}/llm-calls/download`
}

/** タイムゾーンなしのSQLite形式（"YYYY-MM-DD HH:MM:SS"）をUTCとして解釈できるよう補う */
function normalizeTimestamp(value: string): string {
  const withT = value.includes('T') ? value : value.replace(' ', 'T')
  return /(Z|[+-]\d{2}:?\d{2})$/.test(withT) ? withT : `${withT}Z`
}

/** 「2026/08/14 10:00:05」形式。未確定はダッシュで表す */
export function formatEventDateTime(value: string | null): string {
  if (!value) return '—'
  const d = new Date(normalizeTimestamp(value))
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('ja-JP', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

/** ミリ秒を「2分26秒」「850ms」のように読みやすい単位へ整形する */
export function formatDurationMs(ms: number | null): string {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return `${ms}ms`
  const totalSeconds = ms / 1000
  if (totalSeconds < 60) return `${totalSeconds.toFixed(1)}秒`
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = Math.round(totalSeconds % 60)
  return `${minutes}分${seconds}秒`
}

export function formatSeconds(value: number | null): string {
  if (value === null || value === undefined) return '—'
  return `${value.toFixed(1)}秒`
}

const PHASE_LABELS: Record<AdminEpisodeLogsPhase, string> = {
  synthesize: '音声合成',
  wav_combine: '音声結合',
  mp3_encode: 'MP3エンコード',
}

export function phaseLabel(phase: string | null): string {
  if (phase && phase in PHASE_LABELS) return PHASE_LABELS[phase as AdminEpisodeLogsPhase]
  return phase ?? '操作'
}

const LLM_PHASE_LABELS: Record<string, string> = {
  summarize: '要約',
  script: '台本生成',
  arc: '構成（Narrative Arc）',
  review: 'レビュー',
  correction: '修正',
  category: 'カテゴリ選定',
  unknown: '不明',
}

export function llmPhaseLabel(phase: string | null): string {
  if (!phase) return '不明'
  return LLM_PHASE_LABELS[phase] ?? phase
}

export interface ResultLabel {
  text: string
  icon: string
  tone: 'success' | 'failure' | 'warning' | 'pending' | 'neutral'
}

const RESULT_LABELS: Record<string, ResultLabel> = {
  success: { text: '成功', icon: '✓', tone: 'success' },
  failure: { text: '失敗', icon: '✕', tone: 'failure' },
  rejected: { text: '却下', icon: '⚠', tone: 'warning' },
  started: { text: '受付・処理中', icon: '…', tone: 'pending' },
  incomplete: { text: '未確定', icon: '…', tone: 'pending' },
  retry: { text: '再試行', icon: '↻', tone: 'warning' },
  json_parse_failed: { text: 'JSON解析失敗', icon: '✕', tone: 'failure' },
  error: { text: 'エラー', icon: '✕', tone: 'failure' },
}

export function resultLabel(result: string | null): ResultLabel {
  if (result && RESULT_LABELS[result]) return RESULT_LABELS[result]
  return { text: result ?? '不明', icon: '?', tone: 'neutral' }
}

const RESULT_TONE_CLASSES: Record<ResultLabel['tone'], string> = {
  success: 'text-emerald-700',
  failure: 'text-rose-700',
  warning: 'text-amber-700',
  pending: 'text-sky-700',
  neutral: 'text-slate-500',
}

export function resultToneClassName(tone: ResultLabel['tone']): string {
  return RESULT_TONE_CLASSES[tone]
}
