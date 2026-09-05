'use client'

import { useRef, useState, useMemo, useCallback } from 'react'
import Link from 'next/link'
import { formatPublishedAt, type Script, type ScriptLine, type Article, type EpisodeItem, type EpisodeCorrection, type SourceArticle, type EpisodeTopic } from '../lib/api'
import { buildChapters } from '../lib/chapters'
import {
  buildPlaybackReportContext,
  buildScriptLineReportContext,
  buildArticleReportContext,
  type PlaybackContext,
} from '../lib/misreading-report-context'
import EpisodeAudioPlayer, { type PlayerHandle } from './EpisodeAudioPlayer'
import ScriptViewer from './ScriptViewer'
import ArticleLinks from './ArticleLinks'
import SynthesizeAudioButton from './SynthesizeAudioButton'
import MisreadingReportForm from './MisreadingReportForm'

export interface DetailEpisode {
  id: number
  title: string
  subtitle: string
  date: string
  dateLabel: string
  isCommentary: boolean
  sourceUrl: string | null
  audioUrl: string | null
  durationSeconds: number
  generationPhase?: string
  generatedAtLabel?: string
  keyPoints?: string[]
  llmModel?: string | null
  sourceArticles?: SourceArticle[]
  topics?: EpisodeTopic[]
  corrections?: EpisodeCorrection[]
}

export interface EpisodeSummary {
  intro: string
  topics: string[]
}

interface Props {
  episode: DetailEpisode
  script: Script | null
  articles: Article[]
  episodeItems: EpisodeItem[]
  summary: EpisodeSummary | null
  isAuthenticated?: boolean
}

export default function EpisodeDetailShell({ episode, script, articles, episodeItems, summary, isAuthenticated = false }: Props) {
  const playerRef = useRef<PlayerHandle>(null)
  // undefinedは未再生（停止中）、0は再生位置が先頭であることを表す
  const [currentTime, setCurrentTime] = useState<number | undefined>(undefined)
  const [reportContext, setReportContext] = useState<PlaybackContext | null>(null)
  const [reportOpen, setReportOpen] = useState(false)

  const chapters = useMemo(() => buildChapters(script), [script])

  const hasScript = Boolean(script && script.lines.length > 0)
  const hasArticleWithUrl = articles.some((a) => a.url)
  const hasArticles = hasArticleWithUrl || Boolean(episode.sourceUrl)
  const isSingleUrlCommentary = episode.isCommentary && Boolean(episode.sourceUrl) && !hasArticleWithUrl
  const articlesHeading = isSingleUrlCommentary ? '解説の元記事' : '元記事'
  const title = episode.title || `エピソード #${episode.id}`
  const sourceArticles = episode.sourceArticles ?? []
  const topics = episode.topics ?? []
  const corrections = episode.corrections ?? []
  const formatCorrectionDate = (value: string | null) => value ? formatPublishedAt(value) : '日時不明'

  const correctionTopicLabels = (correction: EpisodeCorrection): string[] => {
    if (correction.affected_topic?.trim()) return [correction.affected_topic.trim()]
    return correction.affected_article_ids
      .map((id) => sourceArticles.find((article) => article.id === id)?.title)
      .filter((label): label is string => Boolean(label?.trim()))
  }

  const openPlaybackReport = useCallback(() => {
    setReportContext(buildPlaybackReportContext(episode, script, episodeItems, currentTime ?? 0))
    setReportOpen(true)
  }, [script, episodeItems, currentTime, episode.id, episode.audioUrl, episode.generationPhase])

  const openScriptLineReport = useCallback((line: ScriptLine) => {
    setReportContext(buildScriptLineReportContext(episode.id, line))
    setReportOpen(true)
  }, [episode.id])

  const openArticleReport = useCallback((article: Article) => {
    setReportContext(buildArticleReportContext(episode.id, article.id, episodeItems))
    setReportOpen(true)
  }, [episode.id, episodeItems])

  const closeReport = useCallback(() => {
    setReportOpen(false)
    setReportContext(null)
  }, [])

  return (
    <div className="space-y-6">
      {/* エピソード概要 */}
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <p className="text-xs text-slate-400">エピソード ・ {episode.dateLabel}{episode.generatedAtLabel ? ` ・ 生成 ${episode.generatedAtLabel}` : ''}</p>
          {isAuthenticated && (
            <Link
              href={`/admin/episodes/${episode.id}/logs`}
              className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-2.5 py-1 text-xs text-slate-500 transition hover:border-slate-300 hover:text-slate-800"
            >
              生成詳細ログ
            </Link>
          )}
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <h1 className="text-lg font-semibold leading-snug text-slate-900 sm:text-xl">
            {title}
          </h1>
          {episode.isCommentary && (
            <span className="inline-flex items-center rounded-full bg-violet-50 px-2.5 py-0.5 text-xs font-medium text-violet-700">
              解説
            </span>
          )}
          {episode.llmModel?.trim() && (
            <span
              className="inline-flex max-w-full whitespace-normal break-all rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600"
              title="LLMモデル"
              aria-label={`LLMモデル: ${episode.llmModel.trim()}`}
            >
              {episode.llmModel.trim()}
            </span>
          )}
        </div>
        {episode.subtitle && (
          <p className="mt-1 text-sm leading-6 text-slate-500">{episode.subtitle}</p>
        )}

        <section className="mt-4 border-t border-slate-100 pt-4" aria-labelledby="episode-info-heading">
          <h2 id="episode-info-heading" className="text-sm font-semibold text-slate-900">この回の情報</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            {episode.generatedAtLabel ? `番組作成日時 ${episode.generatedAtLabel} ・ ` : ''}利用元記事 {sourceArticles.length}件 ・ AIによる要約・構成
          </p>
        </section>

        {corrections.length > 0 && (
          <section className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3" aria-labelledby="correction-heading">
            <h2 id="correction-heading" className="text-sm font-semibold text-amber-900">訂正済み</h2>
            {corrections.map((correction) => (
              <div key={correction.id} className="mt-2 text-sm leading-6 text-amber-950">
                <p className="text-xs text-amber-800">最終訂正 {formatCorrectionDate(correction.corrected_at)}</p>
                <p>{correction.reason || '番組内容を訂正しました。'}</p>
                {correctionTopicLabels(correction).length > 0 && (
                  <p className="text-xs text-amber-800">影響トピック: {correctionTopicLabels(correction).join('、')}</p>
                )}
              </div>
            ))}
          </section>
        )}

        {episode.keyPoints && episode.keyPoints.length > 0 && (
          <div className="mt-4 border-t border-slate-100 pt-4">
            <h2 className="text-sm font-semibold text-slate-900">この回で分かること</h2>
            <ul className="mt-2 space-y-1.5">
              {episode.keyPoints.map((point) => (
                <li key={point} className="flex items-start gap-2 text-sm leading-6 text-slate-700">
                  <span
                    aria-hidden="true"
                    className="mt-2.5 h-1 w-1 shrink-0 rounded-full bg-emerald-500"
                  />
                  <span className="break-words min-w-0">{point}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {summary && (
          <div className="mt-4 border-t border-slate-100 pt-4">
            <p className="text-sm leading-7 text-slate-600">{summary.intro}</p>
            {summary.topics.length > 0 && (
              <ul className="mt-2 space-y-1.5">
                {summary.topics.map((topic) => (
                  <li key={topic} className="flex items-start gap-2 text-sm leading-6 text-slate-700">
                    <span
                      aria-hidden="true"
                      className="mt-2.5 h-1 w-1 shrink-0 rounded-full bg-sky-500"
                    />
                    <span className="break-words min-w-0">{topic}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {(hasScript || hasArticles) && (
          <div className="mt-4 flex items-center gap-1.5 text-xs">
            {hasScript && (
              <a
                href="#script"
                className="rounded-full border border-slate-200 px-2.5 py-1 text-slate-500 transition hover:border-slate-300 hover:text-slate-800"
              >
                台本
              </a>
            )}
            {hasArticles && (
              <a
                href="#articles"
                className="rounded-full border border-slate-200 px-2.5 py-1 text-slate-500 transition hover:border-slate-300 hover:text-slate-800"
              >
                {articlesHeading}
              </a>
            )}
          </div>
        )}
      </section>

      {/* プレーヤー */}
      <section
        id="player"
        className="scroll-mt-20 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"
      >
        {episode.audioUrl ? (
          <EpisodeAudioPlayer
            ref={playerRef}
            audioUrl={episode.audioUrl}
            title={title}
            date={episode.date}
            durationSeconds={episode.durationSeconds}
            chapters={chapters}
            onTimeUpdate={setCurrentTime}
            onMisreadingReport={openPlaybackReport}
          />
        ) : hasScript ? (
          isAuthenticated ? <SynthesizeAudioButton episodeId={episode.id} /> : (
            <div className="py-4 text-center">
              <p className="text-sm text-slate-500">音声の再合成はログイン後に利用できます</p>
              <a href="/admin/login" className="mt-3 inline-flex rounded-xl bg-sky-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-sky-700">ログインして再合成</a>
            </div>
          )
        ) : (
          <p className="py-4 text-center text-sm text-slate-400">音声ファイルを準備中です</p>
        )}
      </section>

      {/* 台本 */}
      {hasScript && (
        <section id="script" className="scroll-mt-20">
          <h2 className="mb-2 px-1 text-sm font-semibold text-slate-900">台本</h2>
          <ScriptViewer
            lines={script!.lines}
            sourceArticles={sourceArticles}
            topics={topics}
            currentTime={currentTime}
            onSeek={episode.audioUrl ? (time) => playerRef.current?.seekTo(time) : undefined}
            onMisreadingReport={openScriptLineReport}
          />
        </section>
      )}

      {/* 元記事 */}
      {hasArticles && (
        <section id="articles" className="scroll-mt-20">
          <h2 className="mb-2 px-1 text-sm font-semibold text-slate-900">{articlesHeading}</h2>
          <ArticleLinks articles={articles} sourceUrl={episode.sourceUrl} onReportArticle={openArticleReport} />
        </section>
      )}

      {/* 読み間違い報告フォーム */}
      {reportOpen && (
        <MisreadingReportForm playbackContext={reportContext} onClose={closeReport} />
      )}
    </div>
  )
}
