'use client'

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { Chapter } from '../lib/chapters'

export interface PlayerHandle {
  seekTo: (time: number) => void
}

interface Props {
  audioUrl: string
  title: string
  durationSeconds?: number
  chapters?: Chapter[]
  onTimeUpdate?: (time: number) => void
  onMisreadingReport?: () => void
}

const SPEEDS = [1.0, 1.25, 1.5]

function formatTime(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function PlayIcon({ className }: { className: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className={className} fill="currentColor">
      <path d="M8 5.5v13a1 1 0 0 0 1.52.86l10.2-6.5a1 1 0 0 0 0-1.7L9.52 4.63A1 1 0 0 0 8 5.5Z" />
    </svg>
  )
}

function PauseIcon({ className }: { className: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className={className} fill="currentColor">
      <rect x="7" y="5" width="3.5" height="14" rx="1" />
      <rect x="13.5" y="5" width="3.5" height="14" rx="1" />
    </svg>
  )
}

/**
 * ヒーロースタイルの音声プレーヤー。
 * コントロール一式とチャプターチップに加えて、プレーヤー本体が画面外に
 * スクロールしたときだけ画面下に現れるミニプレーヤーを描画する。
 */
const EpisodeAudioPlayer = forwardRef<PlayerHandle, Props>(function EpisodeAudioPlayer(
  { audioUrl, title, durationSeconds = 0, chapters = [], onTimeUpdate, onMisreadingReport },
  ref,
) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(durationSeconds)
  const [speed, setSpeed] = useState(1.0)
  const [containerVisible, setContainerVisible] = useState(true)
  const [menuOpen, setMenuOpen] = useState(false)

  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return

    const handleTimeUpdate = () => {
      setCurrentTime(audio.currentTime)
      onTimeUpdate?.(audio.currentTime)
    }
    const onDurationChange = () => {
      if (isFinite(audio.duration) && audio.duration > 0) setDuration(audio.duration)
    }
    const onPlay = () => setIsPlaying(true)
    const onPause = () => setIsPlaying(false)

    audio.addEventListener('timeupdate', handleTimeUpdate)
    audio.addEventListener('durationchange', onDurationChange)
    audio.addEventListener('loadedmetadata', onDurationChange)
    audio.addEventListener('play', onPlay)
    audio.addEventListener('pause', onPause)
    audio.addEventListener('ended', onPause)

    return () => {
      audio.removeEventListener('timeupdate', handleTimeUpdate)
      audio.removeEventListener('durationchange', onDurationChange)
      audio.removeEventListener('loadedmetadata', onDurationChange)
      audio.removeEventListener('play', onPlay)
      audio.removeEventListener('pause', onPause)
      audio.removeEventListener('ended', onPause)
    }
  }, [onTimeUpdate])

  useEffect(() => {
    const el = containerRef.current
    if (!el || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(
      ([entry]) => setContainerVisible(entry.isIntersecting),
      { threshold: 0 },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    if (!menuOpen) return
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [menuOpen])

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
    onTimeUpdate?.(audio.currentTime)
  }, [onTimeUpdate])

  useImperativeHandle(ref, () => ({ seekTo }), [seekTo])

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

  const progressPercent = duration > 0 ? (currentTime / duration) * 100 : 0
  const showMiniPlayer = !containerVisible && (isPlaying || currentTime > 0)

  return (
    <>
      <div ref={containerRef}>
        <audio ref={audioRef} src={audioUrl} preload="metadata" />

        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={togglePlay}
            className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-sky-600 text-white shadow-md transition hover:bg-sky-500 active:scale-95"
            aria-label={isPlaying ? '一時停止' : '再生'}
          >
            {isPlaying ? (
              <PauseIcon className="h-6 w-6" />
            ) : (
              <PlayIcon className="ml-0.5 h-6 w-6" />
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
                  href={audioUrl}
                  download={`${title}.mp3`}
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

                {onMisreadingReport && (
                  <div ref={menuRef} className="relative">
                    <button
                      type="button"
                      onClick={() => setMenuOpen((v) => !v)}
                      className="rounded-full p-1.5 text-slate-500 transition hover:bg-slate-100 hover:text-slate-800"
                      aria-label="その他"
                      aria-haspopup="true"
                      aria-expanded={menuOpen}
                    >
                      <svg
                        aria-hidden="true"
                        viewBox="0 0 24 24"
                        className="h-4 w-4"
                        fill="currentColor"
                      >
                        <circle cx="12" cy="5.5" r="1.5" />
                        <circle cx="12" cy="12" r="1.5" />
                        <circle cx="12" cy="18.5" r="1.5" />
                      </svg>
                    </button>
                    {menuOpen && (
                      <div
                        className="absolute right-0 top-full z-20 mt-1 min-w-40 rounded-xl border border-slate-200 bg-white py-1 shadow-lg"
                        role="menu"
                      >
                        <button
                          type="button"
                          role="menuitem"
                          onClick={() => {
                            setMenuOpen(false)
                            onMisreadingReport()
                          }}
                          className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm text-slate-700 transition hover:bg-slate-50"
                        >
                          <svg
                            aria-hidden="true"
                            viewBox="0 0 24 24"
                            className="h-4 w-4 text-slate-400"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                          >
                            <path d="M12 20h9" />
                            <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
                          </svg>
                          読み間違いを報告
                        </button>
                      </div>
                    )}
                  </div>
                )}
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
      </div>

      {/* 画面下ミニプレーヤー */}
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
              <PauseIcon className="h-4 w-4" />
            ) : (
              <PlayIcon className="ml-0.5 h-4 w-4" />
            )}
          </button>
          <p className="min-w-0 flex-1 truncate text-sm text-slate-700">再生中：{title}</p>
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
    </>
  )
})

export default EpisodeAudioPlayer
