'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import toast from 'react-hot-toast'
import {
  createDictionaryEntry,
  updateDictionaryEntry,
  updateDictionaryStatus,
  type DictionaryEntry,
} from '../lib/admin-dictionary'

interface Props {
  entry: DictionaryEntry | null
  onClose: () => void
  onSuccess: () => void
}

const CATEGORIES = ['固有名詞', '地名', '人名', '技術用語', '業界用語', 'その他']

type FormErrors = Partial<Record<'word' | 'reading' | 'category', string>>

const MAX_WORD = 100
const MAX_READING = 200
const MAX_NOTES = 500

export default function DictionaryFormModal({ entry, onClose, onSuccess }: Props) {
  const isEdit = entry !== null
  const [word, setWord] = useState(entry?.word ?? '')
  const [reading, setReading] = useState(entry?.reading ?? '')
  const [category, setCategory] = useState(entry?.category ?? '')
  const [notes, setNotes] = useState(entry?.notes ?? '')
  const [status, setStatus] = useState<'active' | 'inactive'>(entry?.status ?? 'active')
  const [submitting, setSubmitting] = useState(false)
  const [errors, setErrors] = useState<FormErrors>({})

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
    if (!word.trim()) errs.word = '単語を入力してください'
    else if (word.length > MAX_WORD) errs.word = `単語は${MAX_WORD}文字以内で入力してください`
    if (!reading.trim()) errs.reading = '読み仮名を入力してください'
    else if (reading.length > MAX_READING)
      errs.reading = `読み仮名は${MAX_READING}文字以内で入力してください`
    if (!category) errs.category = 'カテゴリを選択してください'
    setErrors(errs)
    return Object.keys(errs).length === 0
  }, [word, reading, category])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return
    setSubmitting(true)
    try {
      if (isEdit) {
        await updateDictionaryEntry(entry!.id, {
          word: word.trim(),
          reading: reading.trim(),
          category,
          notes: notes.trim() || undefined,
        })
        if (status !== entry!.status) {
          await updateDictionaryStatus(entry!.id, status)
        }
        toast.success('辞書を更新しました')
      } else {
        await createDictionaryEntry({
          word: word.trim(),
          reading: reading.trim(),
          category,
          notes: notes.trim() || undefined,
        })
        toast.success('辞書を追加しました')
      }
      onSuccess()
    } catch (err) {
      const message =
        err instanceof Error ? err.message : '保存に失敗しました'
      toast.error(message)
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
        aria-label={isEdit ? '辞書を編集' : '辞書を追加'}
      >
        {/* ヘッダー */}
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <h2 className="text-base font-semibold text-slate-900">
            {isEdit ? '辞書を編集' : '辞書を追加'}
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

        {/* フォーム */}
        <form onSubmit={handleSubmit} className="space-y-4 overflow-y-auto px-5 py-4">
          {/* 単語 */}
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">
              単語 <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={word}
              onChange={(e) => setWord(e.target.value)}
              maxLength={MAX_WORD}
              className={`w-full rounded-lg border px-3 py-2 text-sm text-slate-900 transition focus:outline-none focus:ring-2 ${
                errors.word
                  ? 'border-red-300 bg-red-50 focus:border-red-400 focus:ring-red-100'
                  : 'border-slate-200 bg-slate-50 focus:border-sky-400 focus:bg-white focus:ring-sky-100'
              }`}
              placeholder="例: 人工衛星"
              aria-invalid={!!errors.word}
            />
            {errors.word && (
              <p className="mt-1 text-xs text-red-500">{errors.word}</p>
            )}
            <p className="mt-0.5 text-right text-[11px] text-slate-400">
              {word.length}/{MAX_WORD}
            </p>
          </div>

          {/* 読み仮名 */}
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">
              読み仮名 <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={reading}
              onChange={(e) => setReading(e.target.value)}
              maxLength={MAX_READING}
              className={`w-full rounded-lg border px-3 py-2 text-sm text-slate-900 transition focus:outline-none focus:ring-2 ${
                errors.reading
                  ? 'border-red-300 bg-red-50 focus:border-red-400 focus:ring-red-100'
                  : 'border-slate-200 bg-slate-50 focus:border-sky-400 focus:bg-white focus:ring-sky-100'
              }`}
              placeholder="例: じんこうえいせい"
              aria-invalid={!!errors.reading}
            />
            {errors.reading && (
              <p className="mt-1 text-xs text-red-500">{errors.reading}</p>
            )}
            <p className="mt-0.5 text-right text-[11px] text-slate-400">
              {reading.length}/{MAX_READING}
            </p>
          </div>

          {/* カテゴリ */}
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">
              カテゴリ <span className="text-red-500">*</span>
            </label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className={`w-full rounded-lg border px-3 py-2 text-sm text-slate-700 transition focus:outline-none focus:ring-2 ${
                errors.category
                  ? 'border-red-300 bg-red-50 focus:border-red-400 focus:ring-red-100'
                  : 'border-slate-200 bg-slate-50 focus:border-sky-400 focus:bg-white focus:ring-sky-100'
              }`}
              aria-invalid={!!errors.category}
            >
              <option value="">選択してください</option>
              {CATEGORIES.map((cat) => (
                <option key={cat} value={cat}>
                  {cat}
                </option>
              ))}
            </select>
            {errors.category && (
              <p className="mt-1 text-xs text-red-500">{errors.category}</p>
            )}
          </div>

          {/* 備考 */}
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">備考</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              maxLength={MAX_NOTES}
              rows={3}
              className="w-full resize-none rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-900 transition focus:border-sky-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100"
              placeholder="必要に応じて備考を入力"
            />
            <p className="mt-0.5 text-right text-[11px] text-slate-400">
              {notes.length}/{MAX_NOTES}
            </p>
          </div>

          {/* 編集モードのみ：状態トグル */}
          {isEdit && (
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-500">状態</label>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => setStatus(status === 'active' ? 'inactive' : 'active')}
                  className="relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full transition"
                  role="switch"
                  aria-checked={status === 'active'}
                >
                  <span
                    className={`inline-block h-6 w-11 rounded-full transition-colors ${
                      status === 'active' ? 'bg-emerald-500' : 'bg-slate-300'
                    }`}
                  />
                  <span
                    className={`absolute left-0.5 inline-block h-5 w-5 transform rounded-full bg-white shadow-sm transition-transform ${
                      status === 'active' ? 'translate-x-5' : 'translate-x-0.5'
                    }`}
                  />
                </button>
                <span
                  className={`text-xs font-medium ${
                    status === 'active' ? 'text-emerald-700' : 'text-slate-400'
                  }`}
                >
                  {status === 'active' ? '有効' : '無効'}
                </span>
              </div>
            </div>
          )}

          {/* 編集モードのみ：最終更新情報 */}
          {isEdit && entry && (
            <div className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-400">
              最終更新: {new Date(entry.updated_at).toLocaleString('ja-JP')}
            </div>
          )}

          {/* アクション */}
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
