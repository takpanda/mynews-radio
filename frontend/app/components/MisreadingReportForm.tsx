'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { submitMisreadingReport } from '../lib/misreading-report'

export interface PlaybackContext {
  episodeId: number
  articleId: number | null
  generationId: string | null
  playbackPosition: number | null
  targetSentence: string
  allowEditTarget?: boolean
  needsGenerationId?: boolean
}

interface Props {
  playbackContext: PlaybackContext | null
  onClose: () => void
}

const MAX_TARGET = 2000
const MAX_INCORRECT = 500
const MAX_CORRECT = 500
const MAX_NOTES = 2000

export default function MisreadingReportForm({ playbackContext, onClose }: Props) {
  const [targetSentence, setTargetSentence] = useState(playbackContext?.targetSentence ?? '')
  const [incorrectReading, setIncorrectReading] = useState('')
  const [correctReading, setCorrectReading] = useState('')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const backdropRef = useRef<HTMLDivElement>(null)

  const isFromPlayback = playbackContext !== null
  const showReadonlyTarget = isFromPlayback && !playbackContext.allowEditTarget
  const blockedByGenerationId = isFromPlayback && !!playbackContext.needsGenerationId && !playbackContext.generationId

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !submitting) onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose, submitting])

  const validate = useCallback((): boolean => {
    const errs: Record<string, string> = {}
    if (!targetSentence.trim()) {
      errs.target_sentence = showReadonlyTarget
        ? '対象文が取得できませんでした'
        : '対象の箇所を入力してください'
    } else if (targetSentence.length > MAX_TARGET) {
      errs.target_sentence = `対象文は${MAX_TARGET}文字以内で入力してください`
    }
    if (!correctReading.trim()) {
      errs.correct_reading = '正しい読みを入力してください'
    } else if (correctReading.length > MAX_CORRECT) {
      errs.correct_reading = `正しい読みは${MAX_CORRECT}文字以内で入力してください`
    }
    if (incorrectReading.length > MAX_INCORRECT) {
      errs.incorrect_reading = `誤読内容は${MAX_INCORRECT}文字以内で入力してください`
    }
    if (Object.keys(errs).length > 0) {
      setSubmitError(errs[Object.keys(errs)[0]])
      return false
    }
    setSubmitError(null)
    return true
  }, [targetSentence, correctReading, incorrectReading, showReadonlyTarget])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (blockedByGenerationId) return
    if (!validate()) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      const notesParts: string[] = []
      if (incorrectReading.trim()) {
        notesParts.push(`誤読内容: ${incorrectReading.trim()}`)
      }
      if (notes.trim()) {
        notesParts.push(notes.trim())
      }
      await submitMisreadingReport({
        episode_id: playbackContext?.episodeId ?? 0,
        target_text: targetSentence.trim(),
        correct_reading: correctReading.trim(),
        article_id: playbackContext?.articleId ?? null,
        audio_generation_id: playbackContext?.generationId ?? null,
        playback_position: playbackContext?.playbackPosition ?? null,
        notes: notesParts.length > 0 ? notesParts.join('\n') : undefined,
      })
      onClose()
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : '送信に失敗しました')
    } finally {
      setSubmitting(false)
    }
  }

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === backdropRef.current && !submitting) {
      onClose()
    }
  }

  return (
    <div
      ref={backdropRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onClick={handleBackdropClick}
    >
      <div
        className="flex w-full max-w-lg flex-col rounded-2xl border border-slate-200 bg-white shadow-xl"
        role="dialog"
        aria-modal="true"
        aria-label="読み間違いを報告"
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <h2 className="text-base font-semibold text-slate-900">読み間違いを報告</h2>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="flex h-8 w-8 items-center justify-center rounded-full text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 disabled:opacity-50"
            aria-label="閉じる"
          >
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              className="h-4.5 w-4.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            >
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>

        {showReadonlyTarget && (
          <div className="mx-5 mt-4 rounded-xl border border-sky-100 bg-sky-50 px-4 py-3">
            <p className="text-xs font-medium text-sky-700">再生中に聞こえた箇所</p>
            <p className="mt-1 text-sm leading-6 text-sky-900">
              {playbackContext!.targetSentence}
            </p>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4 overflow-y-auto px-5 py-4">
          {(!isFromPlayback || playbackContext?.allowEditTarget) && (
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-500">
                対象の箇所 <span className="text-red-500">*</span>
              </label>
              <textarea
                value={targetSentence}
                onChange={(e) => setTargetSentence(e.target.value)}
                maxLength={MAX_TARGET}
                rows={3}
                className="w-full resize-none rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-900 transition focus:border-sky-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100"
                placeholder="読み間違いがあった箇所を入力してください"
              />
              <p className="mt-0.5 text-right text-[11px] text-slate-400">
                {targetSentence.length}/{MAX_TARGET}
              </p>
            </div>
          )}

          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">
              誤って読まれた内容
            </label>
            <input
              type="text"
              value={incorrectReading}
              onChange={(e) => setIncorrectReading(e.target.value)}
              maxLength={MAX_INCORRECT}
              className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-900 transition focus:border-sky-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100"
              placeholder="例: じんこうえいせい と読んでいた"
            />
            <p className="mt-0.5 text-right text-[11px] text-slate-400">
              {incorrectReading.length}/{MAX_INCORRECT}
            </p>
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">
              正しい読み <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={correctReading}
              onChange={(e) => setCorrectReading(e.target.value)}
              maxLength={MAX_CORRECT}
              className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-900 transition focus:border-sky-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100"
              placeholder="例: じんこうちのう"
            />
            <p className="mt-0.5 text-right text-[11px] text-slate-400">
              {correctReading.length}/{MAX_CORRECT}
            </p>
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">補足</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              maxLength={MAX_NOTES}
              rows={3}
              className="w-full resize-none rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-900 transition focus:border-sky-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100"
              placeholder="必要に応じて補足情報を入力"
            />
            <p className="mt-0.5 text-right text-[11px] text-slate-400">
              {notes.length}/{MAX_NOTES}
            </p>
          </div>

          {blockedByGenerationId && (
            <div className="rounded-xl border border-sky-200 bg-sky-50 p-3 text-sm text-sky-800">
              <p className="font-medium">音声データの生成が完了していません</p>
              <p className="mt-1 text-xs text-sky-600">
                再生中の読み間違いを報告するには、音声データの生成が完了している必要があります。しばらく待ってから再度お試しください。
              </p>
            </div>
          )}

          {submitError && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              <p>{submitError}</p>
              <p className="mt-1 text-xs text-amber-600">時間をおいてもう一度お試しください。</p>
            </div>
          )}

          <div className="flex items-center justify-end gap-2 border-t border-slate-100 pt-4">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
            >
              キャンセル
            </button>
            <button
              type="submit"
              disabled={submitting || blockedByGenerationId}
              className="inline-flex items-center gap-1.5 rounded-full bg-sky-600 px-5 py-2 text-sm font-medium text-white transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting && (
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              )}
              送信する
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
