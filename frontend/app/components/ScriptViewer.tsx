'use client'

import { useEffect, useRef } from 'react'
import type { ScriptLine } from '../lib/api'
import { SECTION_LABEL } from '../lib/chapters'

interface Props {
  lines: ScriptLine[]
  currentTime?: number
  onSeek?: (time: number) => void
  onMisreadingReport?: (line: ScriptLine) => void
}

interface SectionGroup {
  section: string
  lines: Array<{ line: ScriptLine; globalIndex: number }>
}

const SPEAKER_META = {
  male: {
    label: 'MC（男性）',
    align: 'justify-start',
    bubble: 'bg-sky-50 text-slate-800 rounded-tl-md',
    // 色を識別できない場合でも判別できるよう、色つきリングに加えて濃色の輪郭を重ねる
    activeBubble: 'ring-2 ring-sky-300 ring-offset-2 outline outline-2 outline-slate-900',
    badge: 'text-sky-700',
    // 話者アイコン（実写）: 丸型トリミングで女性（角丸四角形）と形状でも区別
    icon: '/images/speakers/mc-male.jpg',
    iconShape: 'rounded-full border border-sky-300',
  },
  female: {
    label: 'MC（女性）',
    align: 'justify-end',
    bubble: 'bg-rose-50 text-slate-800 rounded-tr-md',
    activeBubble: 'ring-2 ring-rose-300 ring-offset-2 outline outline-2 outline-slate-900',
    badge: 'text-rose-700',
    icon: '/images/speakers/mc-female.jpg',
    iconShape: 'rounded-md border border-rose-300',
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

export default function ScriptViewer({ lines, currentTime, onSeek, onMisreadingReport }: Props) {
  const lineRefs = useRef<(HTMLDivElement | null)[]>([])

  // currentTime=0は「先頭行を再生中」を表す有効な値。停止中（未再生）を表す場合は
  // 呼び出し側がcurrentTimeをundefinedにする想定。
  const activeIndex =
    currentTime !== undefined
      ? findActiveIndex(lines, currentTime)
      : -1

  useEffect(() => {
    if (activeIndex < 0) return
    lineRefs.current[activeIndex]?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [activeIndex])

  if (lines.length === 0) {
    return <p className="py-4 text-center text-sm text-slate-400">台本がありません</p>
  }

  const sections = groupBySection(lines)

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
      {sections.map((section, si) => (
        <div key={si} className={si > 0 ? 'mt-8' : ''}>
          <div className="mb-4 flex items-center gap-3">
            <span className="shrink-0 rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-600">
              {SECTION_LABEL[section.section] ?? section.section}
            </span>
            <span className="h-px flex-1 bg-slate-100" />
          </div>

          <div className="space-y-3">
            {section.lines.map(({ line, globalIndex }) => {
              const isActive = globalIndex === activeIndex
              const canSeek = line.start_time !== undefined && onSeek !== undefined
              const speakerMeta = SPEAKER_META[line.speaker]
              const timeLabel = formatTimeLabel(line.start_time)
              const seekAriaLabel = canSeek
                ? `${speakerMeta.label}${timeLabel ? ` ${timeLabel}` : ''}${isActive ? '（再生中）' : ''}: ${line.text} の位置に移動`
                : undefined
              const handleSeekKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
                if (!canSeek) return
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  onSeek!(line.start_time!)
                }
              }
              return (
                <div
                  key={globalIndex}
                  ref={(el) => { lineRefs.current[globalIndex] = el }}
                  className={`flex items-start gap-1.5 group ${speakerMeta.align === 'justify-end' ? 'flex-row-reverse' : ''}`}
                >
                  <div
                    className={`max-w-none rounded-2xl px-4 py-3 transition sm:max-w-[80%] ${
                      speakerMeta.bubble
                    } ${canSeek ? 'cursor-pointer hover:brightness-[0.98] focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:ring-offset-2' : ''} ${
                      isActive ? speakerMeta.activeBubble : ''
                    }`}
                    onClick={() => canSeek && onSeek!(line.start_time!)}
                    onKeyDown={canSeek ? handleSeekKeyDown : undefined}
                    role={canSeek ? 'button' : undefined}
                    tabIndex={canSeek ? 0 : undefined}
                    aria-label={seekAriaLabel}
                    aria-current={isActive ? 'true' : undefined}
                  >
                    <div className="mb-1 flex items-center justify-between gap-3 text-[11px]">
                      <span className={`flex items-center gap-1.5 font-medium ${speakerMeta.badge}`}>
                        <span
                          aria-hidden="true"
                          className={`h-6 w-6 shrink-0 overflow-hidden ${speakerMeta.iconShape}`}
                        >
                          <img
                            src={speakerMeta.icon}
                            alt=""
                            className="h-full w-full object-cover"
                          />
                        </span>
                        {speakerMeta.label}
                      </span>
                      <span className="flex items-center gap-1.5 text-slate-400">
                        {isActive && (
                          <span className="flex items-center gap-1 font-medium text-emerald-600">
                            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
                            再生中
                          </span>
                        )}
                        {timeLabel && <span className="tabular-nums">{timeLabel}</span>}
                      </span>
                    </div>
                    <p className="text-sm leading-7">{line.text}</p>
                  </div>
                  {onMisreadingReport && (
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); onMisreadingReport(line) }}
                      className="flex shrink-0 items-center justify-center rounded-full text-slate-500 transition hover:bg-slate-100 hover:text-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300 min-h-[44px] min-w-[44px]"
                      aria-label={`この行を報告: ${line.text.slice(0, 30)}`}
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
                        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                        <line x1="12" y1="9" x2="12" y2="13" />
                        <line x1="12" y1="17" x2="12.01" y2="17" />
                      </svg>
                    </button>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
