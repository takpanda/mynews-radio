import {
  fetchLatestEpisode,
  fetchEpisodes,
  fetchEpisodeScript,
  buildAudioUrl,
  formatDateWithWeekday,
  type Episode,
  type EpisodeListItem,
} from './lib/api'
import { buildChapters, type Chapter } from './lib/chapters'
import HomeShell, { type HeroEpisode } from './components/HomeShell'

function toHeroEpisode(episode: Episode): HeroEpisode {
  return {
    id: episode.id,
    title: episode.title,
    subtitle: episode.subtitle,
    dateLabel: formatDateWithWeekday(episode.date),
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
