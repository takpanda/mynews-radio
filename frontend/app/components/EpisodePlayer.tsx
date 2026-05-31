'use client'

import { useState, useRef } from 'react'
import AudioPlayer from './AudioPlayer'
import ScriptViewer from './ScriptViewer'
import type { Episode, Script } from '../lib/api'

interface Props {
  episode: Episode
  script: Script | null
  audioUrl: string
}

export default function EpisodePlayer({ episode, script, audioUrl }: Props) {
  const [currentTime, setCurrentTime] = useState(0)
  const audioRef = useRef<HTMLAudioElement>(null)

  const handleSeek = (time: number) => {
    if (audioRef.current) {
      audioRef.current.currentTime = time
    }
  }

  return (
    <>
      <section id="player" className="sticky top-0 z-20 mb-8 scroll-mt-24 rounded-[1.75rem] border border-white/80 bg-white/70 p-3 shadow-[0_18px_40px_rgba(15,23,42,0.08)] backdrop-blur sm:p-4">
        <AudioPlayer
          src={audioUrl}
          title={episode.title || `エピソード #${episode.id}`}
          onTimeUpdate={setCurrentTime}
          externalAudioRef={audioRef}
        />
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
