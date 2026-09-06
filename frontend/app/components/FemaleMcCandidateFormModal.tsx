'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import {
  createFemaleMcCandidateClient,
  updateFemaleMcCandidateClient,
  type FemaleMcCandidate,
} from '../lib/admin-female-mc-candidates'

interface Props {
  candidate: FemaleMcCandidate | null
  onClose: () => void
  onSuccess: (candidate: FemaleMcCandidate) => void
}

const MAX_VOICE_NAME = 100
const MAX_DISPLAY_NAME = 100
const MAX_SAMPLE_TEXT = 2000

type FormErrors = Partial<Record<'voiceName' | 'displayName', string>>

export default function FemaleMcCandidateFormModal({ candidate, onClose, onSuccess }: Props) {
  const isEdit = candidate !== null
  const [voiceName, setVoiceName] = useState(candidate?.voice_name ?? '')
  const [displayName, setDisplayName] = useState(candidate?.display_name ?? '')
  const [sampleText, setSampleText] = useState(candidate?.sample_text ?? '')
  const [submitting, setSubmitting] = useState(false)
  const [errors, setErrors] = useState<FormErrors>({})
  const [submitError, setSubmitError] = useState<string | null>(null)

  const backdropRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !submitting) onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose, submitting])

  const validate = useCallback((): boolean => {
    const errs: FormErrors = {}
    if (!isEdit) {
      if (!voiceName.trim()) errs.voiceName = 'ボイス名を入力してください'
      else if (voiceName.length > MAX_VOICE_NAME)
        errs.voiceName = `ボイス名は${MAX_VOICE_NAME}文字以内で入力してください`
    }
    if (!displayName.trim()) errs.displayName = '表示名を入力してください'
    else if (displayName.length > MAX_DISPLAY_NAME)
      errs.displayName = `表示名は${MAX_DISPLAY_NAME}文字以内で入力してください`
    setErrors(errs)
    return Object.keys(errs).length === 0
  }, [isEdit, voiceName, displayName])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      const trimmedSampleText = sampleText.trim()
      let saved: FemaleMcCandidate
      if (isEdit) {
        saved = await updateFemaleMcCandidateClient(candidate!.voice_name, {
          display_name: displayName.trim(),
          ...(trimmedSampleText ? { sample_text: trimmedSampleText } : {}),
        })
      } else {
        saved = await createFemaleMcCandidateClient({
          voice_name: voiceName.trim(),
          display_name: displayName.trim(),
          ...(trimmedSampleText ? { sample_text: trimmedSampleText } : {}),
        })
      }
      onSuccess(saved)
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : '保存に失敗しました')
    } finally {
      setSubmitting(false)
    }
  }

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === backdropRef.current && !submitting) onClose()
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
        aria-label={isEdit ? '女性MC候補を編集' : '女性MC候補を追加'}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <h2 className="text-base font-semibold text-slate-900">
            {isEdit ? '女性MC候補を編集' : '女性MC候補を追加'}
          </h2>
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

        <form onSubmit={handleSubmit} className="space-y-4 overflow-y-auto px-5 py-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">
              ボイス名 <span className="text-red-500">*</span>
            </label>
            {isEdit ? (
              <p className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700">{voiceName}</p>
            ) : (
              <>
                <input
                  type="text"
                  value={voiceName}
                  onChange={(e) => setVoiceName(e.target.value)}
                  maxLength={MAX_VOICE_NAME}
                  className={`w-full rounded-lg border px-3 py-2 text-sm text-slate-900 transition focus:outline-none focus:ring-2 ${
                    errors.voiceName
                      ? 'border-red-300 bg-red-50 focus:border-red-400 focus:ring-red-100'
                      : 'border-slate-200 bg-slate-50 focus:border-sky-400 focus:bg-white focus:ring-sky-100'
                  }`}
                  placeholder="例: morigawa"
                  aria-invalid={!!errors.voiceName}
                />
                {errors.voiceName && <p className="mt-1 text-xs text-red-500">{errors.voiceName}</p>}
                <p className="mt-0.5 text-right text-[11px] text-slate-400">
                  {voiceName.length}/{MAX_VOICE_NAME}
                </p>
              </>
            )}
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">
              表示名 <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              maxLength={MAX_DISPLAY_NAME}
              className={`w-full rounded-lg border px-3 py-2 text-sm text-slate-900 transition focus:outline-none focus:ring-2 ${
                errors.displayName
                  ? 'border-red-300 bg-red-50 focus:border-red-400 focus:ring-red-100'
                  : 'border-slate-200 bg-slate-50 focus:border-sky-400 focus:bg-white focus:ring-sky-100'
              }`}
              placeholder="例: もりかわ"
              aria-invalid={!!errors.displayName}
            />
            {errors.displayName && <p className="mt-1 text-xs text-red-500">{errors.displayName}</p>}
            <p className="mt-0.5 text-right text-[11px] text-slate-400">
              {displayName.length}/{MAX_DISPLAY_NAME}
            </p>
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">試聴文</label>
            <textarea
              value={sampleText}
              onChange={(e) => setSampleText(e.target.value)}
              maxLength={MAX_SAMPLE_TEXT}
              rows={3}
              className="w-full resize-none rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-900 transition focus:border-sky-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100"
              placeholder={isEdit ? '空欄の場合は現在の試聴文を維持します' : '空欄の場合は既定の試聴文を使用します'}
            />
            <p className="mt-0.5 text-right text-[11px] text-slate-400">
              {sampleText.length}/{MAX_SAMPLE_TEXT}
            </p>
          </div>

          {submitError && (
            <p role="alert" className="text-xs text-red-500">
              {submitError}
            </p>
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
              disabled={submitting}
              className="inline-flex items-center gap-1.5 rounded-full bg-sky-600 px-5 py-2 text-sm font-medium text-white transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting && (
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              )}
              {isEdit ? '保存する' : '追加する'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
