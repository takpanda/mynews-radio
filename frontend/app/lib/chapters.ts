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
  const chapters: Chapter[] = []
  const seenSections = new Set<string>()
  for (const line of script.lines) {
    // つなぎトークは章にしない。同じセクションの再登場もスキップして章数を絞る
    if (line.section === 'transition') continue
    if (seenSections.has(line.section)) continue
    seenSections.add(line.section)
    if (typeof line.start_time === 'number') {
      chapters.push({
        label: SECTION_LABEL[line.section] ?? line.section,
        startTime: line.start_time,
      })
    }
  }
  // 1件だけでは章として意味がないため出さない
  return chapters.length >= 2 ? chapters : []
}
