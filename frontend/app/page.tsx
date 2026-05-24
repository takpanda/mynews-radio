import { fetchLatestEpisode, fetchEpisodes, buildAudioUrl, formatDate } from './lib/api'
import AudioPlayer from './components/AudioPlayer'
import EpisodeList from './components/EpisodeList'

export default async function Home() {
  let latestEpisode = null
  let episodes = []
  let error: string | null = null

  try {
    ;[latestEpisode, episodes] = await Promise.all([fetchLatestEpisode(), fetchEpisodes()])
  } catch {
    error = 'エラーが発生しました。しばらく後でもう一度お試しください。'
  }

  return (
    <main className="max-w-lg mx-auto px-4 py-6">
      <header className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">MyNews Radio</h1>
        <p className="text-sm text-gray-500 mt-1">あなた専用のニュース番組</p>
      </header>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl p-4 mb-6 text-sm">
          {error}
        </div>
      )}

      {!error && !latestEpisode && (
        <div className="text-center py-16">
          <p className="text-5xl mb-4">📻</p>
          <p className="text-gray-500">番組がまだありません</p>
        </div>
      )}

      {!error && latestEpisode && (
        <section className="mb-8">
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">
            最新エピソード
          </h2>
          <div className="bg-white rounded-2xl shadow-md p-4 mb-3">
            <p className="font-semibold text-gray-900">
              {latestEpisode.title || `エピソード #${latestEpisode.id}`}
            </p>
            <p className="text-xs text-gray-500 mt-1">{formatDate(latestEpisode.date)}</p>
          </div>
          {latestEpisode.audio_url ? (
            <AudioPlayer
              src={buildAudioUrl(latestEpisode.audio_url)}
              title={latestEpisode.title || `エピソード #${latestEpisode.id}`}
            />
          ) : (
            <div className="bg-white rounded-2xl shadow-sm p-4 text-sm text-gray-400 text-center">
              音声ファイルを準備中です
            </div>
          )}
        </section>
      )}

      {!error && episodes.length > 0 && (
        <section>
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">
            過去のエピソード
          </h2>
          <EpisodeList episodes={episodes} />
        </section>
      )}
    </main>
  )
}
