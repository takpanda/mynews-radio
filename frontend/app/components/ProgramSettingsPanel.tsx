'use client'

import { useEffect, useState } from 'react'
import {
  fetchProgramSettings,
  resetProgramSettings,
  saveProgramSettings,
  type ProgramSettings,
  type ProgramTheme,
} from '../lib/api'

const THEMES: Array<{ value: ProgramTheme; label: string }> = [
  { value: 'technology', label: 'テクノロジー' },
  { value: 'business', label: 'ビジネス' },
  { value: 'society', label: '社会' },
  { value: 'sports', label: 'スポーツ' },
  { value: 'entertainment', label: 'エンタメ' },
  { value: 'general', label: '一般' },
]

const DURATIONS: Array<{ value: ProgramSettings['duration_preset']; label: string; detail: string }> = [
  { value: 'short', label: '短め', detail: '約6記事' },
  { value: 'normal', label: '標準', detail: '約10記事' },
  { value: 'long', label: 'しっかり', detail: '約14記事' },
]

const DEFAULT_SETTINGS: ProgramSettings = { priority_themes: [], excluded_themes: [], duration_preset: 'normal' }

interface Props { disabled?: boolean; onChange?: (settings: ProgramSettings) => void }

export default function ProgramSettingsPanel({ disabled = false, onChange }: Props) {
  const [settings, setSettings] = useState<ProgramSettings>(DEFAULT_SETTINGS)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [failedSettings, setFailedSettings] = useState<ProgramSettings | null>(null)
  const authRequired = error?.includes('ログインが必要') ?? false

  useEffect(() => {
    fetchProgramSettings().then((value) => { setSettings(value); onChange?.(value) }).catch((err) => {
      setError(err instanceof Error && err.message.includes('ログインが必要')
        ? err.message
        : '設定を読み込めません。標準設定で生成できます。')
    }).finally(() => setLoading(false))
  }, [])

  const update = async (next: ProgramSettings) => {
    setSettings(next)
    onChange?.(next)
    setFailedSettings(null)
    setSaving(true); setSaved(false); setError(null)
    try { const savedSettings = await saveProgramSettings(next); setSettings(savedSettings); onChange?.(savedSettings); setSaved(true) }
    catch (err) { setFailedSettings(next); setError(err instanceof Error ? err.message : '設定を保存できませんでした') }
    finally { setSaving(false) }
  }

  const toggleTheme = (theme: ProgramTheme, kind: 'priority_themes' | 'excluded_themes') => {
    const current = settings[kind]
    const exists = current.includes(theme)
    if (exists) return update({ ...settings, [kind]: current.filter((item) => item !== theme) })
    if (kind === 'priority_themes' && current.length >= 3) return
    const other = kind === 'priority_themes' ? 'excluded_themes' : 'priority_themes'
    if (settings[other].includes(theme)) return
    return update({ ...settings, [kind]: [...current, theme] })
  }

  const reset = async () => {
    setSaving(true); setSaved(false); setError(null)
    setFailedSettings(null)
    try { const value = await resetProgramSettings(); setSettings(value); onChange?.(value); setSaved(true) }
    catch (err) { setError(err instanceof Error ? err.message : '設定を初期化できませんでした') }
    finally { setSaving(false) }
  }

  const retry = () => failedSettings && update(failedSettings)

  return (
    <fieldset className="rounded-xl border border-slate-200 bg-slate-50/70 p-3" disabled={disabled || loading || saving || authRequired}>
      <legend className="px-1 text-sm font-medium text-slate-900">番組設定</legend>
      <p className="mt-1 text-xs leading-5 text-slate-500">次回生成から自動で反映されます。テーマは最大3つまで。</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div>
          <p className="text-xs font-medium text-slate-700">優先テーマ</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {THEMES.map((theme) => <button key={theme.value} type="button" onClick={() => toggleTheme(theme.value, 'priority_themes')} className={`rounded-full border px-2.5 py-1 text-xs transition ${settings.priority_themes.includes(theme.value) ? 'border-sky-500 bg-sky-50 text-sky-700' : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300'}`}>{theme.label}</button>)}
          </div>
        </div>
        <div>
          <p className="text-xs font-medium text-slate-700">除外テーマ</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {THEMES.map((theme) => <button key={theme.value} type="button" onClick={() => toggleTheme(theme.value, 'excluded_themes')} className={`rounded-full border px-2.5 py-1 text-xs transition ${settings.excluded_themes.includes(theme.value) ? 'border-rose-400 bg-rose-50 text-rose-700' : 'border-slate-200 bg-white text-slate-500 hover:border-slate-300'}`}>{theme.label}</button>)}
          </div>
        </div>
      </div>
      <div className="mt-3">
        <p className="text-xs font-medium text-slate-700">番組の尺</p>
        <div className="mt-1.5 grid grid-cols-3 gap-1.5">
          {DURATIONS.map((duration) => <button key={duration.value} type="button" onClick={() => update({ ...settings, duration_preset: duration.value })} className={`rounded-lg border px-2 py-2 text-left transition ${settings.duration_preset === duration.value ? 'border-sky-500 bg-sky-50' : 'border-slate-200 bg-white hover:border-slate-300'}`}><span className="block text-xs font-medium text-slate-800">{duration.label}</span><span className="mt-0.5 block text-[10px] text-slate-400">{duration.detail}</span></button>)}
        </div>
      </div>
      <div className="mt-2 flex min-h-5 items-center justify-between gap-2 text-xs" aria-live="polite">
        <span className={error ? 'text-rose-600' : 'text-slate-400'}>
          {loading ? '設定を読み込み中…' : error ? (
            <>
              {error}
              {error.includes('ログインが必要') && <a href="/admin/login" className="ml-2 underline hover:text-rose-800">ログインする</a>}
            </>
          ) : saving ? '保存中…' : saved ? '保存しました' : '未設定なら標準設定で生成'}
        </span>
        {failedSettings && <button type="button" onClick={retry} className="shrink-0 rounded-md border border-rose-200 bg-white px-2 py-1 text-rose-700 transition hover:bg-rose-50">再試行</button>}
        <button type="button" onClick={reset} disabled={settings.priority_themes.length === 0 && settings.excluded_themes.length === 0 && settings.duration_preset === 'normal'} className="shrink-0 text-slate-500 underline decoration-slate-300 underline-offset-2 transition hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-40">初期化</button>
      </div>
    </fieldset>
  )
}
