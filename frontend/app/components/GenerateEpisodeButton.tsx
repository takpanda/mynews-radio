"use client"

import { useState, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'react-hot-toast'
import { generateEpisode, fetchEpisode, searchEpisodesBySourceUrl, type EpisodeListItem, type DuplicateEpisodeInfo } from '../lib/api'
import DuplicateUrlConfirmDialog from './DuplicateUrlConfirmDialog'

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

function optionCardClass(isSelected: boolean, isLoading: boolean, isDisabled = false) {
  if (isSelected) {
    return 'border-sky-500 bg-sky-50'
  }

  if (isLoading || isDisabled) {
    return 'border-slate-200 bg-slate-50 opacity-60'
  }

  return 'border-slate-200 bg-white hover:border-slate-300'
}

function RadioDot({ checked }: { checked: boolean }) {
  return (
    <span
      className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
        checked ? 'border-sky-500' : 'border-slate-300'
      }`}
    >
      {checked && <span className="h-2 w-2 rounded-full bg-sky-500" />}
    </span>
  )
}

interface GenerationParams {
  url: string
  newsSource: 'hatena_bookmark' | 'hatena_hotentry_all' | 'yahoo_news'
  commentaryStyle: 'solo' | 'dialogue'
  mcGender: 'male' | 'female'
  ttsEngine: 'voicevox' | 'aivispeech'
  maxArticles: number
  recreateSummary: boolean
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
  const [maxArticles, setMaxArticles] = useState(10)
  const [episodeId, setEpisodeId] = useState<number | null>(null)
  const [hasError, setHasError] = useState(false)
  const [urlInput, setUrlInput] = useState('')
  const [commentaryStyle, setCommentaryStyle] = useState<'solo' | 'dialogue'>('solo')
  const [mcGender, setMcGender] = useState<'male' | 'female'>('male')
  const [urlError, setUrlError] = useState<string | null>(null)
  const [isCheckingDuplicate, setIsCheckingDuplicate] = useState(false)
  const [duplicateDialog, setDuplicateDialog] = useState<{
    type: 'duplicate-found' | 'search-error'
    episodes: DuplicateEpisodeInfo[]
    snapshot: GenerationParams
  } | null>(null)
  const router = useRouter()
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const isLoadingRef = useRef(false)
  const attemptCountRef = useRef(0)
  const consecutiveFailuresRef = useRef(0)
  const shouldScrollToProgress = useRef(false)

  const isUrlMode = urlInput.trim().length > 0

  const isValidUrl = (value: string): boolean =>
    value === '' || /^https?:\/\/.+/.test(value)

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

    const INTERVAL_MS = 5000
    const MAX_ATTEMPTS = 800
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
        consecutiveFailuresRef.current = 0

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
          // フェーズが変わったタイミングでプログレスセクションにスクロール
          if (shouldScrollToProgress.current) {
            setTimeout(() => {
              const progressSection = document.getElementById('progress-section')
              if (progressSection && typeof progressSection.scrollIntoView === 'function') {
                progressSection.scrollIntoView({ behavior: 'smooth', block: 'center' })
              }
            }, 200)
            shouldScrollToProgress.current = false
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
          toast.success('番組の生成が完了しました！', { icon: '✅' })
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
        consecutiveFailuresRef.current += 1
        const CONSECUTIVE_ERROR_THRESHOLD = 5
        if (consecutiveFailuresRef.current >= CONSECUTIVE_ERROR_THRESHOLD || attemptCountRef.current > MAX_ATTEMPTS) {
          isCancelled = true
          localStorage.removeItem(STORAGE_KEY)
          setMessage('生成の確認に失敗しました。ページを再読み込みしてください。')
          setHasError(true)
          setIsLoading(false)
        }
      }
    }

    poll()
    pollingRef.current = setInterval(poll, INTERVAL_MS)

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

  const runGeneration = async (params?: GenerationParams) => {
    const url = params ? params.url : (isUrlMode ? urlInput.trim() : undefined)
    const source = params ? params.newsSource : newsSource
    const style = params ? params.commentaryStyle : commentaryStyle
    const gender = params ? params.mcGender : mcGender
    const engine = params ? params.ttsEngine : ttsEngine
    const articles = params ? params.maxArticles : maxArticles
    const recreate = params ? params.recreateSummary : recreateSummary

    setIsLoading(true)
    setProgress([{ phase: 'start', message: '番組の生成を準備しています…', updatedAt: Date.now() }])
    setMessage(null)
    setShowLogs(false)
    setEpisodeId(null)
    setHasError(false)
    setUrlError(null)
    shouldScrollToProgress.current = true
    setTimeout(() => {
      const progressSection = document.getElementById('progress-section')
      if (progressSection && typeof progressSection.scrollIntoView === 'function') {
        progressSection.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    }, 200)
    consecutiveFailuresRef.current = 0

    try {
      const today = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Tokyo' })
      const { episode_id } = await generateEpisode(today, articles, source, engine, recreate, url, url ? style : undefined, url && style === 'solo' ? gender : undefined)
      localStorage.setItem(STORAGE_KEY, String(episode_id))
      setEpisodeId(episode_id)
      toast('番組の生成を開始しました', { icon: '🎙️' })
    } catch (error) {
      const msg = error instanceof Error ? error.message : '番組生成に失敗しました。'
      setMessage(msg)
      if (msg !== '既に生成中のタスクがあります') {
        setHasError(true)
      }
      setIsLoading(false)
    }
  }

  const checkDuplicateAndRun = async () => {
    const snapshot: GenerationParams = {
      url: urlInput.trim(),
      newsSource,
      commentaryStyle,
      mcGender,
      ttsEngine,
      maxArticles,
      recreateSummary,
    }
    setIsCheckingDuplicate(true)
    setDuplicateDialog(null)
    try {
      const episodes = await searchEpisodesBySourceUrl(snapshot.url)
      if (episodes.length > 0) {
        setDuplicateDialog({ type: 'duplicate-found', episodes, snapshot })
      } else {
        await runGeneration(snapshot)
      }
    } catch {
      setDuplicateDialog({ type: 'search-error', episodes: [], snapshot })
    } finally {
      setIsCheckingDuplicate(false)
    }
  }

  const handleClearUrl = () => {
    setUrlInput('')
    setUrlError(null)
  }

  const handleClick = async () => {
    if (!isLoading && episodes?.some((ep) => ep.status === 'generating')) {
      setMessage('先に生成中のタスクがあります')
      return
    }
    if (isUrlMode && !isValidUrl(urlInput)) {
      setUrlError('「http(s)://...」の形式で有効なURLを入力してください')
      return
    }
    if (isUrlMode) {
      await checkDuplicateAndRun()
    } else {
      await runGeneration()
    }
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
    <section className="space-y-4">
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-slate-900">{isUrlMode ? 'URLから解説を生成' : '今日の番組を生成'}</h2>
          <p className="mt-1 text-xs leading-5 text-slate-500">
            {isUrlMode
              ? 'URLから記事を取得して解説音声を生成します。'
              : 'ニュースの種類と読み上げエンジンを選ぶと、取得から音声化までの進行をこの場で確認できます。'}
          </p>
        </div>
        <span className="shrink-0 rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-500">
          通常 2-5 分
        </span>
      </div>

      <div className="mt-5">
        <label htmlFor="generate-url-input" className="block text-sm font-medium text-slate-900">
          URLから解説を生成
        </label>
        <div className="mt-2">
          <div className="relative">
            <input
              id="generate-url-input"
              type="url"
              value={urlInput}
              onChange={(e) => {
                setUrlInput(e.target.value)
                if (urlError) setUrlError(null)
              }}
              onBlur={() => {
                if (urlInput.trim() && !isValidUrl(urlInput)) {
                  setUrlError('「http(s)://...」の形式で入力してください')
                } else {
                  setUrlError(null)
                }
              }}
              placeholder="https://example.com/article"
              disabled={isLoading}
              className="block w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 pr-10 text-sm text-slate-900 placeholder:text-slate-400 transition focus:border-sky-400 focus:outline-none focus:ring-2 focus:ring-sky-100 disabled:opacity-50"
            />
            {urlInput.trim().length > 0 && !isLoading && (
              <button
                type="button"
                onClick={handleClearUrl}
                aria-label="URLをクリア"
                className="absolute right-2.5 top-1/2 -translate-y-1/2 flex items-center justify-center rounded-md p-2 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600 focus:outline-none focus:ring-2 focus:ring-sky-400"
              >
                <svg className="h-4 w-4" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                  <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              </button>
            )}
          </div>
          {urlError && (
            <p className="mt-1.5 text-xs text-red-500">{urlError}</p>
          )}
          <p className="mt-1.5 text-xs leading-5 text-slate-400">
            URLを入力すると自動的に解説モードに切り替わり、ニュースソース選択が無効になります。
          </p>
        </div>
      </div>

      <div className="mt-5 space-y-5">
          <fieldset>
            <legend className="text-sm font-medium text-slate-900">ニュースソース</legend>
            <div className="mt-2 grid gap-2 sm:grid-cols-3">
              <label className={`flex cursor-pointer items-start justify-between gap-2 rounded-xl border p-3 transition ${optionCardClass(newsSource === 'hatena_bookmark', isLoading, isUrlMode)}`}>
                <input
                  type="radio"
                  name="newsSource"
                  value="hatena_bookmark"
                  checked={newsSource === 'hatena_bookmark'}
                  onChange={() => setNewsSource('hatena_bookmark')}
                  disabled={isLoading || isUrlMode}
                  className="sr-only"
                />
                <span>
                  <span className="block text-sm font-medium text-slate-900">テックニュース</span>
                  <span className="mt-0.5 block text-xs leading-5 text-slate-500">
                    はてなブックマークのテック面を中心に収集します。
                  </span>
                </span>
                <RadioDot checked={newsSource === 'hatena_bookmark'} />
              </label>

              <label className={`flex cursor-pointer items-start justify-between gap-2 rounded-xl border p-3 transition ${optionCardClass(newsSource === 'hatena_hotentry_all', isLoading, isUrlMode)}`}>
                <input
                  type="radio"
                  name="newsSource"
                  value="hatena_hotentry_all"
                  checked={newsSource === 'hatena_hotentry_all'}
                  onChange={() => setNewsSource('hatena_hotentry_all')}
                  disabled={isLoading || isUrlMode}
                  className="sr-only"
                />
                <span>
                  <span className="block text-sm font-medium text-slate-900">一般ニュース</span>
                  <span className="mt-0.5 block text-xs leading-5 text-slate-500">
                    幅広い話題をまとめて、日次のダイジェストとして届けます。
                  </span>
                </span>
                <RadioDot checked={newsSource === 'hatena_hotentry_all'} />
              </label>

              <label className={`flex cursor-pointer items-start justify-between gap-2 rounded-xl border p-3 transition ${optionCardClass(newsSource === 'yahoo_news', isLoading, isUrlMode)}`}>
                <input
                  type="radio"
                  name="newsSource"
                  value="yahoo_news"
                  checked={newsSource === 'yahoo_news'}
                  onChange={() => setNewsSource('yahoo_news')}
                  disabled={isLoading || isUrlMode}
                  className="sr-only"
                />
                <span>
                  <span className="block text-sm font-medium text-slate-900">Yahoo!ニュース</span>
                  <span className="mt-0.5 block text-xs leading-5 text-slate-500">
                    Yahoo!ニュース・トピックスの主要ニュースをお届けします。
                  </span>
                </span>
                <RadioDot checked={newsSource === 'yahoo_news'} />
              </label>
            </div>
          </fieldset>

          <fieldset>
            <legend className="text-sm font-medium text-slate-900">音声エンジン</legend>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              <label className={`flex cursor-pointer items-start justify-between gap-2 rounded-xl border p-3 transition ${optionCardClass(ttsEngine === 'voicevox', isLoading)}`}>
                <input
                  type="radio"
                  name="ttsEngine"
                  value="voicevox"
                  checked={ttsEngine === 'voicevox'}
                  onChange={() => setTtsEngine('voicevox')}
                  disabled={isLoading}
                  className="sr-only"
                />
                <span>
                  <span className="block text-sm font-medium text-slate-900">VOICEVOX</span>
                  <span className="mt-0.5 block text-xs leading-5 text-slate-500">
                    安定した読み上げで、通常の番組生成に向いています。
                  </span>
                </span>
                <RadioDot checked={ttsEngine === 'voicevox'} />
              </label>

              <label className={`flex cursor-pointer items-start justify-between gap-2 rounded-xl border p-3 transition ${optionCardClass(ttsEngine === 'aivispeech', isLoading)}`}>
                <input
                  type="radio"
                  name="ttsEngine"
                  value="aivispeech"
                  checked={ttsEngine === 'aivispeech'}
                  onChange={() => setTtsEngine('aivispeech')}
                  disabled={isLoading}
                  className="sr-only"
                />
                <span>
                  <span className="block text-sm font-medium text-slate-900">AivisSpeech</span>
                  <span className="mt-0.5 block text-xs leading-5 text-slate-500">
                    音声差分を試したいときの代替エンジンです。
                  </span>
                </span>
                <RadioDot checked={ttsEngine === 'aivispeech'} />
              </label>
            </div>
          </fieldset>

          <fieldset>
            <legend className="text-sm font-medium text-slate-900">記事数</legend>
            <div className="mt-2 rounded-xl border border-slate-200 p-3">
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
                className="mt-2 w-full accent-sky-600 disabled:opacity-50"
              />
              <div className="mt-1 flex justify-between text-[10px] text-slate-400">
                <span>3</span>
                <span>30</span>
              </div>
            </div>
          </fieldset>

          {isUrlMode && (
            <fieldset>
              <legend className="text-sm font-medium text-slate-900">解説スタイル</legend>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                <label className={`flex cursor-pointer items-start justify-between gap-2 rounded-xl border p-3 transition ${optionCardClass(commentaryStyle === 'solo', isLoading)}`}>
                  <input
                    type="radio"
                    name="commentaryStyle"
                    value="solo"
                    checked={commentaryStyle === 'solo'}
                    onChange={() => setCommentaryStyle('solo')}
                    disabled={isLoading}
                    className="sr-only"
                  />
                  <span>
                    <span className="block text-sm font-medium text-slate-900">一人解説</span>
                    <span className="mt-0.5 block text-xs leading-5 text-slate-500">
                      1人のナレーターが記事を読み上げます。
                    </span>
                  </span>
                  <RadioDot checked={commentaryStyle === 'solo'} />
                </label>

                <label className={`flex cursor-pointer items-start justify-between gap-2 rounded-xl border p-3 transition ${optionCardClass(commentaryStyle === 'dialogue', isLoading)}`}>
                  <input
                    type="radio"
                    name="commentaryStyle"
                    value="dialogue"
                    checked={commentaryStyle === 'dialogue'}
                    onChange={() => setCommentaryStyle('dialogue')}
                    disabled={isLoading}
                    className="sr-only"
                  />
                  <span>
                    <span className="block text-sm font-medium text-slate-900">対談解説</span>
                    <span className="mt-0.5 block text-xs leading-5 text-slate-500">
                      2人のパーソナリティが対談形式で解説します。
                    </span>
                  </span>
                  <RadioDot checked={commentaryStyle === 'dialogue'} />
                </label>
              </div>

              {commentaryStyle === 'solo' && (
                <div className="mt-3">
                  <p className="text-sm font-medium text-slate-900">MCの性別</p>
                  <div className="mt-2 grid gap-2 sm:grid-cols-2">
                    <label className={`flex cursor-pointer items-start justify-between gap-2 rounded-xl border p-3 transition ${optionCardClass(mcGender === 'male', isLoading)}`}>
                      <input
                        type="radio"
                        name="mcGender"
                        value="male"
                        checked={mcGender === 'male'}
                        onChange={() => setMcGender('male')}
                        disabled={isLoading}
                        className="sr-only"
                      />
                      <span>
                        <span className="block text-sm font-medium text-slate-900">男性</span>
                        <span className="mt-0.5 block text-xs leading-5 text-slate-500">男性のナレーター音声で生成します。</span>
                      </span>
                      <RadioDot checked={mcGender === 'male'} />
                    </label>

                    <label className={`flex cursor-pointer items-start justify-between gap-2 rounded-xl border p-3 transition ${optionCardClass(mcGender === 'female', isLoading)}`}>
                      <input
                        type="radio"
                        name="mcGender"
                        value="female"
                        checked={mcGender === 'female'}
                        onChange={() => setMcGender('female')}
                        disabled={isLoading}
                        className="sr-only"
                      />
                      <span>
                        <span className="block text-sm font-medium text-slate-900">女性</span>
                        <span className="mt-0.5 block text-xs leading-5 text-slate-500">女性のナレーター音声で生成します。</span>
                      </span>
                      <RadioDot checked={mcGender === 'female'} />
                    </label>
                  </div>
                </div>
              )}
            </fieldset>
          )}

          <label className={`flex cursor-pointer items-start justify-between gap-2 rounded-xl border p-3 transition ${optionCardClass(recreateSummary, isLoading)}`}>
            <input
              type="checkbox"
              checked={recreateSummary}
              onChange={(e) => setRecreateSummary(e.target.checked)}
              disabled={isLoading}
              className="sr-only"
            />
            <span>
              <span className="block text-sm font-medium text-slate-900">要約を再作成する</span>
              <span className="mt-0.5 block text-xs leading-5 text-slate-500">
                既存の要約を破棄して、再度生成します。
              </span>
            </span>
            <span className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border ${recreateSummary ? 'border-sky-500 bg-sky-500' : 'border-slate-300 bg-white'}`}>
              {recreateSummary && (
                <svg className="h-2.5 w-2.5 text-white" viewBox="0 0 10 8" fill="none">
                  <path d="M1 4l3 3 5-6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </span>
          </label>

          <div>
            <button
              type="button"
              onClick={handleClick}
              disabled={isLoading || isCheckingDuplicate}
              className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-xl bg-sky-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {(isLoading || isCheckingDuplicate) && <span className="h-2 w-2 animate-pulse rounded-full bg-white/90" />}
              {isLoading ? '生成を進めています…' : isCheckingDuplicate ? '確認中…' : isUrlMode ? 'このURLで解説を生成する' : 'この設定で番組を生成する'}
            </button>
            <p className="mt-2 text-center text-xs leading-5 text-slate-400">
              {isUrlMode
                ? 'URL取得 → 記事抽出 → 解説生成 → 音声合成 の順で処理します'
                : '記事取得 → 要約 → 台本生成 → 音声合成 の順で処理します'}
            </p>
          </div>
        </div>
      </div>

      {(isLoading || progress.length > 0 || message || isDuplicateError) && (
        <div id="progress-section" className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="text-sm font-semibold text-slate-900">{phasePresentation.title}</p>
              <p className="mt-0.5 text-xs leading-5 text-slate-500">{phasePresentation.detail}</p>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-500">
                目安 {currentEstimate}
              </span>
              {(isLoading || message) && (
                <span className={`rounded-full border px-2.5 py-1 text-xs font-medium ${statusTone}`}>
                  {isLoading ? '生成中' : isSuccess ? '完了' : isDuplicateError ? '重複' : '確認が必要'}
                </span>
              )}
            </div>
          </div>

          <div className="mt-4">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span>{isFailure ? '進行が中断されました' : isDuplicateError ? '生成できません' : '工程の進み具合'}</span>
              <span className="tabular-nums text-slate-600">{visualProgressPercent}%</span>
            </div>
            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-100">
              <div
                className={`relative h-full rounded-full transition-all duration-500 ${isSuccess ? 'bg-emerald-500' : isFailure ? 'bg-amber-500' : 'bg-sky-500 progress-shimmer'}`}
                style={{ width: `${visualProgressPercent}%` }}
              />
            </div>
          </div>

          <ol className="mt-4 space-y-1.5" aria-live="polite">
            {STEP_DEFINITIONS.map((step, index) => {
              const isComplete = activeStep > index || isSuccess
              const isCurrent = !isSuccess && activeStep === index

              return (
                <li
                  key={step.title}
                  className={`flex items-center gap-3 rounded-xl p-2.5 transition ${
                    isCurrent ? 'bg-sky-50' : ''
                  } ${!isCurrent && !isComplete ? 'opacity-50' : ''}`}
                >
                  <span
                    className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                      isComplete
                        ? 'bg-emerald-500 text-white'
                        : isCurrent
                          ? 'bg-sky-500 text-white progress-breathe'
                          : 'bg-slate-100 text-slate-400'
                    }`}
                  >
                    {isComplete ? (
                      <svg className="h-3 w-3" viewBox="0 0 10 8" fill="none" aria-hidden="true">
                        <path d="M1 4l3 3 5-6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    ) : (
                      index + 1
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium text-slate-800">{step.title}</span>
                    {isCurrent && (
                      <span className="mt-0.5 block text-xs leading-5 text-slate-500">
                        {step.description}
                      </span>
                    )}
                  </span>
                  <span className="shrink-0 text-xs tabular-nums text-slate-400">{step.estimate}</span>
                </li>
              )
            })}
          </ol>

          {progress.length > 0 && (
            <div className="mt-4 border-t border-slate-100 pt-3">
              <button
                type="button"
                onClick={() => setShowLogs((current) => !current)}
                className="flex w-full items-center justify-between gap-3 text-xs text-slate-500 transition hover:text-slate-800"
                aria-expanded={showLogs}
              >
                <span className="font-medium">ログ</span>
                <span>{showLogs ? '隠す' : '表示'}</span>
              </button>

              {showLogs && (
                <div className="mt-2 space-y-1.5">
                  {progress.map((entry, index) => (
                    <div key={`${entry.phase}-${index}`} className="rounded-lg bg-slate-50 px-3 py-2 text-xs leading-5 text-slate-600">
                      <span className="font-medium text-slate-400">
                        {entry.status === 'skipped' && entry.phase === 'review_done'
                          ? 'レビュー省略'
                          : PHASE_PRESENTATION[entry.phase].logLabel}
                      </span>
                      <p className="mt-0.5">{entry.message}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {message ? (
            <div className={`mt-4 rounded-xl border p-3 text-sm ${isSuccess ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-amber-200 bg-amber-50 text-amber-800'}`}>
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
      {duplicateDialog && (
        <DuplicateUrlConfirmDialog
          type={duplicateDialog.type}
          episodes={duplicateDialog.episodes}
          sourceUrl={duplicateDialog.snapshot.url}
          onCancel={() => { setDuplicateDialog(null) }}
          onContinue={() => {
            const snap = duplicateDialog.snapshot
            setDuplicateDialog(null)
            runGeneration(snap)
          }}
        />
      )}
    </section>
  )
}
