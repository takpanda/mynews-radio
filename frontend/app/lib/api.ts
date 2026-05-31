export interface EpisodeListItem {
  id: number
  title: string
  subtitle: string
  date: string
  duration: number
  audio_url: string
  status: string
}

export interface Episode {
  id: number
  title: string
  subtitle: string
  date: string
  duration_seconds: number
  status: string
  article_count: number
  audio_url: string | null
  articles: EpisodeItem[]
}

export interface EpisodeItem {
  id: number
  episode_id: number
  article_id: number | null
  item_order: number
  segment_text: string
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
}

export interface Article {
  id: number
  title: string
  source: string | null
  url: string | null
}

const SERVER_API_BASE = process.env.API_BASE ?? 'http://api:8010'
const CLIENT_API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://localhost:8010'

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

export async function fetchLatestEpisode(): Promise<Episode | null> {
  const res = await fetch(`${getApiBase()}/episodes/latest`, { cache: 'no-store' })
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Failed to fetch latest episode: ${res.status}`)
  return res.json() as Promise<Episode>
}

export async function fetchEpisodes(): Promise<EpisodeListItem[]> {
  const res = await fetch(`${getApiBase()}/episodes`, { cache: 'no-store' })
  if (!res.ok) throw new Error(`Failed to fetch episodes: ${res.status}`)
  return res.json() as Promise<EpisodeListItem[]>
}

export async function fetchEpisode(id: number): Promise<Episode | null> {
  const res = await fetch(`${getApiBase()}/episodes/${id}`, { cache: 'no-store' })
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

export async function generateEpisode(date: string, maxArticles = 10, newsSource = 'hatena_bookmark'): Promise<Response> {
  return fetch(`${getApiBase()}/generate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      date,
      max_articles: maxArticles,
      news_source: newsSource,
    }),
  })
}

export async function generateEpisodeStream(date: string, maxArticles = 10, newsSource = 'hatena_bookmark', ttsEngine = 'voicevox'): Promise<Response> {
  // 相対 URL を使うことで、別端末からアクセスした場合でも
  // Next.js サーバー経由でバックエンドへ転送される
  return fetch('/api/generate', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({
      date,
      max_articles: maxArticles,
      news_source: newsSource,
      tts_engine: ttsEngine,
    }),
  })
}
