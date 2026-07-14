import { notFound } from 'next/navigation'
import Link from 'next/link'
import {
  fetchEpisode,
  fetchEpisodeScript,
  fetchArticle,
  buildAudioUrl,
  formatDateWithWeekday,
  type Article,
  type Episode,
} from '../../lib/api'
import EpisodeDetailShell, {
  type DetailEpisode,
  type EpisodeSummary,
} from '../../components/EpisodeDetailShell'

interface Props {
  params: { id: string }
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

function buildEpisodeSummary(episodeSubtitle: string, articles: Article[]): EpisodeSummary | null {
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

function toDetailEpisode(episode: Episode): DetailEpisode {
  return {
    id: episode.id,
    title: episode.title,
    subtitle: episode.subtitle,
    dateLabel: formatDateWithWeekday(episode.date),
    isCommentary: episode.type === 'commentary',
    sourceUrl: episode.source_url ?? null,
    audioUrl: episode.audio_url ? buildAudioUrl(episode.audio_url) : null,
    durationSeconds: episode.duration_seconds || 0,
    generationPhase: episode.generation_phase,
  }
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
    <main className="mx-auto max-w-3xl px-4 pb-24 pt-6 sm:px-6">
      <div className="mb-4">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-sm text-slate-500 transition hover:text-slate-900"
        >
          <span aria-hidden="true">←</span>
          ホーム
        </Link>
      </div>

      {error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {episode && (
        <EpisodeDetailShell
          episode={toDetailEpisode(episode)}
          script={script}
          articles={articles}
          summary={buildEpisodeSummary(episode.subtitle, articles)}
        />
      )}
    </main>
  )
}
