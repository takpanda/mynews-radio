'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import AudioPlayer from './AudioPlayer'
import ScriptViewer from './ScriptViewer'
import type { Episode, Script } from '../lib/api'

interface Props {
  episode: Episode
  script: Script | null
  audioUrl: string
}

function useIsMobile(breakpoint = 640) {
  const [isMobile, setIsMobile] = useState(false)

  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < breakpoint)
    check()
    window.addEventListener('resize', check)
    return () => window.removeEventListener('resize', check)
  }, [breakpoint])

  return isMobile
}

export default function EpisodePlayer({ episode, script, audioUrl }: Props) {
  const [currentTime, setCurrentTime] = useState(0)
  const [expanded, setExpanded] = useState(false)
  const audioRef = useRef<HTMLAudioElement>(null)
  const isMobile = useIsMobile()
  const touchStartY = useRef(0)

  const handleSeek = useCallback((time: number) => {
    if (audioRef.current) {
      audioRef.current.currentTime = time
    }
  }, [])

  const handleExpand = useCallback(() => setExpanded(true), [])
  const handleCollapse = useCallback(() => setExpanded(false), [])

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    touchStartY.current = e.touches[0].clientY
  }, [])

  const handleTouchEnd = useCallback((e: React.TouchEvent) => {
    const dy = e.changedTouches[0].clientY - touchStartY.current
    if (dy > 50) {
      setExpanded(false)
    }
  }, [])

  const compact = isMobile && !expanded

  const sectionClasses = compact
    ? 'max-h-[52px] overflow-hidden rounded-[0.75rem] p-0'
    : isMobile
      ? 'max-h-[600px] rounded-[1.75rem] p-3'
      : 'rounded-[1.75rem] p-3 sm:p-4'

  return (
    <>
      <section
        id="player"
        className={`sticky top-0 z-20 mb-8 scroll-mt-24 border border-white/80 bg-white/70 shadow-[0_18px_40px_rgba(15,23,42,0.08)] backdrop-blur transition-all duration-300 ${sectionClasses}`}
        onTouchStart={expanded ? handleTouchStart : undefined}
        onTouchEnd={expanded ? handleTouchEnd : undefined}
      >
        {isMobile && expanded && (
          <div className="flex justify-center pb-1">
            <button
              onClick={handleCollapse}
              className="flex h-6 w-12 items-center justify-center rounded-full text-slate-400 transition-colors hover:bg-white/40 hover:text-slate-600"
              aria-label="閉じる"
            >
              <svg
                aria-hidden="true"
                viewBox="0 0 24 24"
                className="h-5 w-5"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="m18 15-6-6-6 6" />
              </svg>
            </button>
          </div>
        )}

        <div onClick={compact ? handleExpand : undefined}>
          <AudioPlayer
            src={audioUrl}
            title={episode.title || `エピソード #${episode.id}`}
            onTimeUpdate={setCurrentTime}
            externalAudioRef={audioRef}
            compact={compact}
          />
        </div>
      </section>

      {script && script.lines.length > 0 && (
        <section id="script" className="mb-8 scroll-mt-28">
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-gray-400">
            台本
          </h2>
          <ScriptViewer
            lines={script.lines}
            currentTime={currentTime}
            onSeek={handleSeek}
          />
        </section>
      )}

      {(!script || script.lines.length === 0) && (
        <div className="text-center text-gray-400 py-8 text-sm">台本がありません</div>
      )}
    </>
  )
}
