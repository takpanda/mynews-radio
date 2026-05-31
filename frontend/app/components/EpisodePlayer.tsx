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
      <section className="mb-8">
        <AudioPlayer
          src={audioUrl}
          title={episode.title || `エピソード #${episode.id}`}
          onTimeUpdate={setCurrentTime}
          externalAudioRef={audioRef}
        />
      </section>

      {script && script.lines.length > 0 && (
        <section className="mb-8">
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">
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
