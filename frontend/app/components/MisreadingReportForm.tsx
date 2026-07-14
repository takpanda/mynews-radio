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

type FormErrors = Partial<Record<'target_sentence' | 'incorrect_reading' | 'correct_reading', string>>

const MAX_TARGET = 500
const MAX_INCORRECT = 500
const MAX_CORRECT = 200
const MAX_NOTES = 500

export default function MisreadingReportForm({ playbackContext, onClose }: Props) {
  const [targetSentence, setTargetSentence] = useState(playbackContext?.targetSentence ?? '')
  const [incorrectReading, setIncorrectReading] = useState('')
  const [correctReading, setCorrectReading] = useState('')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [errors, setErrors] = useState<FormErrors>({})
  const [success, setSuccess] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const backdropRef = useRef<HTMLDivElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const initialFocusRef = useRef<HTMLTextAreaElement>(null)

  const isFromPlayback = playbackContext !== null
  const showReadonlyTarget = isFromPlayback && !playbackContext.allowEditTarget
  const generationIdMissing = Boolean(
    playbackContext?.needsGenerationId && !playbackContext.generationId,
  )

  useEffect(() => {
    if (showReadonlyTarget && closeButtonRef.current) {
      closeButtonRef.current.focus()
    } else {
      const el = initialFocusRef.current ?? closeButtonRef.current
      if (el) el.focus()
    }
  }, [showReadonlyTarget])

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !submitting && !success) onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose, submitting, success])

  const validate = useCallback((): boolean => {
    const errs: FormErrors = {}
    if (!targetSentence.trim()) {
      if (showReadonlyTarget) {
        errs.target_sentence = '対象文が取得できませんでした'
      } else {
        errs.target_sentence = '対象の箇所を入力してください'
      }
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
    setErrors(errs)
    return Object.keys(errs).length === 0
  }, [targetSentence, correctReading, incorrectReading, showReadonlyTarget])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return
    if (generationIdMissing) {
      setSubmitError(
        '音声生成IDの連携が未確定のため、再生画面からの報告は一時的にご利用いただけません。Backend APIで音声生成IDが提供されるまでお待ちください。',
      )
      return
    }
    setSubmitting(true)
    setSubmitError(null)
    try {
      await submitMisreadingReport({
        episode_id: playbackContext?.episodeId ?? 0,
        article_id: playbackContext?.articleId ?? null,
        audio_generation_id: playbackContext?.generationId ?? null,
        playback_position: playbackContext?.playbackPosition ?? null,
        target_sentence: targetSentence.trim(),
        incorrect_reading: incorrectReading.trim(),
        correct_reading: correctReading.trim(),
        notes: notes.trim(),
      })
      setSuccess(true)
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

  if (success) {
    return (
      <div
        ref={backdropRef}
        className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
        onClick={handleBackdropClick}
      >
        <div
          className="flex w-full max-w-lg flex-col items-center rounded-2xl border border-slate-200 bg-white px-8 py-12 shadow-xl"
          role="dialog"
          aria-modal="true"
          aria-label="報告完了"
        >
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-emerald-100">
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              className="h-7 w-7 text-emerald-600"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M20 6L9 17l-5-5" />
            </svg>
          </div>
          <h2 className="mt-4 text-lg font-semibold text-slate-900">受付完了</h2>
          <p className="mt-2 text-center text-sm leading-6 text-slate-500">
            読み間違いの報告を受け付けました。<br />
            今後の読み上げ品質向上に活用します。
          </p>
          <button
            type="button"
            onClick={onClose}
            className="mt-6 rounded-full bg-sky-600 px-6 py-2 text-sm font-medium text-white transition hover:bg-sky-700"
          >
            閉じる
          </button>
        </div>
      </div>
    )
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
            ref={closeButtonRef}
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
              {playbackContext.targetSentence}
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
                ref={initialFocusRef}
                value={targetSentence}
                id="misreading-target-sentence"
                onChange={(e) => setTargetSentence(e.target.value)}
                maxLength={MAX_TARGET}
                rows={3}
                className={`w-full resize-none rounded-lg border px-3 py-2 text-sm text-slate-900 transition focus:outline-none focus:ring-2 ${
                  errors.target_sentence
                    ? 'border-red-300 bg-red-50 focus:border-red-400 focus:ring-red-100'
                    : 'border-slate-200 bg-slate-50 focus:border-sky-400 focus:bg-white focus:ring-sky-100'
                }`}
                placeholder="読み間違いがあった箇所を入力してください"
                aria-invalid={!!errors.target_sentence}
              />
              {errors.target_sentence && (
                <p className="mt-1 text-xs text-red-500">{errors.target_sentence}</p>
              )}
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
              className={`w-full rounded-lg border px-3 py-2 text-sm text-slate-900 transition focus:outline-none focus:ring-2 ${
                errors.incorrect_reading
                  ? 'border-red-300 bg-red-50 focus:border-red-400 focus:ring-red-100'
                  : 'border-slate-200 bg-slate-50 focus:border-sky-400 focus:bg-white focus:ring-sky-100'
              }`}
              placeholder="例: じんこうえいせい と読んでいた"
              aria-invalid={!!errors.incorrect_reading}
            />
            {errors.incorrect_reading && (
              <p className="mt-1 text-xs text-red-500">{errors.incorrect_reading}</p>
            )}
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
              className={`w-full rounded-lg border px-3 py-2 text-sm text-slate-900 transition focus:outline-none focus:ring-2 ${
                errors.correct_reading
                  ? 'border-red-300 bg-red-50 focus:border-red-400 focus:ring-red-100'
                  : 'border-slate-200 bg-slate-50 focus:border-sky-400 focus:bg-white focus:ring-sky-100'
              }`}
              placeholder="例: じんこうえいせい"
              aria-invalid={!!errors.correct_reading}
            />
            {errors.correct_reading && (
              <p className="mt-1 text-xs text-red-500">{errors.correct_reading}</p>
            )}
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
              disabled={submitting || generationIdMissing}
              className="inline-flex items-center gap-1.5 rounded-full bg-sky-600 px-5 py-2 text-sm font-medium text-white transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60"
              title={generationIdMissing ? '音声生成IDの連携が未確定のため送信できません' : undefined}
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
