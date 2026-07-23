'use client'

import { useRef, useState, useMemo, useCallback } from 'react'
import type { Script, ScriptLine, Article, EpisodeItem } from '../lib/api'
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
}

export default function EpisodeDetailShell({ episode, script, articles, episodeItems, summary }: Props) {
  const playerRef = useRef<PlayerHandle>(null)
  const [currentTime, setCurrentTime] = useState(0)
  const [reportContext, setReportContext] = useState<PlaybackContext | null>(null)
  const [reportOpen, setReportOpen] = useState(false)

  const chapters = useMemo(() => buildChapters(script), [script])

  const hasScript = Boolean(script && script.lines.length > 0)
  const hasArticles = articles.some((a) => a.url) || Boolean(episode.sourceUrl)
  const title = episode.title || `エピソード #${episode.id}`

  const openPlaybackReport = useCallback(() => {
    setReportContext(buildPlaybackReportContext(episode, script, episodeItems, currentTime))
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
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-slate-400">エピソード ・ {episode.dateLabel}{episode.generatedAtLabel ? ` ・ 生成 ${episode.generatedAtLabel}` : ''}</p>
          <div className="flex items-center gap-1.5 text-xs">
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
                元記事
              </a>
            )}
          </div>
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
        </div>
        {episode.subtitle && (
          <p className="mt-1 text-sm leading-6 text-slate-500">{episode.subtitle}</p>
        )}
        {episode.sourceUrl && (
          <a
            href={episode.sourceUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-2 inline-flex max-w-full items-center gap-1.5 text-xs text-slate-400 transition hover:text-sky-600"
          >
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              className="h-3.5 w-3.5 shrink-0"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
              <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
            </svg>
            <span className="truncate">{episode.sourceUrl}</span>
          </a>
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
                    {topic}
                  </li>
                ))}
              </ul>
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
          <SynthesizeAudioButton episodeId={episode.id} />
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
            currentTime={currentTime}
            onSeek={episode.audioUrl ? (time) => playerRef.current?.seekTo(time) : undefined}
            onMisreadingReport={openScriptLineReport}
          />
        </section>
      )}

      {/* 元記事 */}
      {hasArticles && (
        <section id="articles" className="scroll-mt-20">
          <h2 className="mb-2 px-1 text-sm font-semibold text-slate-900">元記事</h2>
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
