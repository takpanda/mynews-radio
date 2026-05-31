import { notFound } from 'next/navigation'
import Link from 'next/link'
import {
  fetchEpisode,
  fetchEpisodeScript,
  fetchArticle,
  buildAudioUrl,
  formatDate,
  type Article,
} from '../../lib/api'
import AudioPlayer from '../../components/AudioPlayer'
import ScriptViewer from '../../components/ScriptViewer'
import ArticleLinks from '../../components/ArticleLinks'

interface Props {
  params: { id: string }
}

export default async function EpisodePage({ params }: Props) {
  const episodeId = parseInt(params.id, 10)
  if (isNaN(episodeId)) notFound()

  let episode = null
  let script = null
  let articles: Article[] = []
  let error: string | null = null

  try {
    ;[episode, script] = await Promise.all([
      fetchEpisode(episodeId),
      fetchEpisodeScript(episodeId),
    ])

    if (!episode) notFound()

    if (script && script.lines.length > 0) {
      const articleIds = [
        ...new Set(
          script.lines
            .map((l) => l.article_id)
            .filter((id): id is number => id !== null),
        ),
      ]
      const results = await Promise.all(articleIds.map((id) => fetchArticle(id)))
      articles = results.filter((a): a is Article => a !== null)
    }
  } catch {
    error = 'エラーが発生しました。しばらく後でもう一度お試しください。'
  }

  if (!episode && !error) notFound()

  return (
    <main className="max-w-lg mx-auto px-4 py-6">
      <div className="mb-6">
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-blue-500 hover:text-blue-700 text-sm"
        >
          ← トップへ
        </Link>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl p-4 text-sm">
          {error}
        </div>
      )}

      {episode && (
        <>
          <header className="mb-6">
            <h1 className="text-xl font-bold text-gray-900">
              {episode.title || `エピソード #${episode.id}`}
            </h1>
            {episode.subtitle && (
              <p className="text-sm text-blue-500 mt-0.5">{episode.subtitle}</p>
            )}
            <p className="text-sm text-gray-500 mt-1">{formatDate(episode.date)}</p>
          </header>

          {episode.audio_url ? (
            <section className="mb-8">
              <AudioPlayer
                src={buildAudioUrl(episode.audio_url)}
                title={episode.title || `エピソード #${episode.id}`}
              />
            </section>
          ) : (
            <div className="bg-white rounded-2xl shadow-sm p-4 mb-8 text-sm text-gray-400 text-center">
              音声ファイルを準備中です
            </div>
          )}

          {articles.length > 0 && (
            <section className="mb-8">
              <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">
                元記事
              </h2>
              <ArticleLinks articles={articles} />
            </section>
          )}

          {script && script.lines.length > 0 && (
            <section className="mb-8">
              <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">
                台本
              </h2>
              <ScriptViewer lines={script.lines} />
            </section>
          )}

          {(!script || script.lines.length === 0) && (
            <div className="text-center text-gray-400 py-8 text-sm">台本がありません</div>
          )}
        </>
      )}
    </main>
  )
}
