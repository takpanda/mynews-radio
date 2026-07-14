import type { Script } from './api'
import type { PlaybackContext } from '../components/MisreadingReportForm'

export interface DetailEpisode {
  id: number
  audioUrl: string | null
  generationPhase?: string
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

export function buildPlaybackReportContext(
  episode: DetailEpisode,
  script: Script | null,
  currentTime: number,
): PlaybackContext {
  const currentLine = findCurrentLine(script?.lines ?? [], currentTime)
  const lineArticleId = currentLine?.article_id ?? null
  const hasTargetSentence = Boolean(currentLine?.text?.trim())
  return {
    episodeId: episode.id,
    articleId: lineArticleId,
    generationId: null,
    playbackPosition: currentTime > 0 ? currentTime : null,
    targetSentence: hasTargetSentence ? currentLine!.text : '',
    allowEditTarget: !hasTargetSentence,
    needsGenerationId: true,
  }
}

export function buildArticleReportContext(
  episodeId: number,
  articleId: number,
): PlaybackContext {
  return {
    episodeId,
    articleId,
    generationId: null,
    playbackPosition: null,
    targetSentence: '',
    allowEditTarget: true,
    needsGenerationId: false,
  }
}
