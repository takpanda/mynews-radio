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
import EpisodePlayer from '../../components/EpisodePlayer'
import ArticleLinks from '../../components/ArticleLinks'
import EpisodeQuickActions from '../../components/EpisodeQuickActions'

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

  const hasScript = Boolean(script && script.lines.length > 0)
  const hasArticles = articles.length > 0

  return (
    <main className="mx-auto max-w-6xl px-4 py-6 pb-28 sm:px-6 lg:px-8 lg:py-10 lg:pb-32">
      <div className="mb-6">
        <Link
          href="/"
          className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white/85 px-4 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:border-slate-300 hover:bg-white"
        >
          <span aria-hidden="true">←</span>
          ホームへ戻る
        </Link>
      </div>

      {error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 shadow-sm">
          {error}
        </div>
      )}

      {episode && (
        <>
          <header className="mb-8 rounded-[2rem] border border-white/70 bg-[radial-gradient(circle_at_top_left,_rgba(125,211,252,0.22),_transparent_26%),linear-gradient(135deg,_rgba(255,255,255,0.94),_rgba(241,245,249,0.95))] p-6 shadow-[0_24px_70px_rgba(15,23,42,0.08)] sm:p-8">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="max-w-3xl">
                <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">
                  Episode Detail
                </p>
                <h1 className="mt-3 text-3xl font-semibold leading-tight text-slate-950 sm:text-4xl">
                  {episode.title || `エピソード #${episode.id}`}
                </h1>
                {episode.subtitle && (
                  <p className="mt-3 text-base leading-7 text-sky-700">{episode.subtitle}</p>
                )}
                <p className="mt-4 text-sm text-slate-500">{formatDate(episode.date)}</p>
              </div>

              <div className="grid min-w-[220px] gap-3 sm:grid-cols-2 lg:grid-cols-1">
                <a
                  href="#player"
                  className="inline-flex min-h-12 items-center justify-center rounded-2xl bg-slate-900 px-4 text-sm font-medium text-white shadow-sm transition hover:bg-slate-800"
                >
                  再生セクションへ
                </a>
                {hasArticles ? (
                  <a
                    href="#articles"
                    className="inline-flex min-h-12 items-center justify-center rounded-2xl border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50"
                  >
                    元記事を見る
                  </a>
                ) : (
                  <a
                    href="#script"
                    className="inline-flex min-h-12 items-center justify-center rounded-2xl border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50"
                  >
                    台本へ進む
                  </a>
                )}
              </div>
            </div>

            <div className="mt-6 grid gap-3 sm:grid-cols-3">
              <div className="rounded-2xl border border-white/80 bg-white/80 p-4 backdrop-blur">
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Listen</p>
                <p className="mt-2 text-sm font-medium text-slate-900">下部の固定操作からいつでも再生位置へ戻れます。</p>
              </div>
              <div className="rounded-2xl border border-white/80 bg-white/80 p-4 backdrop-blur">
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Read</p>
                <p className="mt-2 text-sm font-medium text-slate-900">長い台本でも、セクション移動の負担を減らしました。</p>
              </div>
              <div className="rounded-2xl border border-white/80 bg-white/80 p-4 backdrop-blur">
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">Source</p>
                <p className="mt-2 text-sm font-medium text-slate-900">元記事への移動も固定操作からすぐ開けます。</p>
              </div>
            </div>
          </header>

          {episode.audio_url ? (
            <EpisodePlayer
              episode={episode}
              script={script}
              audioUrl={buildAudioUrl(episode.audio_url)}
            />
          ) : (
            <div className="bg-white rounded-2xl shadow-sm p-4 mb-8 text-sm text-gray-400 text-center">
              音声ファイルを準備中です
            </div>
          )}

          {articles.length > 0 && (
            <section id="articles" className="mb-8 scroll-mt-28">
              <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-gray-400">
                元記事
              </h2>
              <ArticleLinks articles={articles} />
            </section>
          )}

          <EpisodeQuickActions hasScript={hasScript} hasArticles={hasArticles} />
        </>
      )}
    </main>
  )
}
