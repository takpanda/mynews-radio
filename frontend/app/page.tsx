import {
  fetchLatestEpisode,
  fetchEpisodes,
  fetchEpisodeScript,
  buildAudioUrl,
  type Episode,
  type EpisodeListItem,
  type Script,
} from './lib/api'
import HomeShell, { type Chapter, type HeroEpisode } from './components/HomeShell'

const SECTION_LABEL: Record<string, string> = {
  intro: 'オープニング',
  news: 'ニュース',
  discussion: '討論',
  outro: 'エンディング',
}

function buildChapters(script: Script | null): Chapter[] {
  if (!script) return []
  const chapters: Chapter[] = []
  let prevSection: string | null = null
  for (const line of script.lines) {
    if (line.section === prevSection) continue
    prevSection = line.section
    if (typeof line.start_time === 'number') {
      chapters.push({
        label: SECTION_LABEL[line.section] ?? line.section,
        startTime: line.start_time,
      })
    }
  }
  // 1件だけでは章として意味がないため出さない
  return chapters.length >= 2 ? chapters : []
}

const WEEKDAYS = ['日', '月', '火', '水', '木', '金', '土']

function formatHeroDate(dateStr: string): string {
  const [y, m, d] = dateStr.slice(0, 10).split('-').map(Number)
  if (!y || !m || !d) return dateStr
  const weekday = WEEKDAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()]
  return `${m}月${d}日（${weekday}）`
}

function toHeroEpisode(episode: Episode): HeroEpisode {
  return {
    id: episode.id,
    title: episode.title,
    subtitle: episode.subtitle,
    dateLabel: formatHeroDate(episode.date),
    isCommentary: episode.type === 'commentary',
    sourceUrl: episode.source_url ?? null,
    audioUrl: episode.audio_url ? buildAudioUrl(episode.audio_url) : null,
    durationSeconds: episode.duration_seconds || 0,
  }
}

export default async function Home() {
  let latestEpisode: Episode | null = null
  let episodes: EpisodeListItem[] = []
  let error: string | null = null

  try {
    ;[latestEpisode, episodes] = await Promise.all([fetchLatestEpisode(), fetchEpisodes()])
  } catch {
    error = 'エラーが発生しました。しばらく後でもう一度お試しください。'
  }

  let chapters: Chapter[] = []
  if (latestEpisode?.audio_url) {
    try {
      chapters = buildChapters(await fetchEpisodeScript(latestEpisode.id))
    } catch {
      // 章情報はなくても再生に支障がないため無視する
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-4 pb-24 pt-6 sm:px-6">
      {error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      ) : (
        <HomeShell
          latest={latestEpisode ? toHeroEpisode(latestEpisode) : null}
          chapters={chapters}
          episodes={episodes}
        />
      )}
    </main>
  )
}
