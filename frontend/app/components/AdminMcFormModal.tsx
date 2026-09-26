'use client'

import { useEffect, useRef, useState } from 'react'
import { createMc, replaceMc, type Mc, type McSaveInput } from '../lib/admin-programs'

interface Props {
  mc: Mc | null
  onClose: () => void
  onSuccess: () => void
}

type FormErrors = Partial<Record<'id' | 'name' | 'role', string>>

const MAX_ID = 100
const MAX_NAME = 200
const MAX_ROLE = 200
const MAX_FISH = 200

export default function AdminMcFormModal({ mc, onClose, onSuccess }: Props) {
  const isEdit = mc !== null
  const [id, setId] = useState(mc?.id ?? '')
  const [name, setName] = useState(mc?.name ?? '')
  const [role, setRole] = useState(mc?.role ?? '')
  const [voiceFishs2pro, setVoiceFishs2pro] = useState(mc?.voice_fishs2pro ?? '')
  const [voiceAivispeech, setVoiceAivispeech] = useState(
    mc?.voice_aivispeech != null ? String(mc.voice_aivispeech) : '',
  )
  const [voiceVoicevox, setVoiceVoicevox] = useState(
    mc?.voice_voicevox != null ? String(mc.voice_voicevox) : '',
  )
  const [isActive, setIsActive] = useState(mc?.is_active ?? true)
  const [errors, setErrors] = useState<FormErrors>({})
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const backdropRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !submitting) onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose, submitting])

  const validate = (): boolean => {
    const errs: FormErrors = {}
    if (!id.trim()) errs.id = 'IDを入力してください'
    else if (id.length > MAX_ID) errs.id = `IDは${MAX_ID}文字以内で入力してください`
    if (name.length > MAX_NAME) errs.name = `名前は${MAX_NAME}文字以内で入力してください`
    if (role.length > MAX_ROLE) errs.role = `役割は${MAX_ROLE}文字以内で入力してください`
    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return
    setSubmitting(true)
    setSubmitError(null)
    const input: McSaveInput = {
      id: id.trim(),
      name: name.trim(),
      role: role.trim(),
      voice_fishs2pro: voiceFishs2pro.trim() || null,
      voice_aivispeech: voiceAivispeech.trim() === '' ? null : Number(voiceAivispeech),
      voice_voicevox: voiceVoicevox.trim() === '' ? null : Number(voiceVoicevox),
      is_active: isActive,
    }
    try {
      if (isEdit) {
        await replaceMc(mc!.id, input)
      } else {
        await createMc(input)
      }
      onSuccess()
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
        aria-label={isEdit ? 'MCを編集' : 'MCを追加'}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <h2 className="text-base font-semibold text-slate-900">{isEdit ? 'MCを編集' : 'MCを追加'}</h2>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="flex h-8 w-8 items-center justify-center rounded-full text-slate-500 transition hover:bg-slate-100 hover:text-slate-800 disabled:opacity-50"
            aria-label="閉じる"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4.5 w-4.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 overflow-y-auto px-5 py-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">
              ID <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={id}
              onChange={(e) => setId(e.target.value)}
              maxLength={MAX_ID}
              disabled={isEdit}
              className={`w-full rounded-lg border px-3 py-2 text-sm text-slate-900 transition focus:outline-none focus:ring-2 disabled:bg-slate-100 disabled:text-slate-500 ${
                errors.id
                  ? 'border-red-300 bg-red-50 focus:border-red-400 focus:ring-red-100'
                  : 'border-slate-200 bg-slate-50 focus:border-sky-400 focus:bg-white focus:ring-sky-100'
              }`}
              placeholder="例: radio_male"
              aria-invalid={!!errors.id}
            />
            {errors.id && <p className="mt-1 text-xs text-red-500">{errors.id}</p>}
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">名前</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={MAX_NAME}
              className={`w-full rounded-lg border px-3 py-2 text-sm text-slate-900 transition focus:outline-none focus:ring-2 ${
                errors.name
                  ? 'border-red-300 bg-red-50 focus:border-red-400 focus:ring-red-100'
                  : 'border-slate-200 bg-slate-50 focus:border-sky-400 focus:bg-white focus:ring-sky-100'
              }`}
            />
            {errors.name && <p className="mt-1 text-xs text-red-500">{errors.name}</p>}
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">役割</label>
            <input
              type="text"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              maxLength={MAX_ROLE}
              className={`w-full rounded-lg border px-3 py-2 text-sm text-slate-900 transition focus:outline-none focus:ring-2 ${
                errors.role
                  ? 'border-red-300 bg-red-50 focus:border-red-400 focus:ring-red-100'
                  : 'border-slate-200 bg-slate-50 focus:border-sky-400 focus:bg-white focus:ring-sky-100'
              }`}
              placeholder="例: メインMC"
            />
            {errors.role && <p className="mt-1 text-xs text-red-500">{errors.role}</p>}
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-500">Fish S2 Pro</label>
              <input
                type="text"
                value={voiceFishs2pro}
                onChange={(e) => setVoiceFishs2pro(e.target.value)}
                maxLength={MAX_FISH}
                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-900 transition focus:border-sky-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100"
                placeholder="voice id"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-500">AivisSpeech</label>
              <input
                type="number"
                value={voiceAivispeech}
                onChange={(e) => setVoiceAivispeech(e.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-900 transition focus:border-sky-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100"
                placeholder="speaker id"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-500">VOICEVOX</label>
              <input
                type="number"
                value={voiceVoicevox}
                onChange={(e) => setVoiceVoicevox(e.target.value)}
                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-900 transition focus:border-sky-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100"
                placeholder="speaker id"
              />
            </div>
          </div>

          {isEdit && (
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-500">状態</label>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => setIsActive((prev) => !prev)}
                  className="relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full transition"
                  role="switch"
                  aria-checked={isActive}
                >
                  <span className={`inline-block h-6 w-11 rounded-full transition-colors ${isActive ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                  <span
                    className={`absolute left-0.5 inline-block h-5 w-5 transform rounded-full bg-white shadow-sm transition-transform ${
                      isActive ? 'translate-x-5' : 'translate-x-0.5'
                    }`}
                  />
                </button>
                <span className={`text-xs font-medium ${isActive ? 'text-emerald-700' : 'text-slate-400'}`}>
                  {isActive ? '有効' : '無効'}
                </span>
              </div>
            </div>
          )}

          {submitError && (
            <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{submitError}</div>
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
              {submitting && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />}
              {isEdit ? '保存する' : '追加する'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
