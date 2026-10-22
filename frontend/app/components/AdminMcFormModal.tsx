'use client'

import { useEffect, useRef, useState } from 'react'
import {
  createMc,
  replaceMc,
  uploadMcPhoto,
  deleteMcPhoto,
  MAX_PERSONA_LENGTH,
  type Mc,
  type McSaveInput,
} from '../lib/admin-programs'
import { fetchVoiceOptionsClient } from '../lib/admin-voice-settings'
import {
  DISABLED_TTS_ENGINE_MESSAGE,
  isTtsDisabled,
  type EngineVoiceOptions,
  type VoiceEngineKey,
  type VoiceOptionsResponse,
} from '../lib/tts-engines'

interface Props {
  mc: Mc | null
  onClose: () => void
  onSuccess: () => void
}

type FormErrors = Partial<Record<'id' | 'name' | 'role' | 'persona' | 'photo', string>>

const MAX_ID = 100
const MAX_NAME = 200
const MAX_ROLE = 200
const MAX_PHOTO_BYTES = 5 * 1024 * 1024
const PHOTO_TYPES = ['image/jpeg', 'image/png', 'image/webp']

const VOICE_SELECT_CLASS =
  'w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-900 transition focus:border-sky-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400'

function VoiceOptionItems({
  engine,
  current,
}: {
  engine: EngineVoiceOptions | undefined
  current: string
}) {
  const options = engine?.options ?? []
  // 候補を確認できた（status が ok）場合のみ「候補にありません」と断定する
  const loaded = engine?.status === 'ok'
  // 候補にない保存済みの値は、値を失わないよう専用optionで表示する（取得完了前は値のみ表示）
  const isOutOfCandidates = current !== '' && !options.some((o) => String(o.value) === current)
  return (
    <>
      <option value="">選択してください</option>
      {isOutOfCandidates && (
        <option value={current}>{loaded ? `現在の値: ${current}（候補にありません）` : current}</option>
      )}
      {options.map((o) => (
        <option key={String(o.value)} value={String(o.value)}>
          {o.display_name}
        </option>
      ))}
    </>
  )
}

export default function AdminMcFormModal({ mc, onClose, onSuccess }: Props) {
  const isEdit = mc !== null
  const isAivispeechDisabled = isTtsDisabled('aivispeech')
  const isVoicevoxDisabled = isTtsDisabled('voicevox')
  const [id, setId] = useState(mc?.id ?? '')
  const [name, setName] = useState(mc?.name ?? '')
  const [role, setRole] = useState(mc?.role ?? '')
  const [persona, setPersona] = useState(mc?.persona ?? '')
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
  const [voiceOptions, setVoiceOptions] = useState<VoiceOptionsResponse | null>(null)
  const [voiceOptionsError, setVoiceOptionsError] = useState<string | null>(null)

  const [photoFile, setPhotoFile] = useState<File | null>(null)
  const [photoPreview, setPhotoPreview] = useState<string | null>(null)
  const [photoRemoved, setPhotoRemoved] = useState(false)
  const [photoBroken, setPhotoBroken] = useState(false)
  // MC本体の保存が済んだか（写真だけ失敗した場合の再試行で、作成を重複させないため）
  const [mainSaved, setMainSaved] = useState(false)

  const backdropRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!photoFile) {
      setPhotoPreview(null)
      return
    }
    const url = URL.createObjectURL(photoFile)
    setPhotoPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [photoFile])

  const currentPhotoUrl =
    photoPreview ?? (!photoRemoved && !photoBroken && mc?.photo_url ? mc.photo_url : null)

  const handlePhotoChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (!PHOTO_TYPES.includes(file.type)) {
      setErrors((prev) => ({ ...prev, photo: '画像はJPEG・PNG・WebPのいずれかを選択してください' }))
      return
    }
    if (file.size > MAX_PHOTO_BYTES) {
      setErrors((prev) => ({ ...prev, photo: '画像のサイズは5MB以下にしてください' }))
      return
    }
    setErrors((prev) => ({ ...prev, photo: undefined }))
    setPhotoFile(file)
    setPhotoRemoved(false)
  }

  const handlePhotoRemove = () => {
    setPhotoFile(null)
    setPhotoRemoved(true)
    setErrors((prev) => ({ ...prev, photo: undefined }))
  }

  const hasPhotoChange = photoFile !== null || (photoRemoved && !!mc?.photo_url)

  const handleClose = () => {
    // MC本体が保存済みなら一覧を最新化して閉じる
    if (mainSaved) onSuccess()
    else onClose()
  }

  useEffect(() => {
    let cancelled = false
    fetchVoiceOptionsClient()
      .then((res) => {
        if (!cancelled) setVoiceOptions(res)
      })
      .catch((err) => {
        if (!cancelled) setVoiceOptionsError(err instanceof Error ? err.message : 'ボイス候補の取得に失敗しました')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const engineError = (key: VoiceEngineKey): string | null => {
    const e = voiceOptions?.[key]
    return e?.status === 'error' ? (e.error ?? 'ボイス候補の取得に失敗しました') : null
  }
  const voiceErrors = [voiceOptionsError, engineError('fishs2pro')].filter((m): m is string => !!m)

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !submitting) handleClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose, onSuccess, mainSaved, submitting])

  const validate = (): boolean => {
    const errs: FormErrors = {}
    if (!id.trim()) errs.id = 'IDを入力してください'
    else if (id.length > MAX_ID) errs.id = `IDは${MAX_ID}文字以内で入力してください`
    if (name.length > MAX_NAME) errs.name = `名前は${MAX_NAME}文字以内で入力してください`
    if (role.length > MAX_ROLE) errs.role = `役割は${MAX_ROLE}文字以内で入力してください`
    if (persona.length > MAX_PERSONA_LENGTH)
      errs.persona = `ペルソナは${MAX_PERSONA_LENGTH}文字以内で入力してください`
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
      // BEのPUTはnullを「変更なし」として扱うため、削除は空文字で明示する
      persona: persona.trim(),
      voice_fishs2pro: voiceFishs2pro.trim() || null,
      voice_aivispeech: voiceAivispeech.trim() === '' ? null : Number(voiceAivispeech),
      voice_voicevox: voiceVoicevox.trim() === '' ? null : Number(voiceVoicevox),
      is_active: isActive,
    }
    let step: 'main' | 'photo' = 'main'
    try {
      if (isEdit || mainSaved) {
        await replaceMc(input.id, input)
      } else {
        await createMc(input)
      }
      step = 'photo'
      if (photoFile) {
        await uploadMcPhoto(input.id, photoFile)
      } else if (photoRemoved && mc?.photo_url) {
        await deleteMcPhoto(input.id)
      }
      onSuccess()
    } catch (err) {
      const message = err instanceof Error ? err.message : '保存に失敗しました'
      if (step === 'photo') setMainSaved(true)
      setSubmitError(
        step === 'photo'
          ? `MC情報は保存されましたが、写真の更新に失敗しました: ${message}（もう一度保存するか、閉じてください）`
          : message,
      )
    } finally {
      setSubmitting(false)
    }
  }

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === backdropRef.current && !submitting) handleClose()
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
            onClick={handleClose}
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
              disabled={isEdit || mainSaved}
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
            <span className="mb-1 block text-xs font-medium text-slate-500">写真</span>
            <div className="flex items-center gap-3">
              {currentPhotoUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={currentPhotoUrl}
                  alt="MC写真のプレビュー"
                  onError={() => setPhotoBroken(true)}
                  className="h-16 w-16 rounded-full border border-slate-200 object-cover"
                />
              ) : (
                <div
                  aria-hidden="true"
                  className="flex h-16 w-16 items-center justify-center rounded-full bg-slate-200 text-lg font-medium text-slate-500"
                >
                  {(name.trim() || id.trim() || '?').charAt(0)}
                </div>
              )}
              <div className="flex flex-wrap items-center gap-2">
                <input
                  ref={fileInputRef}
                  id="mc-form-photo"
                  type="file"
                  accept={PHOTO_TYPES.join(',')}
                  onChange={handlePhotoChange}
                  disabled={submitting}
                  className="sr-only"
                  aria-label="MC写真を選択"
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={submitting}
                  className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
                >
                  {currentPhotoUrl ? '写真を変更' : '写真を選択'}
                </button>
                {currentPhotoUrl && (
                  <button
                    type="button"
                    onClick={handlePhotoRemove}
                    disabled={submitting}
                    className="rounded-full border border-red-200 bg-white px-3 py-1.5 text-xs font-medium text-red-600 transition hover:bg-red-50 disabled:opacity-50"
                  >
                    写真を削除
                  </button>
                )}
              </div>
            </div>
            <p className="mt-1 text-xs text-slate-400">JPEG・PNG・WebP、5MB以下。保存時にアップロードされます。</p>
            {errors.photo && <p role="alert" className="mt-1 text-xs text-red-500">{errors.photo}</p>}
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

          <div>
            <label htmlFor="mc-form-persona" className="mb-1 block text-xs font-medium text-slate-500">
              ペルソナ（性格・話し方など）
            </label>
            <textarea
              id="mc-form-persona"
              value={persona}
              onChange={(e) => setPersona(e.target.value)}
              rows={6}
              maxLength={MAX_PERSONA_LENGTH}
              className={`w-full resize-y rounded-lg border px-3 py-2 text-sm text-slate-900 transition focus:outline-none focus:ring-2 ${
                errors.persona
                  ? 'border-red-300 bg-red-50 focus:border-red-400 focus:ring-red-100'
                  : 'border-slate-200 bg-slate-50 focus:border-sky-400 focus:bg-white focus:ring-sky-100'
              }`}
              placeholder="例: 落ち着いた口調で、専門用語はかみ砕いて説明する"
              aria-invalid={!!errors.persona}
              aria-describedby="mc-form-persona-hint"
            />
            <p id="mc-form-persona-hint" className="mt-1 text-xs text-slate-400">
              話し方もここで設定します。未入力の場合はペルソナなしで保存されます（{persona.length}/{MAX_PERSONA_LENGTH}文字）。
            </p>
            {errors.persona && <p className="mt-1 text-xs text-red-500">{errors.persona}</p>}
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <label htmlFor="mc-form-voice-fishs2pro" className="mb-1 block text-xs font-medium text-slate-500">Fish S2 Pro</label>
              <select
                id="mc-form-voice-fishs2pro"
                value={voiceFishs2pro}
                onChange={(e) => setVoiceFishs2pro(e.target.value)}
                className={VOICE_SELECT_CLASS}
              >
                <VoiceOptionItems engine={voiceOptions?.fishs2pro} current={voiceFishs2pro} />
              </select>
            </div>
            <div>
              <label htmlFor="mc-form-voice-aivispeech" className="mb-1 block text-xs font-medium text-slate-500">AivisSpeech</label>
              <select
                id="mc-form-voice-aivispeech"
                value={voiceAivispeech}
                onChange={(e) => setVoiceAivispeech(e.target.value)}
                disabled={isAivispeechDisabled}
                title={isAivispeechDisabled ? DISABLED_TTS_ENGINE_MESSAGE : undefined}
                aria-describedby={isAivispeechDisabled ? 'mc-form-tts-disabled-note' : undefined}
                className={VOICE_SELECT_CLASS}
              >
                <VoiceOptionItems engine={voiceOptions?.aivispeech} current={voiceAivispeech} />
              </select>
            </div>
            <div>
              <label htmlFor="mc-form-voice-voicevox" className="mb-1 block text-xs font-medium text-slate-500">VOICEVOX</label>
              <select
                id="mc-form-voice-voicevox"
                value={voiceVoicevox}
                onChange={(e) => setVoiceVoicevox(e.target.value)}
                disabled={isVoicevoxDisabled}
                title={isVoicevoxDisabled ? DISABLED_TTS_ENGINE_MESSAGE : undefined}
                aria-describedby={isVoicevoxDisabled ? 'mc-form-tts-disabled-note' : undefined}
                className={VOICE_SELECT_CLASS}
              >
                <VoiceOptionItems engine={voiceOptions?.voicevox} current={voiceVoicevox} />
              </select>
            </div>
          </div>
          {voiceErrors.map((m) => (
            <p key={m} role="alert" className="text-xs text-red-600">
              ボイス候補を取得できませんでした: {m}
            </p>
          ))}
          {(isAivispeechDisabled || isVoicevoxDisabled) && (
            <p id="mc-form-tts-disabled-note" className="text-xs text-slate-500">
              {DISABLED_TTS_ENGINE_MESSAGE}
            </p>
          )}

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
              onClick={handleClose}
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
