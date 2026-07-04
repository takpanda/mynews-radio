'use client'

import { useState, useRef, useEffect, useMemo, useCallback } from 'react'
import Link from 'next/link'
import type { EpisodeListItem } from '../lib/api'
import SynthesizeAudioButton from './SynthesizeAudioButton'

export interface Chapter {
  label: string
  startTime: number
}

export interface HeroEpisode {
  id: number
  title: string
  subtitle: string
  dateLabel: string
  isCommentary: boolean
  sourceUrl: string | null
  audioUrl: string | null
  durationSeconds: number
}

interface Props {
  latest: HeroEpisode | null
  chapters: Chapter[]
  episodes: EpisodeListItem[]
}

const SPEEDS = [1.0, 1.25, 1.5]

type CategoryKey = 'all' | 'tech' | 'general' | 'commentary'

const CATEGORY_TABS: Array<{ key: CategoryKey; label: string }> = [
  { key: 'all', label: 'すべて' },
  { key: 'tech', label: 'テック' },
  { key: 'general', label: '一般' },
  { key: 'commentary', label: '解説' },
]

const INITIAL_VISIBLE_COUNT = 10

function categorize(ep: EpisodeListItem): Exclude<CategoryKey, 'all'> {
  if (ep.type === 'commentary') return 'commentary'
  if ((ep.title || '').includes('テック')) return 'tech'
  return 'general'
}

function formatTime(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function monthLabel(dateStr: string): string {
  const [y, m] = dateStr.slice(0, 10).split('-')
  if (!y || !m) return dateStr
  return `${y}年${Number(m)}月`
}

function dayLabel(dateStr: string): string {
  const [, m, d] = dateStr.slice(0, 10).split('-')
  if (!m || !d) return dateStr
  return `${Number(m)}月${Number(d)}日`
}

function durationLabel(seconds: number): string {
  if (!seconds || seconds <= 0) return ''
  return `${Math.max(1, Math.round(seconds / 60))}分`
}

export default function HomeShell({ latest, chapters, episodes }: Props) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const heroRef = useRef<HTMLElement>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(latest?.durationSeconds ?? 0)
  const [speed, setSpeed] = useState(1.0)
  const [heroVisible, setHeroVisible] = useState(true)

  const [category, setCategory] = useState<CategoryKey>('all')
  const [query, setQuery] = useState('')
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE_COUNT)

  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return

    const onTimeUpdate = () => setCurrentTime(audio.currentTime)
    const onDurationChange = () => {
      if (isFinite(audio.duration) && audio.duration > 0) setDuration(audio.duration)
    }
    const onPlay = () => setIsPlaying(true)
    const onPause = () => setIsPlaying(false)
    const onEnded = () => setIsPlaying(false)

    audio.addEventListener('timeupdate', onTimeUpdate)
    audio.addEventListener('durationchange', onDurationChange)
    audio.addEventListener('loadedmetadata', onDurationChange)
    audio.addEventListener('play', onPlay)
    audio.addEventListener('pause', onPause)
    audio.addEventListener('ended', onEnded)

    return () => {
      audio.removeEventListener('timeupdate', onTimeUpdate)
      audio.removeEventListener('durationchange', onDurationChange)
      audio.removeEventListener('loadedmetadata', onDurationChange)
      audio.removeEventListener('play', onPlay)
      audio.removeEventListener('pause', onPause)
      audio.removeEventListener('ended', onEnded)
    }
  }, [])

  useEffect(() => {
    const el = heroRef.current
    if (!el || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(
      ([entry]) => setHeroVisible(entry.isIntersecting),
      { threshold: 0.2 },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const togglePlay = useCallback(async () => {
    const audio = audioRef.current
    if (!audio) return
    if (audio.paused) {
      await audio.play()
    } else {
      audio.pause()
    }
  }, [])

  const seekTo = useCallback((time: number) => {
    const audio = audioRef.current
    if (!audio) return
    audio.currentTime = Math.max(0, time)
    setCurrentTime(audio.currentTime)
  }, [])

  const skip = useCallback(
    (delta: number) => {
      const audio = audioRef.current
      if (!audio) return
      seekTo(audio.currentTime + delta)
    },
    [seekTo],
  )

  const cycleSpeed = useCallback(() => {
    const audio = audioRef.current
    const next = SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length]
    if (audio) audio.playbackRate = next
    setSpeed(next)
  }, [speed])

  const activeChapterIndex = useMemo(() => {
    let active = -1
    chapters.forEach((chapter, index) => {
      if (currentTime >= chapter.startTime) active = index
    })
    return active
  }, [chapters, currentTime])

  const filteredEpisodes = useMemo(() => {
    const q = query.trim().toLowerCase()
    return episodes.filter((ep) => {
      if (category !== 'all' && categorize(ep) !== category) return false
      if (!q) return true
      return (
        (ep.title || '').toLowerCase().includes(q) ||
        (ep.subtitle || '').toLowerCase().includes(q)
      )
    })
  }, [episodes, category, query])

  const visibleEpisodes = filteredEpisodes.slice(0, visibleCount)

  const groupedByMonth = useMemo(() => {
    const groups: Array<{ month: string; items: EpisodeListItem[] }> = []
    for (const ep of visibleEpisodes) {
      const month = monthLabel(ep.date)
      const last = groups.at(-1)
      if (last && last.month === month) {
        last.items.push(ep)
      } else {
        groups.push({ month, items: [ep] })
      }
    }
    return groups
  }, [visibleEpisodes])

  const progressPercent = duration > 0 ? (currentTime / duration) * 100 : 0
  const showMiniPlayer =
    Boolean(latest?.audioUrl) && !heroVisible && (isPlaying || currentTime > 0)

  return (
    <div className="space-y-6">
      {latest?.audioUrl && <audio ref={audioRef} src={latest.audioUrl} preload="metadata" />}

      {/* 最新エピソード（ヒーロープレーヤー） */}
      <section
        ref={heroRef}
        className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"
      >
        {latest ? (
          <>
            <p className="text-xs text-slate-400">最新エピソード ・ {latest.dateLabel}</p>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <Link
                href={`/episodes/${latest.id}`}
                className="text-lg font-semibold leading-snug text-slate-900 transition hover:text-sky-700 sm:text-xl"
              >
                {latest.title || `エピソード #${latest.id}`}
              </Link>
              {latest.isCommentary && (
                <span className="inline-flex items-center rounded-full bg-violet-50 px-2.5 py-0.5 text-xs font-medium text-violet-700">
                  解説
                </span>
              )}
            </div>
            {latest.subtitle && (
              <p className="mt-1 text-sm leading-6 text-slate-500">{latest.subtitle}</p>
            )}

            {latest.audioUrl ? (
              <>
                <div className="mt-5 flex items-center gap-4">
                  <button
                    type="button"
                    onClick={togglePlay}
                    className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-sky-600 text-white shadow-md transition hover:bg-sky-500 active:scale-95"
                    aria-label={isPlaying ? '一時停止' : '再生'}
                  >
                    {isPlaying ? (
                      <svg aria-hidden="true" viewBox="0 0 24 24" className="h-6 w-6" fill="currentColor">
                        <rect x="7" y="5" width="3.5" height="14" rx="1" />
                        <rect x="13.5" y="5" width="3.5" height="14" rx="1" />
                      </svg>
                    ) : (
                      <svg aria-hidden="true" viewBox="0 0 24 24" className="ml-0.5 h-6 w-6" fill="currentColor">
                        <path d="M8 5.5v13a1 1 0 0 0 1.52.86l10.2-6.5a1 1 0 0 0 0-1.7L9.52 4.63A1 1 0 0 0 8 5.5Z" />
                      </svg>
                    )}
                  </button>

                  <div className="min-w-0 flex-1">
                    <input
                      type="range"
                      min={0}
                      max={duration || 0}
                      step={0.5}
                      value={currentTime}
                      onChange={(e) => seekTo(parseFloat(e.target.value))}
                      className="h-1.5 w-full cursor-pointer accent-sky-600"
                      aria-label="シーク"
                    />
                    <div className="mt-1.5 flex items-center justify-between text-xs text-slate-400">
                      <span className="tabular-nums">
                        {formatTime(currentTime)} / {formatTime(duration)}
                      </span>
                      <span className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={() => skip(-15)}
                          className="rounded-full px-2 py-1 font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-800"
                          aria-label="15秒戻す"
                        >
                          -15s
                        </button>
                        <button
                          type="button"
                          onClick={() => skip(30)}
                          className="rounded-full px-2 py-1 font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-800"
                          aria-label="30秒進める"
                        >
                          +30s
                        </button>
                        <button
                          type="button"
                          onClick={cycleSpeed}
                          className="rounded-full px-2 py-1 font-medium tabular-nums text-slate-500 transition hover:bg-slate-100 hover:text-slate-800"
                          aria-label={`再生速度 ${speed}倍`}
                        >
                          {speed}x
                        </button>
                        <a
                          href={latest.audioUrl}
                          download={`${latest.title || `episode-${latest.id}`}.mp3`}
                          className="rounded-full p-1.5 text-slate-500 transition hover:bg-slate-100 hover:text-slate-800"
                          aria-label="音声をダウンロード"
                          title="音声をダウンロード"
                        >
                          <svg
                            aria-hidden="true"
                            viewBox="0 0 24 24"
                            className="h-4 w-4"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="1.9"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          >
                            <path d="M12 4.5v9" />
                            <path d="m8.5 10.5 3.5 3.5 3.5-3.5" />
                            <path d="M5 17.5h14" />
                          </svg>
                        </a>
                      </span>
                    </div>
                  </div>
                </div>

                {chapters.length > 0 && (
                  <div className="mt-4 flex flex-wrap gap-2">
                    {chapters.map((chapter, index) => (
                      <button
                        key={`${chapter.label}-${chapter.startTime}`}
                        type="button"
                        onClick={() => seekTo(chapter.startTime)}
                        className={`rounded-full px-3 py-1 text-xs transition ${
                          index === activeChapterIndex
                            ? 'bg-sky-50 font-medium text-sky-700'
                            : 'border border-slate-200 text-slate-500 hover:border-slate-300 hover:text-slate-800'
                        }`}
                      >
                        {chapter.label}
                        {chapter.startTime > 0 && (
                          <span className="ml-1 tabular-nums opacity-70">
                            {formatTime(chapter.startTime)}
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <div className="mt-5 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-5 text-center text-sm text-slate-500">
                音声ファイルを準備中です
              </div>
            )}
          </>
        ) : (
          <div className="py-10 text-center">
            <p className="text-lg font-semibold text-slate-900">まだエピソードがありません</p>
            <p className="mt-2 text-sm leading-7 text-slate-500">
              右上の「番組を生成」から今日の番組を作成すると、ここに最新エピソードが表示されます。
            </p>
          </div>
        )}
      </section>

      {/* アーカイブ */}
      <section
        id="archive"
        className="scroll-mt-20 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"
      >
        <div className="flex flex-wrap items-center gap-1.5">
          {CATEGORY_TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => {
                setCategory(tab.key)
                setVisibleCount(INITIAL_VISIBLE_COUNT)
              }}
              className={`rounded-full px-3.5 py-1.5 text-xs transition ${
                category === tab.key
                  ? 'bg-slate-900 font-medium text-white'
                  : 'text-slate-500 hover:bg-slate-100 hover:text-slate-800'
              }`}
            >
              {tab.label}
            </button>
          ))}
          <div className="relative ml-auto w-full sm:w-48">
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            >
              <circle cx="11" cy="11" r="7" />
              <path d="m20 20-3.5-3.5" />
            </svg>
            <input
              type="search"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                setVisibleCount(INITIAL_VISIBLE_COUNT)
              }}
              placeholder="検索"
              className="w-full rounded-full border border-slate-200 bg-slate-50 py-1.5 pl-8 pr-3 text-xs text-slate-800 placeholder:text-slate-400 transition focus:border-sky-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100"
              aria-label="エピソードを検索"
            />
          </div>
        </div>

        {filteredEpisodes.length === 0 ? (
          <p className="py-10 text-center text-sm text-slate-400">
            該当するエピソードがありません
          </p>
        ) : (
          <div className="mt-4">
            {groupedByMonth.map((group) => (
              <div key={group.month}>
                <p className="mb-1 mt-4 text-xs text-slate-400 first:mt-0">{group.month}</p>
                <div className="border-t border-slate-100">
                  {group.items.map((ep) => (
                    <div key={ep.id} className="border-b border-slate-100">
                      <Link
                        href={`/episodes/${ep.id}`}
                        className="flex items-center gap-3 px-1 py-2.5 transition hover:bg-slate-50"
                      >
                        <svg
                          aria-hidden="true"
                          viewBox="0 0 24 24"
                          className="h-4 w-4 shrink-0 text-slate-400"
                          fill="currentColor"
                        >
                          <path d="M8 5.5v13a1 1 0 0 0 1.52.86l10.2-6.5a1 1 0 0 0 0-1.7L9.52 4.63A1 1 0 0 0 8 5.5Z" />
                        </svg>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <p className="truncate text-sm text-slate-900">
                              {ep.title || `エピソード #${ep.id}`}
                            </p>
                            {ep.status === 'generating' && (
                              <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">
                                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
                                生成中
                              </span>
                            )}
                          </div>
                          <p className="mt-0.5 text-xs text-slate-400">
                            {dayLabel(ep.date)}
                            {durationLabel(ep.duration) && ` ・ ${durationLabel(ep.duration)}`}
                          </p>
                        </div>
                        {ep.type === 'commentary' && (
                          <span className="shrink-0 rounded-full bg-violet-50 px-2 py-0.5 text-[11px] font-medium text-violet-700">
                            解説
                          </span>
                        )}
                      </Link>
                      {ep.has_script && !ep.audio_url && (
                        <div className="px-1 pb-2.5 pl-8">
                          <SynthesizeAudioButton episodeId={ep.id} compact />
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}

            {filteredEpisodes.length > visibleCount && (
              <button
                type="button"
                onClick={() => setVisibleCount((count) => count + INITIAL_VISIBLE_COUNT)}
                className="mt-1 w-full rounded-lg py-2.5 text-center text-sm text-slate-500 transition hover:bg-slate-50 hover:text-slate-800"
              >
                もっと見る（残り {filteredEpisodes.length - visibleCount} 件）
              </button>
            )}
          </div>
        )}
      </section>

      {/* 画面下ミニプレーヤー */}
      {latest && (
        <div
          className={`fixed inset-x-0 bottom-0 z-30 border-t border-slate-200 bg-white/95 backdrop-blur transition-transform duration-300 ${
            showMiniPlayer ? 'translate-y-0' : 'translate-y-full'
          }`}
          aria-hidden={!showMiniPlayer}
        >
          <div className="mx-auto flex h-14 max-w-3xl items-center gap-3 px-4 sm:px-6">
            <button
              type="button"
              onClick={togglePlay}
              tabIndex={showMiniPlayer ? 0 : -1}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-sky-600 text-white transition hover:bg-sky-500 active:scale-95"
              aria-label={isPlaying ? '一時停止' : '再生'}
            >
              {isPlaying ? (
                <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor">
                  <rect x="7" y="5" width="3.5" height="14" rx="1" />
                  <rect x="13.5" y="5" width="3.5" height="14" rx="1" />
                </svg>
              ) : (
                <svg aria-hidden="true" viewBox="0 0 24 24" className="ml-0.5 h-4 w-4" fill="currentColor">
                  <path d="M8 5.5v13a1 1 0 0 0 1.52.86l10.2-6.5a1 1 0 0 0 0-1.7L9.52 4.63A1 1 0 0 0 8 5.5Z" />
                </svg>
              )}
            </button>
            <p className="min-w-0 flex-1 truncate text-sm text-slate-700">
              再生中：{latest.title || `エピソード #${latest.id}`}
            </p>
            <div
              className="relative h-1 w-24 shrink-0 cursor-pointer overflow-hidden rounded-full bg-slate-200 sm:w-32"
              onClick={(e) => {
                const rect = e.currentTarget.getBoundingClientRect()
                const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
                if (duration > 0) seekTo(pct * duration)
              }}
              role="slider"
              aria-label="シーク"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(progressPercent)}
            >
              <div
                className="absolute inset-y-0 left-0 rounded-full bg-sky-600 transition-[width] duration-150"
                style={{ width: `${progressPercent}%` }}
              />
            </div>
            <span className="hidden shrink-0 text-xs tabular-nums text-slate-400 sm:inline">
              {formatTime(currentTime)} / {formatTime(duration)}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
