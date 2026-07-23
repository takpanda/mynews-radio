export interface DuplicateEpisodeInfo {
  id: number
  status: string
  type: string
  source_url: string
  episode_date: string
  created_at: string
  title: string
  has_script: boolean
}

export interface EpisodeListItem {
  id: number
  title: string
  subtitle: string
  date: string
  duration: number
  audio_url: string
  status: string
  type?: string
  source_url?: string | null
  has_script?: boolean
}

export interface Episode {
  id: number
  title: string
  subtitle: string
  date: string
  duration_seconds: number
  status: string
  type?: string
  source_url?: string | null
  article_count: number
  audio_url: string | null
  articles: EpisodeItem[]
  generation_phase?: string
  generation_message?: string
  generated_at?: string
}

export interface EpisodeItem {
  id: number
  episode_id: number
  article_id: number | null
  item_order: number
  segment_text: string
  audio_generation_id?: string | null
}

export interface Script {
  title: string
  date?: string
  lines: ScriptLine[]
}

export interface ScriptLine {
  speaker: 'male' | 'female'
  text: string
  article_id: number | null
  section: string
  start_time?: number
}

export interface Article {
  id: number
  title: string
  source: string | null
  url: string | null
  summary?: string | null
}

const SERVER_API_BASE = process.env.API_BASE ?? 'http://api:8010'
const CLIENT_API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? '/api'

function getApiBase(): string {
  return typeof window === 'undefined' ? SERVER_API_BASE : CLIENT_API_BASE
}

export function buildAudioUrl(audioPath: string): string {
  if (!audioPath) return ''
  // 絶対URLはそのまま返す（後方互換）
  if (audioPath.startsWith('http')) return audioPath
  // 相対パス（/audio/...）はNext.jsのrewriteでプロキシされるためそのまま返す
  return audioPath
}

export function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  return d.toLocaleDateString('ja-JP', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

const WEEKDAYS = ['日', '月', '火', '水', '木', '金', '土']

// 「7月4日（土）」形式。タイムゾーンに依存しないよう日付文字列から直接組み立てる
export function formatDateWithWeekday(dateStr: string): string {
  const [y, m, d] = dateStr.slice(0, 10).split('-').map(Number)
  if (!y || !m || !d) return dateStr
  const weekday = WEEKDAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()]
  return `${m}月${d}日（${weekday}）`
}

// 生成時刻の表示形式（管理画面の日付表記と統一）。Asia/Tokyo 固定
export function formatGeneratedAt(dateStr: string): string {
  const d = new Date(dateStr)
  return d.toLocaleDateString('ja-JP', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export async function fetchLatestEpisode(): Promise<Episode | null> {
  const res = await fetch(`${getApiBase()}/episodes/latest`, { cache: 'no-store' })
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Failed to fetch latest episode: ${res.status}`)
  return res.json() as Promise<Episode>
}

export interface PaginatedEpisodesResponse {
  items: EpisodeListItem[]
  total: number
  has_next: boolean
}

export async function fetchEpisodes(): Promise<EpisodeListItem[]>
export async function fetchEpisodes(limit: number, offset: number, signal?: AbortSignal): Promise<PaginatedEpisodesResponse>
export async function fetchEpisodes(limit?: number, offset?: number, signal?: AbortSignal): Promise<EpisodeListItem[] | PaginatedEpisodesResponse> {
  let url = `${getApiBase()}/episodes`
  if (limit !== undefined && offset !== undefined) {
    url += `?limit=${limit}&offset=${offset}`
  }
  const res = await fetch(url, { cache: 'no-store', signal })
  if (!res.ok) throw new Error(`Failed to fetch episodes: ${res.status}`)
  return res.json()
}

export async function fetchEpisode(id: number): Promise<Episode | null> {
  const res = await fetch(`${getApiBase()}/episodes/${id}?_t=${Date.now()}`, { cache: 'no-store' })
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Failed to fetch episode: ${res.status}`)
  return res.json() as Promise<Episode>
}

export async function fetchEpisodeScript(id: number): Promise<Script | null> {
  const res = await fetch(`${getApiBase()}/episodes/${id}/script`, { cache: 'no-store' })
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Failed to fetch script: ${res.status}`)
  return res.json() as Promise<Script>
}

export async function fetchArticle(id: number): Promise<Article | null> {
  const res = await fetch(`${getApiBase()}/articles/${id}`, { cache: 'no-store' })
  if (res.status === 404) return null
  if (!res.ok) return null
  return res.json() as Promise<Article>
}

export interface GenerateResponse {
  episode_id: number
}

function parseErrorDetail(body: string): string {
  try {
    const parsed = JSON.parse(body)
    if (typeof parsed.detail === 'string') return parsed.detail
  } catch {}
  return body
}

export async function generateEpisode(date: string, maxArticles = 10, newsSource = 'hatena_bookmark', ttsEngine = 'aivispeech', recreateSummary = false, url?: string, style?: 'solo' | 'dialogue', mcGender?: 'male' | 'female'): Promise<GenerateResponse> {
  const res = await fetch('/api/generate', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      date,
      max_articles: maxArticles,
      news_source: newsSource,
      tts_engine: ttsEngine,
      recreate_summary: recreateSummary,
      ...(url ? { url } : {}),
      ...(style ? { style } : {}),
      ...(style === 'solo' && mcGender ? { mc_gender: mcGender } : {}),
    }),
  })
  if (!res.ok) {
    const errorBody = await res.text().catch(() => '')
    if (res.status === 409) {
      throw new Error('既に生成中のタスクがあります')
    }
    if (res.status === 401) {
      throw new Error('API キーが設定されていません。サーバー設定が必要です。')
    }
    if (res.status === 429) {
      throw new Error('レート制限に達しました。しばらく待ってから再試行してください。')
    }
    throw new Error(parseErrorDetail(errorBody) || `Generate failed: ${res.status}`)
  }
  return res.json() as Promise<GenerateResponse>
}

export async function fetchEpisodeStatus(id: number): Promise<Episode> {
  const res = await fetch(`${getApiBase()}/episodes/${id}`, { cache: 'no-store' })
  if (!res.ok) throw new Error(`Failed to fetch episode status: ${res.status}`)
  return res.json() as Promise<Episode>
}

export async function searchEpisodesBySourceUrl(sourceUrl: string): Promise<DuplicateEpisodeInfo[]> {
  const res = await fetch(`/api/episodes/search/by-source-url?source_url=${encodeURIComponent(sourceUrl)}`, {
    cache: 'no-store',
  })
  if (!res.ok) throw new Error('重複の確認に失敗しました')
  return res.json() as Promise<DuplicateEpisodeInfo[]>
}

export async function synthesizeEpisodeStream(episodeId: number, ttsEngine = 'aivispeech'): Promise<Response> {
  return fetch(`/api/episodes/${episodeId}/synthesize`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({ tts_engine: ttsEngine }),
  })
}
