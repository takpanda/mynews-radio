"use client"

import { useState, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { generateEpisode, fetchEpisode, type EpisodeListItem } from '../lib/api'

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

interface ProgressEntry {
  phase: PhaseCode
  message: string
  status?: string
  updatedAt?: number
}

interface PhasePresentation {
  title: string
  detail: string
  logLabel: string
  shortLabel: string
  progressPercent: number
}

const STATUS_TO_PHASE: Record<string, PhaseCode> = {
  generating: 'start',
  pending: 'start',
  start: 'start',
  import: 'import',
  summarize: 'summarize',
  generate_script: 'generate_script',
  review: 'review',
  review_done: 'review_done',
  synthesize: 'synthesize',
  build: 'build',
  db: 'db',
  review_synthesize: 'review_synthesize',
  review_build: 'review_build',
  review_complete: 'review_complete',
  complete: 'complete',
  failed: 'failed',
  // 後方互換用（status からマッピングする場合）
  importing: 'import',
  summarizing: 'summarize',
  generating_script: 'generate_script',
  reviewing: 'review',
  synthesizing: 'synthesize',
  building: 'build',
  saving: 'db',
  completed: 'complete',
  generating: 'start',
}

function mapStatusToPhase(episode: { status: string; generation_phase?: string }): PhaseCode {
  if (episode.generation_phase && episode.generation_phase in STATUS_TO_PHASE) {
    return STATUS_TO_PHASE[episode.generation_phase]
  }
  return STATUS_TO_PHASE[episode.status] || 'start'
}

const MESSAGE_BY_STATUS: Record<string, string> = {
  generating: '番組を生成中…',
  pending: '生成を開始しています…',
  importing: 'ニュース記事を取得しています…',
  summarizing: '記事を要約しています…',
  generating_script: '台本を生成しています…',
  reviewing: '台本をレビューしています…',
  synthesizing: '音声を合成しています…',
  building: '番組データを組み立てています…',
  saving: '保存しています…',
  completed: '生成が完了しました',
  failed: '生成に失敗しました',
}

const STEP_DEFINITIONS = [
  {
    phases: ['start', 'import'] as const,
    title: '記事を集める',
    description: '選択したソースから対象記事を取得します。',
    estimate: '20-40秒',
  },
  {
    phases: ['summarize'] as const,
    title: '内容を要約する',
    description: '番組向けに読みやすい要約へ整えます。',
    estimate: '30-60秒',
  },
  {
    phases: ['generate_script', 'review', 'review_done'] as const,
    title: '台本を作る',
    description: '記事構成を会話形式の台本に変換します。',
    estimate: '40-90秒',
  },
  {
    phases: ['synthesize', 'build', 'db', 'review_synthesize', 'review_build', 'review_complete', 'complete'] as const,
    title: '音声を合成する',
    description: '選択した音声エンジンで読み上げます。',
    estimate: '1-3分',
  },
] as const

const PHASE_PRESENTATION: Record<PhaseCode, PhasePresentation> = {
  start: {
    title: '生成を準備しています',
    detail: '番組データの作成を開始しています。',
    logLabel: '開始',
    shortLabel: '準備',
    progressPercent: 8,
  },
  import: {
    title: '記事を集めています',
    detail: '選択したニュースソースから候補を取得しています。',
    logLabel: '記事取得',
    shortLabel: '取得',
    progressPercent: 22,
  },
  summarize: {
    title: '要点を整理しています',
    detail: '番組で扱いやすい要約へ変換しています。',
    logLabel: '要約',
    shortLabel: '要約',
    progressPercent: 38,
  },
  generate_script: {
    title: '台本を組み立てています',
    detail: '記事構成を会話形式の流れに変換しています。',
    logLabel: '台本生成',
    shortLabel: '台本',
    progressPercent: 56,
  },
  review: {
    title: '台本を見直しています',
    detail: 'レビュー結果を確認して仕上げています。',
    logLabel: 'レビュー',
    shortLabel: '確認',
    progressPercent: 68,
  },
  review_done: {
    title: '台本確認が終わりました',
    detail: 'レビュー結果を反映して次の工程へ進みます。',
    logLabel: 'レビュー完了',
    shortLabel: '確認済み',
    progressPercent: 76,
  },
  synthesize: {
    title: '音声を作成しています',
    detail: '選択した音声エンジンで読み上げ音声を生成しています。',
    logLabel: '音声合成',
    shortLabel: '音声',
    progressPercent: 88,
  },
  build: {
    title: '音声をまとめています',
    detail: '番組として再生できる形に整えています。',
    logLabel: '音声統合',
    shortLabel: '統合',
    progressPercent: 94,
  },
  db: {
    title: '公開準備をしています',
    detail: 'エピソード情報を保存しています。',
    logLabel: '保存',
    shortLabel: '保存',
    progressPercent: 98,
  },
  review_synthesize: {
    title: 'レビュー版の音声を作成しています',
    detail: 'レビュー反映版もあわせて生成しています。',
    logLabel: 'レビュー版音声',
    shortLabel: '再音声',
    progressPercent: 92,
  },
  review_build: {
    title: 'レビュー版をまとめています',
    detail: 'レビュー反映版の公開データを整えています。',
    logLabel: 'レビュー版統合',
    shortLabel: '再統合',
    progressPercent: 96,
  },
  review_complete: {
    title: 'レビュー版が完成しました',
    detail: '本編の生成はそのまま継続または完了しています。',
    logLabel: 'レビュー版完了',
    shortLabel: '完了',
    progressPercent: 100,
  },
  complete: {
    title: '生成が完了しました',
    detail: '最新エピソードに反映しています。',
    logLabel: '完了',
    shortLabel: '完了',
    progressPercent: 100,
  },
  failed: {
    title: '生成で問題が発生しました',
    detail: '詳細はログを開いて確認できます。',
    logLabel: '失敗',
    shortLabel: '停止',
    progressPercent: 100,
  },
}

function getPhasePresentation(entry: ProgressEntry | undefined, hasFailure: boolean): PhasePresentation {
  if (hasFailure) {
    return PHASE_PRESENTATION.failed
  }

  if (!entry) {
    return {
      title: '開始を待っています',
      detail: '設定を選ぶと生成を開始できます。',
      logLabel: '待機',
      shortLabel: '待機',
      progressPercent: 0,
    }
  }

  if (entry.phase === 'review_done' && entry.status === 'skipped') {
    return {
      title: 'レビューをスキップしました',
      detail: '本編の生成は継続しています。',
      logLabel: 'レビュー省略',
      shortLabel: '省略',
      progressPercent: 76,
    }
  }

  return PHASE_PRESENTATION[entry.phase]
}

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

function getCurrentEstimate(activeStep: number, isSuccess: boolean, isFailure: boolean) {
  if (isSuccess) return '完了しました'
  if (isFailure) return 'ログを確認してください'
  if (activeStep < 0) return '通常 2-5 分'
  return STEP_DEFINITIONS[activeStep]?.estimate ?? '通常 2-5 分'
}

function optionCardClass(isSelected: boolean, isLoading: boolean) {
  if (isSelected) {
    return 'border-sky-500 bg-sky-50 shadow-[0_10px_25px_rgba(14,165,233,0.15)]'
  }

  return isLoading
    ? 'border-slate-200 bg-slate-50/70 opacity-70'
    : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
}

const STORAGE_KEY = 'generating_episode_id'

interface Props {
  episodes?: EpisodeListItem[]
}

export default function GenerateEpisodeButton({ episodes }: Props) {
  const [isLoading, setIsLoading] = useState(false)
  const [progress, setProgress] = useState<ProgressEntry[]>([])
  const [message, setMessage] = useState<string | null>(null)
  const [showLogs, setShowLogs] = useState(false)
  const [newsSource, setNewsSource] = useState<'hatena_bookmark' | 'hatena_hotentry_all' | 'yahoo_news'>('hatena_bookmark')
  const [recreateSummary, setRecreateSummary] = useState(false)
  const [ttsEngine, setTtsEngine] = useState<'voicevox' | 'aivispeech'>('aivispeech')
  const [enableReview, setEnableReview] = useState(false)
  const [maxArticles, setMaxArticles] = useState(10)
  const [episodeId, setEpisodeId] = useState<number | null>(null)
  const [hasError, setHasError] = useState(false)
  const router = useRouter()
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const isLoadingRef = useRef(false)
  const attemptCountRef = useRef(0)

  useEffect(() => {
    isLoadingRef.current = isLoading
  }, [isLoading])

  useEffect(() => {
    const checkAndResume = async () => {
      const storedId = localStorage.getItem(STORAGE_KEY)
      if (!storedId) return
      const id = Number(storedId)
      if (isNaN(id) || id <= 0) {
        localStorage.removeItem(STORAGE_KEY)
        return
      }
      try {
        const episode = await fetchEpisode(id)
        if (episode?.status === 'completed' || episode?.status === 'failed') {
          localStorage.removeItem(STORAGE_KEY)
          if (episode) {
            setEpisodeId(id)
            setIsLoading(false)
            setProgress([{ phase: mapStatusToPhase(episode), message: MESSAGE_BY_STATUS[episode.status] || '', status: episode.status }])
            setMessage(episode.status === 'completed' ? '生成が完了しました。' : '生成に失敗しました。')
            if (episode.status === 'failed') setHasError(true)
          }
          return
        }
      } catch {
        localStorage.removeItem(STORAGE_KEY)
        return
      }
      setEpisodeId(id)
      setIsLoading(true)
      setProgress([{ phase: 'start', message: '前回の生成を再開しています…' }])
    }
    checkAndResume()
  }, [])

  useEffect(() => {
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
        pollingRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    if (!episodeId || !isLoading) return

    const MAX_ATTEMPTS = 120
    attemptCountRef.current = 0
    let isCancelled = false

    const poll = async () => {
      if (isCancelled) return
      try {
        attemptCountRef.current += 1
        if (attemptCountRef.current > MAX_ATTEMPTS) {
          if (!isCancelled) {
            isCancelled = true
            localStorage.removeItem(STORAGE_KEY)
            setMessage('生成の確認がタイムアウトしました。ページを再読み込みしてください。')
            setHasError(true)
            setIsLoading(false)
          }
          return
        }
        const episode = await fetchEpisode(episodeId)
        if (!episode || isCancelled) return

        const phase = mapStatusToPhase(episode)
        const pollMessage = episode.generation_message || MESSAGE_BY_STATUS[episode.status] || ''
        setProgress((current) => {
          const last = current.at(-1)
          if (last && last.phase === phase) {
            // 同じフェーズ内でもメッセージとタイムスタンプを更新して「まだ動いている」ことを示す
            return [
              ...current.slice(0, -1),
              { ...last, message: pollMessage || last.message, updatedAt: Date.now() }
            ]
          }
          return [...current, { phase, message: pollMessage, status: episode.status, updatedAt: Date.now() }]
        })

        if (episode.status === 'completed') {
          isCancelled = true
          localStorage.removeItem(STORAGE_KEY)
          setMessage('生成が完了しました。')
          setIsLoading(false)
          if (pollingRef.current) {
            clearInterval(pollingRef.current)
            pollingRef.current = null
          }
          router.refresh()
        } else if (episode.status === 'failed') {
          isCancelled = true
          localStorage.removeItem(STORAGE_KEY)
          setMessage('生成に失敗しました。')
          setHasError(true)
          setIsLoading(false)
          if (pollingRef.current) {
            clearInterval(pollingRef.current)
            pollingRef.current = null
          }
        } else if (episode.status === 'pending') {
          // pending は生成が開始されていない、またはリセットされた状態
          localStorage.removeItem(STORAGE_KEY)
          setIsLoading(false)
          if (pollingRef.current) {
            clearInterval(pollingRef.current)
            pollingRef.current = null
          }
        }
      } catch {
        if (attemptCountRef.current > MAX_ATTEMPTS) {
          isCancelled = true
          localStorage.removeItem(STORAGE_KEY)
          setMessage('生成の確認に失敗しました。ページを再読み込みしてください。')
          setHasError(true)
          setIsLoading(false)
        }
      }
    }

    poll()
    pollingRef.current = setInterval(poll, 1000)

    return () => {
      isCancelled = true
      if (pollingRef.current) {
        clearInterval(pollingRef.current)
        pollingRef.current = null
      }
    }
  }, [episodeId, isLoading, router])

  const appendProgress = (entry: ProgressEntry) => {
    setProgress((current) => [...current, entry])
  }

  const stopPolling = useRef(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }).current

  const runGeneration = async () => {
    setIsLoading(true)
    setProgress([])
    setMessage(null)
    setShowLogs(false)
    setEpisodeId(null)
    setHasError(false)

    setTimeout(() => {
      const progressSection = document.getElementById('progress-section')
      if (progressSection) {
        progressSection.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    }, 100)

    try {
      const today = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Tokyo' })
      const { episode_id } = await generateEpisode(today, maxArticles, newsSource, ttsEngine, enableReview, recreateSummary)
      localStorage.setItem(STORAGE_KEY, String(episode_id))
      setEpisodeId(episode_id)
    } catch (error) {
      const msg = error instanceof Error ? error.message : '番組生成に失敗しました。'
      setMessage(msg)
      if (msg !== '既に生成中のタスクがあります') {
        setHasError(true)
      }
      setIsLoading(false)
    }
  }

  const handleClick = async () => {
    if (!isLoading && episodes?.some((ep) => ep.status === 'generating')) {
      setMessage('先に生成中のタスクがあります')
      return
    }
    await runGeneration()
  }

  const retryGeneration = async () => {
    await runGeneration()
  }

  const activeStep = resolveActiveStep(progress)
  const latestProgress = progress.at(-1)
  const isSuccess = Boolean(progress.some((entry) => entry.phase === 'complete'))
  const isFailure = Boolean(message && !isLoading && !isSuccess && hasError)
  const currentEstimate = getCurrentEstimate(activeStep, isSuccess, isFailure)
  const isDuplicateError = message === '先に生成中のタスクがあります'
  const phasePresentation = getPhasePresentation(latestProgress, isFailure)
  const visualProgressPercent = isFailure ? phasePresentation.progressPercent : phasePresentation.progressPercent
  const statusTone = isSuccess
    ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
    : isFailure
      ? 'border-amber-200 bg-amber-50 text-amber-800'
      : isDuplicateError
        ? 'border-amber-200 bg-amber-50 text-amber-800'
        : 'border-sky-200 bg-sky-50 text-sky-800'

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
            <div className="mt-3 grid gap-3 md:grid-cols-3">
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

              <label className={`block cursor-pointer rounded-2xl border p-4 transition ${optionCardClass(newsSource === 'yahoo_news', isLoading)}`}>
                <input
                  type="radio"
                  name="newsSource"
                  value="yahoo_news"
                  checked={newsSource === 'yahoo_news'}
                  onChange={() => setNewsSource('yahoo_news')}
                  disabled={isLoading}
                  className="sr-only"
                />
                <span className="flex items-start justify-between gap-3">
                  <span>
                    <span className="block text-sm font-semibold text-slate-900">Yahoo!ニュース</span>
                    <span className="mt-1 block text-xs leading-6 text-slate-500">
                      Yahoo!ニュース・トピックスの主要ニュースをお届けします。
                    </span>
                  </span>
                  <span className={`mt-1 h-4 w-4 rounded-full border ${newsSource === 'yahoo_news' ? 'border-sky-500 bg-sky-500 shadow-[0_0_0_4px_rgba(14,165,233,0.15)]' : 'border-slate-300 bg-white'}`} />
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

          <fieldset className="rounded-[1.5rem] border border-slate-200 bg-slate-50/70 p-4">
            <legend className="px-2 text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">
              Article Count
            </legend>
            <div className="mt-3 px-1">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-500">台本に使う記事数</span>
                <span className="min-w-[2rem] text-right text-sm font-semibold tabular-nums text-slate-900">{maxArticles} 件</span>
              </div>
              <input
                type="range"
                min={3}
                max={30}
                step={1}
                value={maxArticles}
                onChange={(e) => setMaxArticles(Number(e.target.value))}
                disabled={isLoading}
                className="mt-2 w-full accent-sky-500 disabled:opacity-50"
              />
              <div className="mt-1 flex justify-between text-[10px] text-slate-400">
                <span>3</span>
                <span>30</span>
              </div>
            </div>
          </fieldset>

          <fieldset className="rounded-[1.5rem] border border-slate-200 bg-slate-50/70 p-4">
            <legend className="px-2 text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">
              Script Review
            </legend>
            <label className={`mt-3 block cursor-pointer rounded-2xl border p-4 transition ${optionCardClass(enableReview, isLoading)}`}>
              <input
                type="checkbox"
                checked={enableReview}
                onChange={(e) => setEnableReview(e.target.checked)}
                disabled={isLoading}
                className="sr-only"
              />
              <span className="flex items-start justify-between gap-3">
                <span>
                  <span className="block text-sm font-semibold text-slate-900">台本をレビューする</span>
                  <span className="mt-1 block text-xs leading-6 text-slate-500">
                    4人のディレクターが台本をチェックし、修正版を別エピソードとして生成します。処理時間が増えます。
                  </span>
                </span>
                <span className={`mt-1 flex h-4 w-4 shrink-0 items-center justify-center rounded border ${enableReview ? 'border-sky-500 bg-sky-500 shadow-[0_0_0_4px_rgba(14,165,233,0.15)]' : 'border-slate-300 bg-white'}`}>
                  {enableReview && (
                    <svg className="h-2.5 w-2.5 text-white" viewBox="0 0 10 8" fill="none">
                      <path d="M1 4l3 3 5-6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </span>
              </span>
            </label>

              <label className={`mt-3 block cursor-pointer rounded-2xl border p-4 transition ${optionCardClass(recreateSummary, isLoading)}`}>
                <input
                  type="checkbox"
                  checked={recreateSummary}
                  onChange={(e) => setRecreateSummary(e.target.checked)}
                  disabled={isLoading}
                  className="sr-only"
                />
                <span className="flex items-start justify-between gap-3">
                  <span>
                    <span className="block text-sm font-semibold text-slate-900">要約を再作成する</span>
                    <span className="mt-1 block text-xs leading-6 text-slate-500">
                      既存の要約を破棄して、再度生成します。
                    </span>
                  </span>
                  <span className={`mt-1 flex h-4 w-4 shrink-0 items-center justify-center rounded border ${recreateSummary ? 'border-sky-500 bg-sky-500 shadow-[0_0_0_4px_rgba(14,165,233,0.15)]' : 'border-slate-300 bg-white'}`}>
                    {recreateSummary && (
                      <svg className="h-2.5 w-2.5 text-white" viewBox="0 0 10 8" fill="none">
                        <path d="M1 4l3 3 5-6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    )}
                  </span>
                </span>
              </label>
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
            <div>
              <dt className="text-xs uppercase tracking-[0.16em] text-slate-400">記事数</dt>
              <dd className="mt-1 font-medium text-slate-900">{maxArticles} 件</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-[0.16em] text-slate-400">レビュー</dt>
              <dd className="mt-1 font-medium text-slate-900">
                {enableReview ? '有効（修正版も生成）' : '無効'}
              </dd>
            </div>
            <div className="mt-3 rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
              <dt className="text-xs uppercase tracking-[0.16em] text-slate-400">要約の再作成</dt>
              <dd className="mt-1 font-medium text-slate-900">
                {recreateSummary ? '有効' : '無効'}
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

      {(progress.length > 0 || message || isDuplicateError) && (
        <div id="progress-section" className="mt-5 rounded-[1.5rem] border border-slate-200 bg-slate-50/80 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Progress</p>
              <p className="mt-2 text-sm font-medium text-slate-900">
                {phasePresentation.title}
              </p>
              <p className="mt-1 text-xs leading-6 text-slate-500">{phasePresentation.detail}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600">
                目安 {currentEstimate}
              </span>
              {(isLoading || message) && (
                <span className={`inline-flex rounded-full border px-3 py-1 text-xs font-medium ${statusTone}`}>
                  {isLoading ? '生成中' : isSuccess ? '完了' : isDuplicateError ? '重複' : '確認が必要'}
                </span>
              )}
            </div>
          </div>

          <div className="mt-4 rounded-2xl border border-white/80 bg-white/90 p-3 shadow-sm">
            <div className="flex items-center justify-between gap-3 text-xs font-medium text-slate-500">
              <span className="inline-flex items-center gap-2">
                <span className={`flex h-8 min-w-8 items-center justify-center rounded-full px-2 text-[11px] font-semibold ${isSuccess ? 'bg-emerald-100 text-emerald-700' : isFailure ? 'bg-amber-100 text-amber-700' : 'bg-sky-100 text-sky-700'}`}>
                  {phasePresentation.shortLabel}
                </span>
                <span>{isFailure ? '進行が中断されました' : isDuplicateError ? '生成できません' : '工程の進み具合'}</span>
              </span>
              <span className="tabular-nums text-slate-700">{visualProgressPercent}%</span>
            </div>

            <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200">
              <div
                className={`relative h-full rounded-full transition-all duration-500 ${isSuccess ? 'bg-emerald-500' : isFailure ? 'bg-amber-500' : 'bg-[linear-gradient(90deg,#38bdf8,#14b8a6)] progress-shimmer'}`}
                style={{ width: `${visualProgressPercent}%` }}
              />
            </div>

            <div className="mt-3 grid grid-cols-4 gap-2">
              {STEP_DEFINITIONS.map((step, index) => {
                const isComplete = activeStep > index || isSuccess
                const isCurrent = !isSuccess && activeStep === index
                const markerTone = isComplete
                  ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                  : isCurrent
                    ? 'border-sky-200 bg-sky-50 text-sky-700'
                    : 'border-slate-200 bg-white text-slate-400'

                return (
                  <div key={`summary-${step.title}`} className={`rounded-2xl border px-3 py-2 transition ${markerTone} ${isCurrent ? 'progress-breathe' : ''}`}>
                    <p className="text-[11px] font-semibold uppercase tracking-[0.16em] opacity-80">
                      {index + 1}
                    </p>
                    <p className="mt-1 text-xs font-medium leading-5">{step.title}</p>
                    <p className="mt-1 text-[11px] leading-5 opacity-75">{step.estimate}</p>
                  </div>
                )
              })}
            </div>
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
                <li key={step.title} className={`flex items-start gap-3 rounded-2xl border p-3 transition ${tone} ${isCurrent ? 'shadow-[0_12px_24px_rgba(14,165,233,0.12)]' : ''}`}>
                  <span className={`mt-0.5 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full border text-xs font-semibold ${isComplete ? 'border-emerald-300 bg-emerald-500 text-white' : isCurrent ? 'border-sky-300 bg-sky-500 text-white progress-breathe' : 'border-slate-200 bg-slate-100 text-slate-500'}`}>
                    {index + 1}
                  </span>
                  <span>
                    <span className="block text-sm font-semibold">{step.title}</span>
                    <span className="mt-1 block text-xs leading-6 opacity-80">{step.description}</span>
                    <span className="mt-1 block text-[11px] leading-5 opacity-70">目安 {step.estimate}</span>
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
                        {entry.status === 'skipped' && entry.phase === 'review_done'
                          ? 'レビュー省略'
                          : PHASE_PRESENTATION[entry.phase].logLabel}
                      </p>
                      <p className="mt-1">{entry.message}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {message ? (
            <div className={`mt-4 rounded-2xl border p-3 text-sm ${isSuccess ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : isDuplicateError ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-amber-200 bg-amber-50 text-amber-800'}`}>
              {isSuccess
                ? 'エピソードを更新しました。最新エピソードから再生できます。'
                : isDuplicateError
                  ? '先に生成中のタスクがあります。完了をお待ちください。'
                  : message || '生成を完了できませんでした。必要に応じてログを開いて詳細を確認してください。'}
            </div>
          ) : null}

          {hasError && !isSuccess && (
            <button
              type="button"
              onClick={retryGeneration}
              disabled={isLoading}
              className="mt-3 inline-flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-2 text-sm font-medium text-amber-700 transition hover:bg-amber-100 disabled:opacity-50"
            >
              再試行
            </button>
          )}
        </div>
      )}
    </section>
  )
}
