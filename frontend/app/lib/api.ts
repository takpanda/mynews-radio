export interface EpisodeListItem {
  id: number
  title: string
  date: string
  duration: number
  audio_url: string
  status: string
}

export interface Episode {
  id: number
  title: string
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

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://pi5-3.local:8000'

export function buildAudioUrl(audioPath: string): string {
  if (!audioPath) return ''
  if (audioPath.startsWith('http')) return audioPath
  return `${API_BASE}${audioPath}`
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
  const res = await fetch(`${API_BASE}/episodes/latest`, { cache: 'no-store' })
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Failed to fetch latest episode: ${res.status}`)
  return res.json() as Promise<Episode>
}

export async function fetchEpisodes(): Promise<EpisodeListItem[]> {
  const res = await fetch(`${API_BASE}/episodes`, { cache: 'no-store' })
  if (!res.ok) throw new Error(`Failed to fetch episodes: ${res.status}`)
  return res.json() as Promise<EpisodeListItem[]>
}

export async function fetchEpisode(id: number): Promise<Episode | null> {
  const res = await fetch(`${API_BASE}/episodes/${id}`, { cache: 'no-store' })
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Failed to fetch episode: ${res.status}`)
  return res.json() as Promise<Episode>
}

export async function fetchEpisodeScript(id: number): Promise<Script | null> {
  const res = await fetch(`${API_BASE}/episodes/${id}/script`, { cache: 'no-store' })
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`Failed to fetch script: ${res.status}`)
  return res.json() as Promise<Script>
}

export async function fetchArticle(id: number): Promise<Article | null> {
  const res = await fetch(`${API_BASE}/articles/${id}`, { cache: 'no-store' })
  if (res.status === 404) return null
  if (!res.ok) return null
  return res.json() as Promise<Article>
}
