'use client'

import { useState } from 'react'
import {
  VOICE_ENGINES,
  VOICE_FIELD_MAP,
  fetchVoiceOptionsClient,
  saveVoiceSettingsClient,
  type EngineVoiceOptions,
  type VoiceEngineKey,
  type VoiceGender,
  type VoiceOption,
  type VoiceOptionsResponse,
  type VoiceSettings,
} from '../lib/admin-voice-settings'

interface Props {
  initialSettings: VoiceSettings
  initialOptions: VoiceOptionsResponse
}

const GENDER_LABEL: Record<VoiceGender, string> = { male: '男声', female: '女声' }
const GENDERS: VoiceGender[] = ['male', 'female']

function findOption(engineOptions: EngineVoiceOptions, value: number | string): VoiceOption | undefined {
  return engineOptions.options.find((opt) => String(opt.value) === String(value))
}

export default function AdminVoiceSettingsShell({ initialSettings, initialOptions }: Props) {
  const [settings, setSettings] = useState<VoiceSettings>(initialSettings)
  const [options, setOptions] = useState<VoiceOptionsResponse>(initialOptions)
  const [retryingEngines, setRetryingEngines] = useState<Set<VoiceEngineKey>>(new Set())
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveSuccess, setSaveSuccess] = useState(false)

  const handleChange = (engine: VoiceEngineKey, gender: VoiceGender, raw: string) => {
    const field = VOICE_FIELD_MAP[engine][gender]
    const value: number | string = engine === 'fishs2pro' ? raw : Number(raw)
    setSettings((prev) => ({ ...prev, [field]: value }))
    setSaveSuccess(false)
    setSaveError(null)
  }

  const handleRetry = async (engine: VoiceEngineKey) => {
    setRetryingEngines((prev) => new Set(prev).add(engine))
    try {
      const fresh = await fetchVoiceOptionsClient()
      setOptions(fresh)
    } catch {
      /* 一覧の再取得に失敗。既存のエラー表示と再試行ボタンをそのまま残す */
    } finally {
      setRetryingEngines((prev) => {
        const next = new Set(prev)
        next.delete(engine)
        return next
      })
    }
  }

  const handleSave = async () => {
    if (saving) return
    setSaving(true)
    setSaveError(null)
    setSaveSuccess(false)
    try {
      const saved = await saveVoiceSettingsClient(settings)
      setSettings(saved)
      setSaveSuccess(true)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : '保存できませんでした')
    } finally {
      setSaving(false)
    }
  }

  const hasIncompleteValues = VOICE_ENGINES.some((engine) =>
    GENDERS.some((gender) => {
      const value = settings[VOICE_FIELD_MAP[engine.key][gender]]
      return (
        value === null ||
        value === undefined ||
        value === '' ||
        (typeof value === 'number' && Number.isNaN(value))
      )
    }),
  )

  const statusMessage = saving
    ? '保存中…'
    : saveError
      ? saveError
      : saveSuccess
        ? '保存しました。保存後に開始する生成から反映されます。'
        : '保存後に開始する生成から反映されます。'

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <h1 className="text-lg font-semibold text-slate-900">ボイス設定</h1>
        <p className="mt-1 text-sm text-slate-500">
          AivisSpeech・VOICEVOX・Fish S2 Pro それぞれの男声・女声を設定します。
        </p>
      </div>

      <div className="space-y-4">
        {VOICE_ENGINES.map((engine) => {
          const engineOptions = options[engine.key]
          const isError = engineOptions.status === 'error'
          const isRetrying = retryingEngines.has(engine.key)
          return (
            <div key={engine.key} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-sm font-semibold text-slate-900">{engine.label}</h2>
                {isError && (
                  <button
                    type="button"
                    onClick={() => handleRetry(engine.key)}
                    disabled={isRetrying}
                    className="shrink-0 rounded-md border border-rose-200 bg-white px-2 py-1 text-xs text-rose-700 transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {isRetrying ? '再試行中…' : '再試行'}
                  </button>
                )}
              </div>
              {isError && (
                <p className="mt-1 text-xs text-rose-600">
                  {engineOptions.error ?? '話者一覧を取得できませんでした'}
                </p>
              )}
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                {GENDERS.map((gender) => {
                  const field = VOICE_FIELD_MAP[engine.key][gender]
                  const currentValue = settings[field]
                  const matched = !isError ? findOption(engineOptions, currentValue) : undefined
                  const missing = !isError && !matched
                  const selectId = `voice-${engine.key}-${gender}`
                  return (
                    <div key={selectId}>
                      <label htmlFor={selectId} className="block text-xs font-medium text-slate-700">
                        {GENDER_LABEL[gender]}
                      </label>
                      <select
                        id={selectId}
                        value={String(currentValue)}
                        disabled={isError || saving}
                        onChange={(e) => handleChange(engine.key, gender, e.target.value)}
                        className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
                      >
                        {(missing || isError) && (
                          <option value={String(currentValue)}>
                            {String(currentValue)}
                            {!isError && '（一覧にありません）'}
                          </option>
                        )}
                        {!isError &&
                          engineOptions.options.map((opt) => (
                            <option key={String(opt.value)} value={String(opt.value)}>
                              {opt.display_name}
                            </option>
                          ))}
                      </select>
                      {missing && (
                        <p className="mt-1 text-xs text-amber-600">現在の値は最新の一覧にありません</p>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || hasIncompleteValues}
            className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving ? '保存中…' : '保存'}
          </button>
          <span
            className={`text-xs ${saveError ? 'text-rose-600' : 'text-slate-400'}`}
            aria-live="polite"
          >
            {statusMessage}
          </span>
        </div>
      </div>
    </div>
  )
}
