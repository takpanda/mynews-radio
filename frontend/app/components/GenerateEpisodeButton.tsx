"use client"

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { generateEpisodeStream } from '../lib/api'

type PhaseCode =
  | 'start'
  | 'import'
  | 'summarize'
  | 'generate_script'
  | 'review'
  | 'review_done'
  | 'synthesize'
  | 'build'
  | 'db'
  | 'review_synthesize'
  | 'review_build'
  | 'review_complete'
  | 'complete'
  | 'failed'

interface ProgressPayload {
  phase?: PhaseCode
  message?: string
  status?: string
  step_index?: number
  step_total?: number
  step_label?: string
  episode_id?: number
}

interface ProgressEntry {
  phase: PhaseCode
  message: string
  status?: string
}

const STEP_DEFINITIONS = [
  {
    phases: ['start', 'import'] as const,
    title: '記事を集める',
    description: '選択したソースから対象記事を取得します。',
  },
  {
    phases: ['summarize'] as const,
    title: '内容を要約する',
    description: '番組向けに読みやすい要約へ整えます。',
  },
  {
    phases: ['generate_script', 'review', 'review_done'] as const,
    title: '台本を作る',
    description: '記事構成を会話形式の台本に変換します。',
  },
  {
    phases: ['synthesize', 'build', 'db', 'review_synthesize', 'review_build', 'review_complete', 'complete'] as const,
    title: '音声を合成する',
    description: '選択した音声エンジンで読み上げます。',
  },
] as const

function resolveActiveStep(progress: ProgressEntry[]) {
  let activeIndex = -1

  progress.forEach((entry) => {
    const matchedIndex = STEP_DEFINITIONS.findIndex((step) =>
      step.phases.some((phase) => phase === entry.phase),
    )
    if (matchedIndex >= 0) {
      activeIndex = Math.max(activeIndex, matchedIndex)
    }
  })

  return activeIndex
}

function optionCardClass(isSelected: boolean, isLoading: boolean) {
  if (isSelected) {
    return 'border-sky-500 bg-sky-50 shadow-[0_10px_25px_rgba(14,165,233,0.15)]'
  }

  return isLoading
    ? 'border-slate-200 bg-slate-50/70 opacity-70'
    : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
}

function parseSseChunk(chunk: string) {
  const lines = chunk.split('\n')
  const eventLine = lines.find((line) => line.startsWith('event:'))
  const dataLines = lines.filter((line) => line.startsWith('data:'))
  const event = eventLine ? eventLine.slice('event:'.length).trim() : 'message'
  const data = dataLines.map((line) => line.slice('data:'.length)).join('\n')

  try {
    return { event, payload: JSON.parse(data) as ProgressPayload }
  } catch {
    return { event, payload: null }
  }
}

export default function GenerateEpisodeButton() {
  const [isLoading, setIsLoading] = useState(false)
  const [progress, setProgress] = useState<ProgressEntry[]>([])
  const [message, setMessage] = useState<string | null>(null)
  const [showLogs, setShowLogs] = useState(false)
  const [newsSource, setNewsSource] = useState<'hatena_bookmark' | 'hatena_hotentry_all'>('hatena_bookmark')
  const [ttsEngine, setTtsEngine] = useState<'voicevox' | 'aivispeech'>('aivispeech')
  const router = useRouter()

  const appendProgress = (entry: ProgressEntry) => {
    setProgress((current) => [...current, entry])
  }

  const activeStep = resolveActiveStep(progress)
  const latestProgress = progress.at(-1)
  const isSuccess = Boolean(progress.some((entry) => entry.phase === 'complete'))
  const isFailure = Boolean(message && !isLoading && !isSuccess)
  const statusTone = isSuccess
    ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
    : isFailure
      ? 'border-amber-200 bg-amber-50 text-amber-800'
      : 'border-sky-200 bg-sky-50 text-sky-800'

  const handleClick = async () => {
    setIsLoading(true)
    setProgress([])
    setMessage(null)
    setShowLogs(false)

    try {
      const today = new Date().toISOString().slice(0, 10)
      const response = await generateEpisodeStream(today, 10, newsSource, ttsEngine)

      if (!response.ok) {
        const errorText = await response.text().catch(() => '')
        setMessage(errorText || '番組生成に失敗しました。')
        return
      }

      const reader = response.body?.getReader()
      if (!reader) {
        setMessage('ストリームを受信できませんでした。')
        return
      }

      const decoder = new TextDecoder('utf-8')
      let buffer = ''
      let isCompleted = false

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const chunks = buffer.split('\n\n')
        buffer = chunks.pop() ?? ''

        for (const chunk of chunks) {
          const trimmed = chunk.trim()
          if (!trimmed) continue
          const { event, payload } = parseSseChunk(trimmed)
          if (!payload) continue

          if (event === 'progress') {
            appendProgress({
              phase: payload.phase ?? 'start',
              message: payload.message ?? '進捗更新',
              status: payload.status,
            })
          } else if (event === 'complete') {
            setMessage(payload.message ?? '生成が完了しました。')
            appendProgress({
              phase: payload.phase ?? 'complete',
              message: payload.message ?? '生成が完了しました。',
              status: payload.status,
            })
            isCompleted = true
          } else if (event === 'error') {
            setMessage(payload.message ?? 'エラーが発生しました。')
            appendProgress({
              phase: payload.phase ?? 'failed',
              message: payload.message ?? 'エラーが発生しました。',
              status: payload.status,
            })
            isCompleted = true
          }
        }

        if (isCompleted) {
          break
        }
      }

      if (isCompleted) {
        router.refresh()
      }
    } catch (error) {
      setMessage('通信エラーが発生しました。後でもう一度お試しください。')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <section className="rounded-[1.75rem] border border-slate-200/80 bg-white/90 p-4 shadow-[0_18px_50px_rgba(15,23,42,0.08)] backdrop-blur sm:p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">
            Generate Episode
          </p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-950">今日の番組を生成</h2>
        </div>
        <span className="inline-flex rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-600">
          通常 2-5 分
        </span>
      </div>

      <p className="mt-3 text-sm leading-7 text-slate-600">
        ニュースの種類と読み上げエンジンを選ぶと、取得から音声化までの進行をこの場で確認できます。
      </p>

      <div className="mt-5 grid gap-4 2xl:grid-cols-[minmax(0,1fr)_220px]">
        <div className="space-y-4">
          <fieldset className="rounded-[1.5rem] border border-slate-200 bg-slate-50/70 p-4">
            <legend className="px-2 text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">
              News Source
            </legend>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <label className={`block cursor-pointer rounded-2xl border p-4 transition ${optionCardClass(newsSource === 'hatena_bookmark', isLoading)}`}>
                <input
                  type="radio"
                  name="newsSource"
                  value="hatena_bookmark"
                  checked={newsSource === 'hatena_bookmark'}
                  onChange={() => setNewsSource('hatena_bookmark')}
                  disabled={isLoading}
                  className="sr-only"
                />
                <span className="flex items-start justify-between gap-3">
                  <span>
                    <span className="block text-sm font-semibold text-slate-900">テックニュース</span>
                    <span className="mt-1 block text-xs leading-6 text-slate-500">
                      はてなブックマークのテック面を中心に収集します。
                    </span>
                  </span>
                  <span className={`mt-1 h-4 w-4 rounded-full border ${newsSource === 'hatena_bookmark' ? 'border-sky-500 bg-sky-500 shadow-[0_0_0_4px_rgba(14,165,233,0.15)]' : 'border-slate-300 bg-white'}`} />
                </span>
              </label>

              <label className={`block cursor-pointer rounded-2xl border p-4 transition ${optionCardClass(newsSource === 'hatena_hotentry_all', isLoading)}`}>
                <input
                  type="radio"
                  name="newsSource"
                  value="hatena_hotentry_all"
                  checked={newsSource === 'hatena_hotentry_all'}
                  onChange={() => setNewsSource('hatena_hotentry_all')}
                  disabled={isLoading}
                  className="sr-only"
                />
                <span className="flex items-start justify-between gap-3">
                  <span>
                    <span className="block text-sm font-semibold text-slate-900">一般ニュース</span>
                    <span className="mt-1 block text-xs leading-6 text-slate-500">
                      幅広い話題をまとめて、日次のダイジェストとして届けます。
                    </span>
                  </span>
                  <span className={`mt-1 h-4 w-4 rounded-full border ${newsSource === 'hatena_hotentry_all' ? 'border-sky-500 bg-sky-500 shadow-[0_0_0_4px_rgba(14,165,233,0.15)]' : 'border-slate-300 bg-white'}`} />
                </span>
              </label>
            </div>
          </fieldset>

          <fieldset className="rounded-[1.5rem] border border-slate-200 bg-slate-50/70 p-4">
            <legend className="px-2 text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">
              Voice Engine
            </legend>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <label className={`block cursor-pointer rounded-2xl border p-4 transition ${optionCardClass(ttsEngine === 'voicevox', isLoading)}`}>
                <input
                  type="radio"
                  name="ttsEngine"
                  value="voicevox"
                  checked={ttsEngine === 'voicevox'}
                  onChange={() => setTtsEngine('voicevox')}
                  disabled={isLoading}
                  className="sr-only"
                />
                <span className="flex items-start justify-between gap-3">
                  <span>
                    <span className="block text-sm font-semibold text-slate-900">VOICEVOX</span>
                    <span className="mt-1 block text-xs leading-6 text-slate-500">
                      安定した読み上げで、通常の番組生成に向いています。
                    </span>
                  </span>
                  <span className={`mt-1 h-4 w-4 rounded-full border ${ttsEngine === 'voicevox' ? 'border-sky-500 bg-sky-500 shadow-[0_0_0_4px_rgba(14,165,233,0.15)]' : 'border-slate-300 bg-white'}`} />
                </span>
              </label>

              <label className={`block cursor-pointer rounded-2xl border p-4 transition ${optionCardClass(ttsEngine === 'aivispeech', isLoading)}`}>
                <input
                  type="radio"
                  name="ttsEngine"
                  value="aivispeech"
                  checked={ttsEngine === 'aivispeech'}
                  onChange={() => setTtsEngine('aivispeech')}
                  disabled={isLoading}
                  className="sr-only"
                />
                <span className="flex items-start justify-between gap-3">
                  <span>
                    <span className="block text-sm font-semibold text-slate-900">AivisSpeech</span>
                    <span className="mt-1 block text-xs leading-6 text-slate-500">
                      音声差分を試したいときの代替エンジンです。
                    </span>
                  </span>
                  <span className={`mt-1 h-4 w-4 rounded-full border ${ttsEngine === 'aivispeech' ? 'border-sky-500 bg-sky-500 shadow-[0_0_0_4px_rgba(14,165,233,0.15)]' : 'border-slate-300 bg-white'}`} />
                </span>
              </label>
            </div>
          </fieldset>

          <button
            type="button"
            onClick={handleClick}
            disabled={isLoading}
            className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-2xl bg-[linear-gradient(135deg,#0f172a,#0f766e)] px-5 py-3 text-sm font-semibold text-white shadow-[0_16px_35px_rgba(15,23,42,0.25)] transition hover:translate-y-[-1px] hover:shadow-[0_20px_40px_rgba(15,23,42,0.3)] disabled:translate-y-0 disabled:cursor-not-allowed disabled:opacity-70"
          >
            <span className={`h-2.5 w-2.5 rounded-full bg-white/90 ${isLoading ? 'animate-pulse' : ''}`} />
            {isLoading ? '生成を進めています…' : 'この設定で番組を生成する'}
          </button>
        </div>

        <aside className="rounded-[1.5rem] border border-slate-200 bg-[linear-gradient(180deg,rgba(248,250,252,0.95),rgba(255,255,255,0.95))] p-4">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">今回の設定</p>
          <dl className="mt-4 space-y-3 text-sm text-slate-600">
            <div>
              <dt className="text-xs uppercase tracking-[0.16em] text-slate-400">ソース</dt>
              <dd className="mt-1 font-medium text-slate-900">
                {newsSource === 'hatena_bookmark' ? 'テックニュース' : '一般ニュース'}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.16em] text-slate-400">音声</dt>
              <dd className="mt-1 font-medium text-slate-900">
                {ttsEngine === 'voicevox' ? 'VOICEVOX' : 'AivisSpeech'}
              </dd>
            </div>
          </dl>

          <div className="mt-5 rounded-2xl bg-slate-900 px-4 py-3 text-sm text-slate-50">
            <p className="font-medium">生成の流れ</p>
            <p className="mt-2 text-xs leading-6 text-slate-300">
              記事取得 → 要約 → 台本生成 → 音声合成の順で処理します。
            </p>
          </div>
        </aside>
      </div>

      {(progress.length > 0 || message) && (
        <div className="mt-5 rounded-[1.5rem] border border-slate-200 bg-slate-50/80 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Progress</p>
              <p className="mt-2 text-sm font-medium text-slate-900">
                {latestProgress?.message || (message ? '処理結果を表示しています。' : '開始を待っています。')}
              </p>
            </div>
            {(isLoading || message) && (
              <span className={`inline-flex rounded-full border px-3 py-1 text-xs font-medium ${statusTone}`}>
                {isLoading ? '生成中' : isSuccess ? '完了' : '確認が必要'}
              </span>
            )}
          </div>

          <ol className="mt-4 space-y-3" aria-live="polite">
            {STEP_DEFINITIONS.map((step, index) => {
              const isComplete = activeStep > index || isSuccess
              const isCurrent = !isSuccess && activeStep === index
              const tone = isComplete
                ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                : isCurrent
                  ? 'border-sky-200 bg-sky-50 text-sky-700'
                  : 'border-slate-200 bg-white text-slate-400'

              return (
                <li key={step.title} className={`flex items-start gap-3 rounded-2xl border p-3 transition ${tone}`}>
                  <span className={`mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full border text-xs font-semibold ${isComplete ? 'border-emerald-300 bg-emerald-500 text-white' : isCurrent ? 'border-sky-300 bg-sky-500 text-white' : 'border-slate-200 bg-slate-100 text-slate-500'}`}>
                    {index + 1}
                  </span>
                  <span>
                    <span className="block text-sm font-semibold">{step.title}</span>
                    <span className="mt-1 block text-xs leading-6 opacity-80">{step.description}</span>
                  </span>
                </li>
              )
            })}
          </ol>

          {progress.length > 0 && (
            <div className="mt-4 rounded-2xl border border-white/80 bg-white/90 p-3 text-sm text-slate-700 shadow-sm">
              <button
                type="button"
                onClick={() => setShowLogs((current) => !current)}
                className="flex w-full items-center justify-between gap-3 text-left"
                aria-expanded={showLogs}
              >
                <span>
                  <span className="block text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">ログ</span>
                  <span className="mt-1 block text-xs leading-6 text-slate-500">
                    {showLogs ? 'ログを閉じる' : '必要なときだけログを表示'}
                  </span>
                </span>
                <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-600">
                  {showLogs ? '隠す' : '表示'}
                </span>
              </button>

              {showLogs && (
                <div className="mt-3 space-y-2">
                  {progress.map((entry, index) => (
                    <div key={`${entry.phase}-${index}`} className="rounded-xl bg-slate-50 px-3 py-2.5 leading-6">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
                        {entry.phase}
                      </p>
                      <p className="mt-1">{entry.message}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {message ? (
            <div className={`mt-4 rounded-2xl border p-3 text-sm ${isSuccess ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-amber-200 bg-amber-50 text-amber-800'}`}>
              {message}
            </div>
          ) : null}
        </div>
      )}
    </section>
  )
}
