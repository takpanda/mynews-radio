import type { Script } from './api'

export interface PlaybackContext {
  episodeId: number
  articleId: number | null
  generationId: string | null
  playbackPosition: number | null
  targetSentence: string
  allowEditTarget?: boolean
  needsGenerationId?: boolean
}

interface DetailEpisode {
  id: number
  audioUrl: string | null
  generationPhase?: string
}

interface EpisodeItem {
  article_id: number | null
  audio_generation_id?: string | null
}

export function findCurrentLine(lines: Script['lines'], currentTime: number): Script['lines'][number] | null {
  if (!lines || lines.length === 0) return null
  let active: Script['lines'][number] | null = null
  for (const line of lines) {
    if (line.start_time !== undefined && line.start_time <= currentTime) {
      active = line
    }
  }
  return active
}

function findGenerationId(articleId: number | null, items: EpisodeItem[]): string | null {
  if (articleId === null) return null
  const item = items.find((it) => it.article_id === articleId)
  return item?.audio_generation_id ?? null
}

export function buildPlaybackReportContext(
  episode: DetailEpisode,
  script: Script | null,
  items: EpisodeItem[],
  currentTime: number,
): PlaybackContext {
  const currentLine = findCurrentLine(script?.lines ?? [], currentTime)
  const lineArticleId = currentLine?.article_id ?? null
  const hasTargetSentence = Boolean(currentLine?.text?.trim())
  const generationId = findGenerationId(lineArticleId, items)
  return {
    episodeId: episode.id,
    articleId: lineArticleId,
    generationId,
    playbackPosition: currentTime > 0 ? currentTime : null,
    targetSentence: hasTargetSentence ? currentLine!.text : '',
    allowEditTarget: !hasTargetSentence,
  }
}

export function buildArticleReportContext(
  episodeId: number,
  articleId: number,
  items: EpisodeItem[],
): PlaybackContext {
  const generationId = findGenerationId(articleId, items)
  return {
    episodeId,
    articleId,
    generationId,
    playbackPosition: null,
    targetSentence: '',
    allowEditTarget: true,
  }
}
