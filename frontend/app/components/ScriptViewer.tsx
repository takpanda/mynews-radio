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
    <div className="space-y-1">
      {sections.map((section, si) => (
        <div key={si}>
          <div className="text-center my-4">
            <span className="text-xs text-gray-400 bg-gray-100 px-3 py-1 rounded-full">
              {SECTION_LABEL[section.section] ?? section.section}
            </span>
          </div>
          <div className="space-y-3">
            {section.lines.map(({ line, globalIndex }) => {
              const isActive = globalIndex === activeIndex
              const canSeek = line.start_time !== undefined && onSeek !== undefined
              return (
                <div
                  key={globalIndex}
                  ref={(el) => { lineRefs.current[globalIndex] = el }}
                  className={`flex ${line.speaker === 'female' ? 'justify-end' : 'justify-start'}`}
                  onClick={() => canSeek && onSeek!(line.start_time!)}
                >
                  <div
                    className={`max-w-[80%] rounded-2xl px-4 py-3 transition-all duration-300 ${
                      canSeek ? 'cursor-pointer' : ''
                    } ${
                      line.speaker === 'male'
                        ? `bg-blue-100 text-blue-900 rounded-tl-sm ${isActive ? 'ring-2 ring-blue-400 bg-blue-200' : 'hover:bg-blue-200'}`
                        : `bg-pink-100 text-pink-900 rounded-tr-sm ${isActive ? 'ring-2 ring-pink-400 bg-pink-200' : 'hover:bg-pink-200'}`
                    }`}
                  >
                    <p className="text-xs font-semibold mb-1 opacity-60">
                      {line.speaker === 'male' ? 'MC（男性）' : 'MC（女性）'}
                    </p>
                    <p className="text-sm leading-relaxed">{line.text}</p>
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
