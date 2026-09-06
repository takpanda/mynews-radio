'use client'

import { useRef, useState } from 'react'
import {
  saveCategoryFemaleMcClient,
  type CategoryFemaleMcSettings,
  type CategoryFemaleVoices,
  type FemaleMcOption,
} from '../lib/admin-category-female-mc'

interface Props {
  initialData: CategoryFemaleMcSettings
}

function findVoice(voices: FemaleMcOption[], value: string): FemaleMcOption | undefined {
  return voices.find((voice) => voice.value === value)
}

export default function CategoryFemaleMcPanel({ initialData }: Props) {
  const [data, setData] = useState<CategoryFemaleMcSettings>(initialData)
  const [assignments, setAssignments] = useState<CategoryFemaleVoices>(initialData.category_female_voices)
  const [playingVoice, setPlayingVoice] = useState<string | null>(null)
  const [playErrors, setPlayErrors] = useState<Record<string, string | null>>({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  const handleCategoryChange = (category: string, value: string) => {
    setAssignments((prev) => ({ ...prev, [category]: value || null }))
    setSaveSuccess(false)
    setSaveError(null)
  }

  const handleTogglePlay = (voice: FemaleMcOption) => {
    const audio = audioRef.current
    if (!audio || !voice.sample.available) return
    if (playingVoice === voice.value) {
      audio.pause()
      audio.currentTime = 0
      setPlayingVoice(null)
      return
    }
    setPlayErrors((prev) => ({ ...prev, [voice.value]: null }))
    audio.src = voice.sample.url
    setPlayingVoice(voice.value)
    audio.play().catch(() => {
      setPlayErrors((prev) => ({ ...prev, [voice.value]: 'サンプルを再生できませんでした' }))
      setPlayingVoice(null)
    })
  }

  const handleSave = async () => {
    if (saving) return
    setSaving(true)
    setSaveError(null)
    setSaveSuccess(false)
    try {
      const payload: CategoryFemaleVoices = {}
      data.categories.forEach((category) => {
        payload[category] = assignments[category] ?? null
      })
      const saved = await saveCategoryFemaleMcClient(payload)
      setData(saved)
      setAssignments(saved.category_female_voices)
      setSaveSuccess(true)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : '保存できませんでした')
    } finally {
      setSaving(false)
    }
  }

  const defaultVoiceLabel = findVoice(data.voices, data.default_voice)?.display_name ?? data.default_voice

  const statusMessage = saving
    ? '保存中…'
    : saveError
      ? saveError
      : saveSuccess
        ? '保存しました。保存後に開始する生成から反映されます。'
        : '保存後に開始する生成から反映されます。'

  return (
    <div className="space-y-4">
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <h2 className="text-sm font-semibold text-slate-900">候補女性MC（試聴）</h2>
        <p className="mt-1 text-xs text-slate-500">
          各候補の固定サンプルを再生できます。別の候補を再生すると、再生中のサンプルは自動的に停止します。
        </p>
        {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
        <audio
          ref={audioRef}
          onEnded={() => setPlayingVoice(null)}
          onError={() => {
            setPlayingVoice((current) => {
              if (current) {
                setPlayErrors((prev) => ({ ...prev, [current]: 'サンプルを再生できませんでした' }))
              }
              return null
            })
          }}
          className="hidden"
        />
        <div className="mt-3 space-y-2">
          {data.voices.map((voice) => {
            const isPlaying = playingVoice === voice.value
            const error = playErrors[voice.value]
            return (
              <div
                key={voice.value}
                className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 p-3"
              >
                <div>
                  <p className="text-sm font-medium text-slate-900">{voice.display_name}</p>
                  <p className="mt-0.5 text-xs text-slate-500">{voice.sample.text}</p>
                  {!voice.sample.available && (
                    <p className="mt-1 text-xs text-amber-600">サンプル音声が未登録です</p>
                  )}
                  {error && (
                    <p role="alert" className="mt-1 text-xs text-rose-600">
                      {error}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => handleTogglePlay(voice)}
                  disabled={!voice.sample.available}
                  aria-label={`${voice.display_name}のサンプルを${isPlaying ? '停止' : '再生'}`}
                  className="shrink-0 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {isPlaying ? '停止' : '再生'}
                </button>
              </div>
            )
          })}
        </div>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <h2 className="text-sm font-semibold text-slate-900">カテゴリ別女性MC設定</h2>
        <p className="mt-1 text-xs text-slate-500">
          カテゴリごとに女性MCを割り当てます。未設定のカテゴリは既定の女性MCで生成されます。
        </p>
        <div className="mt-3 divide-y divide-slate-100">
          {data.categories.map((category) => {
            const value = assignments[category] ?? ''
            const selectId = `category-female-mc-${category}`
            return (
              <div key={category} className="flex items-center justify-between gap-3 py-2">
                <label htmlFor={selectId} className="text-sm text-slate-700">
                  {category}
                </label>
                <select
                  id={selectId}
                  value={value}
                  disabled={saving}
                  onChange={(e) => handleCategoryChange(category, e.target.value)}
                  aria-label={`${category}の女性MC`}
                  className="w-56 rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
                >
                  <option value="">{`未設定（既定: ${defaultVoiceLabel}）`}</option>
                  {data.voices.map((voice) => (
                    <option key={voice.value} value={voice.value}>
                      {voice.display_name}
                    </option>
                  ))}
                </select>
              </div>
            )
          })}
        </div>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {saving ? '保存中…' : '保存'}
          </button>
          <span className={`text-xs ${saveError ? 'text-rose-600' : 'text-slate-400'}`} aria-live="polite">
            {statusMessage}
          </span>
        </div>
      </div>
    </div>
  )
}
