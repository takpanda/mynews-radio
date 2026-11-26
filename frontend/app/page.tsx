import {
  fetchLatestEpisode,
  fetchEpisodes,
  fetchEpisodeScript,
  buildAudioUrl,
  formatDateWithWeekday,
  formatGeneratedTime,
  type Episode,
  type PaginatedEpisodesResponse,
} from './lib/api'
import { buildChapters, type Chapter } from './lib/chapters'
import HomeShell, { type HeroEpisode } from './components/HomeShell'
import { hasValidAdminSession } from './admin/auth'

function toHeroEpisode(episode: Episode): HeroEpisode {
  return {
    id: episode.id,
    title: episode.title,
    subtitle: episode.subtitle,
    date: episode.date,
    dateLabel: formatDateWithWeekday(episode.date),
    generatedAtLabel: episode.generated_at ? formatGeneratedTime(episode.generated_at) : undefined,
    isCommentary: episode.type === 'commentary',
    sourceUrl: episode.source_url ?? null,
    audioUrl: episode.audio_url ? buildAudioUrl(episode.audio_url) : null,
    durationSeconds: episode.duration_seconds || 0,
    keyPoints: episode.key_points ?? [],
    categories: episode.categories ?? [],
  }
}

const PAGE_SIZE = 20
// ダイジェスト取得が遅くても通常一覧の表示を待たせない上限（超過時はタブ非表示）
const DIGEST_TIMEOUT_MS = 3000

function fetchDigestEpisodes(): Promise<PaginatedEpisodesResponse | null> {
  let timer: ReturnType<typeof setTimeout> | undefined
  const timeout = new Promise<null>((resolve) => { timer = setTimeout(() => resolve(null), DIGEST_TIMEOUT_MS) })
  const request = (fetchEpisodes(PAGE_SIZE, 0, undefined, 'digest') as Promise<PaginatedEpisodesResponse>).catch(() => null)
  return Promise.race([request, timeout]).finally(() => clearTimeout(timer))
}

export default async function Home() {
  let latestEpisode: Episode | null = null
  let initialData: PaginatedEpisodesResponse | null = null
  let error: string | null = null

  // 公開済みダイジェスト回（「ダイジェスト」タブの表示判定と一覧に使う）。失敗・遅延時はタブを出さないだけにする
  const digestPromise = fetchDigestEpisodes()

  try {
    ;[latestEpisode, initialData] = await Promise.all([
      fetchLatestEpisode(),
      fetchEpisodes(PAGE_SIZE, 0) as Promise<PaginatedEpisodesResponse>,
    ])
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

  const digestData = error ? null : await digestPromise

  const isAuthenticated = await hasValidAdminSession()

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
          initialEpisodes={initialData!.items}
          initialHasNext={initialData!.has_next}
          initialDigestEpisodes={digestData?.items ?? []}
          initialDigestHasNext={digestData?.has_next ?? false}
          isAuthenticated={isAuthenticated}
        />
      )}
    </main>
  )
}
