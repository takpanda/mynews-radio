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
import SynthesizeAudioButton from '../../components/SynthesizeAudioButton'

interface Props {
  params: { id: string }
}

interface EpisodeSummaryContent {
  intro: string
  topics: string[]
}

function normalizeSummaryText(text: string): string {
  const compact = text.replace(/\s+/g, ' ').trim()
  if (!compact) return ''
  return /[。.!！?？]$/.test(compact) ? compact : `${compact}。`
}

function splitSummaryIntoTopics(summary: string): string[] {
  const sentences = summary
    .split(/(?<=[。.!！?？])/)
    .map((sentence) => sentence.trim())
    .filter(Boolean)

  const topics: string[] = []
  for (let index = 0; index < sentences.length; index += 2) {
    topics.push(sentences.slice(index, index + 2).join(' '))
  }

  return topics.slice(0, 3)
}

function buildEpisodeSummary(episodeSubtitle: string, articles: Article[]): EpisodeSummaryContent | null {
  const titles = articles
    .map((article) => article.title.trim())
    .filter((title, index, list) => Boolean(title) && list.indexOf(title) === index)
    .slice(0, 3)

  const intro = episodeSubtitle
    ? `今回は${episodeSubtitle}を軸に、背景と日々の暮らしへの影響を追えるようにまとめています。`
    : '今回の主なトピックを、背景と日々の暮らしへの影響とあわせてまとめています。'

  if (titles.length > 0) {
    const topics = [...titles]
    if (articles.length > titles.length) {
      topics[topics.length - 1] = `${topics[topics.length - 1]} など`
    }

    return {
      intro,
      topics,
    }
  }

  const summaries = articles
    .map((article) => normalizeSummaryText(article.summary ?? ''))
    .filter((summary, index, list) => Boolean(summary) && list.indexOf(summary) === index)
    .slice(0, 1)

  if (summaries.length > 0) {
    return {
      intro,
      topics: splitSummaryIntoTopics(summaries[0]),
    }
  }

  if (episodeSubtitle) {
    return {
      intro: `今回は${episodeSubtitle}を中心に、その日の主要トピックをまとめています。`,
      topics: [],
    }
  }

  return null
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
  const episodeSummary = episode ? buildEpisodeSummary(episode.subtitle, articles) : null

  return (
    <main className="mx-auto max-w-6xl px-4 py-6 pb-14 sm:pb-16 sm:px-6 lg:px-8 lg:py-10 lg:pb-24">
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

            {episodeSummary && (
              <div className="mt-6 rounded-[1.75rem] border border-white/80 bg-white/80 p-5 backdrop-blur sm:p-6">
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                  Episode Summary
                </p>
                <p className="mt-3 text-sm leading-7 text-slate-700 sm:text-[15px]">
                  {episodeSummary.intro}
                </p>
                {episodeSummary.topics.length > 0 && (
                  <div className="mt-3 space-y-0.5">
                    {episodeSummary.topics.map((topic) => (
                      <div
                        key={topic}
                        className="flex items-center gap-2 px-1 py-1"
                      >
                        <span aria-hidden="true" className="flex shrink-0 items-center gap-2">
                          <span className="h-7 w-px rounded-full bg-slate-300" />
                          <span className="h-2 w-2 rotate-45 rounded-[2px] bg-slate-900/80 shadow-[0_0_0_3px_rgba(255,255,255,0.9)]" />
                        </span>
                        <p className="flex-1 text-sm leading-[1.15rem] text-slate-700">
                          {topic}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </header>

          {episode.audio_url ? (
            <EpisodePlayer
              episode={episode}
              script={script}
              audioUrl={buildAudioUrl(episode.audio_url)}
            />
          ) : hasScript ? (
            <div id="player" className="mb-8 scroll-mt-24 max-sm:scroll-mt-[52px] rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <SynthesizeAudioButton episodeId={episode.id} />
            </div>
          ) : (
            <div className="bg-white rounded-2xl shadow-sm p-4 mb-8 text-sm text-gray-400 text-center">
              音声ファイルを準備中です
            </div>
          )}

          {articles.length > 0 && (
            <section id="articles" className="mb-8 scroll-mt-28 max-sm:scroll-mt-[52px]">
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
