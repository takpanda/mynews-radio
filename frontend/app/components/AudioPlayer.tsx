'use client'

import { useState, useRef, useEffect } from 'react'

interface Props {
  src: string
  title: string
  onTimeUpdate?: (currentTime: number) => void
  externalAudioRef?: React.RefObject<HTMLAudioElement>
}

const SPEEDS = [1.0, 1.25, 1.5]

function formatTime(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

export default function AudioPlayer({ src, title, onTimeUpdate, externalAudioRef }: Props) {
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

  const togglePlay = async () => {
    const audio = audioRef.current
    if (!audio) return
    if (isPlaying) {
      audio.pause()
      setIsPlaying(false)
    } else {
      await audio.play()
      setIsPlaying(true)
    }
  }

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

  return (
    <div className="bg-white rounded-2xl shadow-md p-4">
      <audio ref={audioRef} src={src} preload="metadata" />

      <div className="flex items-center gap-4 mb-3">
        <button
          onClick={togglePlay}
          className="w-14 h-14 bg-blue-500 hover:bg-blue-600 active:bg-blue-700 rounded-full flex items-center justify-center text-white text-2xl transition-colors flex-shrink-0"
          aria-label={isPlaying ? '停止' : '再生'}
        >
          {isPlaying ? '⏸' : '▶'}
        </button>
        <span className="text-sm text-gray-500 tabular-nums">
          {formatTime(currentTime)} / {formatTime(duration)}
        </span>
      </div>

      <input
        type="range"
        min={0}
        max={duration || 0}
        step={0.5}
        value={currentTime}
        onChange={handleSeek}
        className="w-full h-2 accent-blue-500 mb-4 cursor-pointer"
        aria-label="シーク"
      />

      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          {SPEEDS.map((s) => (
            <button
              key={s}
              onClick={() => handleSpeedChange(s)}
              className={`px-3 py-1 rounded-full text-sm font-medium transition-colors ${
                speed === s
                  ? 'bg-blue-500 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200 active:bg-gray-300'
              }`}
            >
              {s}x
            </button>
          ))}
        </div>
        <a
          href={src}
          download={`${title}.mp3`}
          className="flex items-center gap-1 px-3 py-1 rounded-full text-sm font-medium bg-gray-100 text-gray-600 hover:bg-gray-200 active:bg-gray-300 transition-colors"
          aria-label="音声をダウンロード"
        >
          ↓ DL
        </a>
      </div>
    </div>
  )
}
