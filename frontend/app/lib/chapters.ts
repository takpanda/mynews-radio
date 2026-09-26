import type { Script } from './api'

export interface Chapter {
  label: string
  startTime: number
}

export const SECTION_LABEL: Record<string, string> = {
  intro: 'オープニング',
  news: 'ニュース',
  discussion: '討論',
  transition: 'つなぎ',
  outro: 'エンディング',
}

export function buildChapters(script: Script | null): Chapter[] {
  if (!script) return []
  const segmentLabels = new Map((script.segments ?? []).map((segment) => [segment.id, segment.label]))
  const chapters: Chapter[] = []
  const seenKeys = new Set<string>()
  for (const line of script.lines) {
    // つなぎトークは章にしない。同じセクション（または同じセグメント）の再登場もスキップして章数を絞る
    if (line.section === 'transition') continue
    // segmentがあればID単位で章を分ける（同じkindでも別セグメントなら別章）。旧台本はsection名で判定する
    const key = line.segment ?? line.section
    if (seenKeys.has(key)) continue
    seenKeys.add(key)
    if (typeof line.start_time === 'number') {
      const label = line.segment ? segmentLabels.get(line.segment) ?? SECTION_LABEL[line.section] ?? line.section : SECTION_LABEL[line.section] ?? line.section
      chapters.push({
        label,
        startTime: line.start_time,
      })
    }
  }
  // 1件だけでは章として意味がないため出さない
  return chapters.length >= 2 ? chapters : []
}
