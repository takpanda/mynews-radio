'use client'

import { useEffect, useRef } from 'react'
import type { ScriptLine } from '../lib/api'

interface Props {
  lines: ScriptLine[]
  currentTime?: number
  onSeek?: (time: number) => void
}

const SECTION_LABEL: Record<string, string> = {
  intro: 'オープニング',
  news: 'ニュース',
  discussion: '注目トピック討論',
  outro: 'エンディング',
}

interface SectionGroup {
  section: string
  lines: Array<{ line: ScriptLine; globalIndex: number }>
}

const SPEAKER_META = {
  male: {
    label: 'MC（男性）',
    align: 'justify-start',
    bubble:
      'bg-[linear-gradient(135deg,rgba(219,234,254,0.98),rgba(239,246,255,0.96))] text-sky-950 shadow-[0_18px_40px_rgba(14,165,233,0.14)] rounded-tl-md border-sky-200/70',
    activeBubble:
      'ring-2 ring-sky-300/90 bg-[linear-gradient(135deg,rgba(186,230,253,1),rgba(224,242,254,0.98))] shadow-[0_24px_50px_rgba(14,165,233,0.22)]',
    hoverBubble: 'hover:-translate-y-0.5 hover:border-sky-300/80 hover:shadow-[0_24px_46px_rgba(14,165,233,0.18)]',
    badge:
      'bg-sky-900/[0.07] text-sky-900 ring-1 ring-inset ring-sky-800/10',
    rail: 'from-sky-200 via-cyan-200 to-transparent',
  },
  female: {
    label: 'MC（女性）',
    align: 'justify-end',
    bubble:
      'bg-[linear-gradient(135deg,rgba(252,231,243,0.98),rgba(253,242,248,0.96))] text-rose-950 shadow-[0_18px_40px_rgba(244,114,182,0.14)] rounded-tr-md border-rose-200/80',
    activeBubble:
      'ring-2 ring-rose-300/90 bg-[linear-gradient(135deg,rgba(251,207,232,1),rgba(253,242,248,0.98))] shadow-[0_24px_50px_rgba(244,114,182,0.2)]',
    hoverBubble: 'hover:-translate-y-0.5 hover:border-rose-300/80 hover:shadow-[0_24px_46px_rgba(244,114,182,0.18)]',
    badge:
      'bg-rose-900/[0.07] text-rose-900 ring-1 ring-inset ring-rose-800/10',
    rail: 'from-rose-200 via-pink-200 to-transparent',
  },
} as const

function formatTimeLabel(seconds?: number): string | null {
  if (seconds === undefined || Number.isNaN(seconds)) return null
  const totalSeconds = Math.max(0, Math.floor(seconds))
  const minutes = Math.floor(totalSeconds / 60)
  const remainSeconds = totalSeconds % 60
  return `${minutes.toString().padStart(2, '0')}:${remainSeconds.toString().padStart(2, '0')}`
}

function groupBySection(lines: ScriptLine[]): SectionGroup[] {
  return lines.reduce<SectionGroup[]>((acc, line, index) => {
    const last = acc[acc.length - 1]
    if (!last || last.section !== line.section) {
      acc.push({ section: line.section, lines: [{ line, globalIndex: index }] })
    } else {
      last.lines.push({ line, globalIndex: index })
    }
    return acc
  }, [])
}

function findActiveIndex(lines: ScriptLine[], currentTime: number): number {
  let active = -1
  for (let i = 0; i < lines.length; i++) {
    const t = lines[i].start_time
    if (t !== undefined && t <= currentTime) {
      active = i
    }
  }
  return active
}

export default function ScriptViewer({ lines, currentTime, onSeek }: Props) {
  const lineRefs = useRef<(HTMLDivElement | null)[]>([])

  const activeIndex =
    currentTime !== undefined && currentTime > 0
      ? findActiveIndex(lines, currentTime)
      : -1

  useEffect(() => {
    if (activeIndex < 0) return
    lineRefs.current[activeIndex]?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [activeIndex])

  if (lines.length === 0) {
    return <p className="text-center text-gray-500 py-4">台本がありません</p>
  }

  const sections = groupBySection(lines)

  return (
    <div className="space-y-6">
      {sections.map((section, si) => (
        <div
          key={si}
          className="relative overflow-hidden rounded-[2rem] border border-white/80 bg-white/75 px-4 py-5 shadow-[0_24px_60px_rgba(15,23,42,0.08)] backdrop-blur sm:px-6 sm:py-6"
        >
          <div className="absolute inset-x-6 top-0 h-px bg-gradient-to-r from-transparent via-slate-200 to-transparent" />
          <div className="mb-5 text-center">
            <span className="inline-flex items-center gap-2 rounded-full border border-amber-200/80 bg-[linear-gradient(135deg,rgba(255,251,235,0.95),rgba(255,247,237,0.95))] px-4 py-1.5 text-[11px] font-semibold tracking-[0.28em] text-amber-700 shadow-sm">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
              {SECTION_LABEL[section.section] ?? section.section}
            </span>
          </div>
          <div className="relative space-y-4 sm:space-y-5">
            {section.lines.map(({ line, globalIndex }) => {
              const isActive = globalIndex === activeIndex
              const canSeek = line.start_time !== undefined && onSeek !== undefined
              const speakerMeta = SPEAKER_META[line.speaker]
              const timeLabel = formatTimeLabel(line.start_time)
              return (
                <div
                  key={globalIndex}
                  ref={(el) => { lineRefs.current[globalIndex] = el }}
                  className={`group relative flex ${speakerMeta.align}`}
                  onClick={() => canSeek && onSeek!(line.start_time!)}
                >
                  <div className={`pointer-events-none absolute top-3 hidden h-[calc(100%-0.75rem)] w-24 bg-gradient-to-r ${speakerMeta.rail} opacity-80 blur-2xl sm:block ${line.speaker === 'female' ? 'right-6' : 'left-6'}`} />
                  <div
                     className={`relative max-w-none rounded-[1.6rem] border px-4 py-4 transition-all duration-300 sm:max-w-[78%] sm:px-5 ${
                      canSeek ? 'cursor-pointer' : ''
                    } ${
                      isActive ? 'scale-[1.01]' : 'scale-100'
                    } ${
                      speakerMeta.bubble
                    } ${
                      isActive ? speakerMeta.activeBubble : speakerMeta.hoverBubble
                    }`}
                  >
                    <div className="mb-2 flex items-center justify-between gap-3">
                      <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-semibold tracking-[0.18em] ${speakerMeta.badge}`}>
                        {speakerMeta.label}
                      </span>
                      {timeLabel && (
                        <span className="shrink-0 rounded-full bg-white/65 px-2.5 py-1 text-[11px] font-medium text-slate-500 ring-1 ring-inset ring-white/70">
                          {timeLabel}
                        </span>
                      )}
                    </div>
                    <p className="text-[15px] leading-8 tracking-[0.01em] sm:text-base">{line.text}</p>
                    {isActive && (
                      <div className="mt-3 flex items-center gap-2 text-[11px] font-medium text-slate-500">
                        <span className="relative flex h-2.5 w-2.5">
                          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-300 opacity-75" />
                          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-400" />
                        </span>
                        再生中
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
