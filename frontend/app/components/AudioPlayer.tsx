'use client'

import { useState, useRef, useEffect, useCallback } from 'react'

interface Props {
  src: string
  title: string
  onTimeUpdate?: (currentTime: number) => void
  externalAudioRef?: React.RefObject<HTMLAudioElement | null>
  compact?: boolean
}

const SPEEDS = [1.0, 1.25, 1.5]

function formatTime(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

export default function AudioPlayer({ src, title, onTimeUpdate, externalAudioRef, compact }: Props) {
  const internalRef = useRef<HTMLAudioElement>(null)
  const audioRef = externalAudioRef ?? internalRef
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [speed, setSpeed] = useState(1.0)

  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return

    const handleTimeUpdate = () => {
      setCurrentTime(audio.currentTime)
      onTimeUpdate?.(audio.currentTime)
    }
    const onDurationChange = () => setDuration(audio.duration || 0)
    const onEnded = () => setIsPlaying(false)

    audio.addEventListener('timeupdate', handleTimeUpdate)
    audio.addEventListener('durationchange', onDurationChange)
    audio.addEventListener('loadedmetadata', onDurationChange)
    audio.addEventListener('ended', onEnded)

    return () => {
      audio.removeEventListener('timeupdate', handleTimeUpdate)
      audio.removeEventListener('durationchange', onDurationChange)
      audio.removeEventListener('loadedmetadata', onDurationChange)
      audio.removeEventListener('ended', onEnded)
    }
  }, [])

  const togglePlay = useCallback(async () => {
    const audio = audioRef.current
    if (!audio) return
    if (isPlaying) {
      audio.pause()
      setIsPlaying(false)
    } else {
      await audio.play()
      setIsPlaying(true)
    }
  }, [isPlaying])

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const audio = audioRef.current
    if (!audio) return
    const newTime = parseFloat(e.target.value)
    audio.currentTime = newTime
    setCurrentTime(newTime)
  }

  const handleSpeedChange = (newSpeed: number) => {
    const audio = audioRef.current
    if (!audio) return
    audio.playbackRate = newSpeed
    setSpeed(newSpeed)
  }

  const progressPercent = duration > 0 ? (currentTime / duration) * 100 : 0

  return (
    <>
      <audio ref={audioRef} src={src} preload="metadata" />
      {compact ? (
        <div className="flex h-10 items-center gap-3 px-1">
          <button
            onClick={(e) => { e.stopPropagation(); togglePlay() }}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-800 text-sm text-white shadow-[0_4px_10px_rgba(15,23,42,0.15)] transition-transform hover:scale-[1.02] active:scale-[0.98]"
            aria-label={isPlaying ? '停止' : '再生'}
          >
            {isPlaying ? '⏸' : '▶'}
          </button>
          <p className="min-w-0 flex-1 truncate text-sm font-medium text-slate-800">
            {title}
          </p>
          <div
            className="relative h-1 w-24 shrink-0 cursor-pointer overflow-hidden rounded-full bg-white/40 sm:w-32"
            onClick={(e) => {
              e.stopPropagation()
              const rect = e.currentTarget.getBoundingClientRect()
              const x = e.clientX - rect.left
              const pct = Math.max(0, Math.min(1, x / rect.width))
              if (audioRef.current && duration > 0) {
                audioRef.current.currentTime = pct * duration
              }
            }}
            role="slider"
            aria-label="シーク"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(progressPercent)}
          >
            <div
              className="absolute inset-y-0 left-0 rounded-full bg-slate-700 transition-[width] duration-150"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>
      ) : (
        <div className="rounded-[1.5rem] border border-white/80 bg-[radial-gradient(circle_at_top_left,rgba(148,163,184,0.16),transparent_30%),linear-gradient(180deg,rgba(255,255,255,0.98),rgba(245,247,250,0.95))] p-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.88),0_14px_30px_rgba(15,23,42,0.05)] sm:p-5">
          <div className="mb-4 flex items-start justify-between gap-4">
            <div className="min-w-0">
              <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">
                Now Playing
              </p>
              <p className="mt-2 truncate text-sm font-medium text-slate-800 sm:text-base">
                {title}
              </p>
            </div>
            <span className="shrink-0 rounded-full border border-slate-200/80 bg-white/85 px-3 py-1 text-sm text-slate-500 shadow-[inset_0_1px_0_rgba(255,255,255,0.9)] tabular-nums">
              {formatTime(currentTime)} / {formatTime(duration)}
            </span>
          </div>

          <div className="flex items-center gap-4">
            <button
              onClick={togglePlay}
              className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-[linear-gradient(135deg,#0f172a,#334155)] text-2xl text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.12),0_10px_24px_rgba(15,23,42,0.18)] transition-transform transition-colors hover:scale-[1.02] hover:bg-[linear-gradient(135deg,#111827,#3f4d63)] active:scale-[0.98]"
              aria-label={isPlaying ? '停止' : '再生'}
            >
              {isPlaying ? '⏸' : '▶'}
            </button>

            <div className="flex-1">
              <input
                type="range"
                min={0}
                max={duration || 0}
                step={0.5}
                value={currentTime}
                onChange={handleSeek}
                className="h-2 w-full cursor-pointer accent-slate-700"
                aria-label="シーク"
              />

              <div className="mt-3 flex items-center justify-between gap-3">
                <div className="flex flex-wrap gap-2">
                  {SPEEDS.map((s) => (
                    <button
                      key={s}
                      onClick={() => handleSpeedChange(s)}
                      className={`rounded-full px-3 py-1.5 text-sm font-medium transition-colors ${
                        speed === s
                          ? 'bg-slate-800 text-white shadow-[0_8px_18px_rgba(15,23,42,0.12)]'
                          : 'border border-slate-200/80 bg-white/80 text-slate-600 hover:border-slate-300 hover:bg-white'
                      }`}
                    >
                      {s}x
                    </button>
                  ))}
                </div>

                <a
                  href={src}
                  download={`${title}.mp3`}
                  className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-slate-800 text-white shadow-[0_10px_24px_rgba(15,23,42,0.16)] transition-transform transition-colors hover:scale-[1.02] hover:bg-slate-700 active:scale-[0.98]"
                  aria-label="音声をダウンロード"
                  title="音声をダウンロード"
                >
                  <svg
                    aria-hidden="true"
                    viewBox="0 0 24 24"
                    className="h-4.5 w-4.5"
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
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
