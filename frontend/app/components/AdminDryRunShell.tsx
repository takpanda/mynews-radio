'use client'

import { useEffect, useRef, useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import {
  createDryRunClient,
  fetchDryRunClient,
  DryRunApiError,
  DryRunQueueFullError,
  type DryRunDetail,
  type DryRunStatus,
  type DryRunVariant,
} from '../lib/admin-dry-runs'
import type { ProgramDefinitionValue, ProgramKind } from '../lib/admin-programs'
import type { AdminScriptReviewScript, ValidationFinding } from '../lib/admin-script-review'

interface Props {
  programId: string
  programKind: ProgramKind
  currentDefinition: ProgramDefinitionValue
  initialDryRunId: number | null
}

const STATUS_LABEL: Record<DryRunStatus, string> = {
  queued: '待機中',
  running: '生成中',
  completed: '完了',
  failed: '失敗',
}

const STATUS_BADGE_CLASS: Record<DryRunStatus, string> = {
  queued: 'bg-slate-100 text-slate-600',
  running: 'bg-sky-100 text-sky-700',
  completed: 'bg-emerald-100 text-emerald-700',
  failed: 'bg-red-100 text-red-700',
}

const VARIANT_LABEL: Record<DryRunVariant, string> = { current: '現在版', draft: '下書き版' }

const POLL_INTERVAL_MS = 3000

export default function AdminDryRunShell({ programId, programKind, currentDefinition, initialDryRunId }: Props) {
  const router = useRouter()
  const pathname = usePathname()
  const disabled = programKind !== 'radio'

  const [draftText, setDraftText] = useState('')
  const [promptVersionText, setPromptVersionText] = useState('')
  const [episodeText, setEpisodeText] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [queueRetryAfter, setQueueRetryAfter] = useState<number | null>(null)

  const [dryRunId, setDryRunId] = useState<number | null>(initialDryRunId)
  const [detail, setDetail] = useState<DryRunDetail | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(initialDryRunId !== null)

  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPolling = () => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current)
      pollingRef.current = null
    }
  }

  useEffect(() => stopPolling, [])

  useEffect(() => {
    if (dryRunId === null) return
    let cancelled = false

    const load = async () => {
      try {
        const result = await fetchDryRunClient(dryRunId)
        if (cancelled) return
        setDetail(result)
        setDetailError(null)
        setLoadingDetail(false)
        if (result.status === 'completed' || result.status === 'failed') {
          stopPolling()
        }
      } catch (err) {
        if (cancelled) return
        setDetailError(err instanceof Error ? err.message : '状態の取得に失敗しました。')
        setLoadingDetail(false)
        stopPolling()
      }
    }

    void load()
    stopPolling()
    pollingRef.current = setInterval(() => {
      void load()
    }, POLL_INTERVAL_MS)

    return () => {
      cancelled = true
      stopPolling()
    }
  }, [dryRunId])

  const handlePrefillDraft = () => {
    setDraftText(JSON.stringify(currentDefinition, null, 2))
  }

  const handleSubmit = async () => {
    if (disabled || submitting) return
    setFormError(null)
    setQueueRetryAfter(null)

    let draftProgramDefinition: Record<string, unknown> | null = null
    if (draftText.trim()) {
      try {
        const parsed = JSON.parse(draftText)
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
          throw new Error('not an object')
        }
        draftProgramDefinition = parsed as Record<string, unknown>
      } catch {
        setFormError('下書き番組定義はJSON形式で入力してください。')
        return
      }
    }

    let draftPromptVersionId: number | null = null
    if (promptVersionText.trim()) {
      const value = Number(promptVersionText.trim())
      if (!Number.isInteger(value) || value < 1) {
        setFormError('下書きプロンプト版IDは1以上の整数で入力してください。')
        return
      }
      draftPromptVersionId = value
    }

    let inputEpisodeId: number | null = null
    if (episodeText.trim()) {
      const value = Number(episodeText.trim())
      if (!Number.isInteger(value) || value < 1) {
        setFormError('過去回IDは1以上の整数で入力してください。')
        return
      }
      inputEpisodeId = value
    }

    setSubmitting(true)
    try {
      const result = await createDryRunClient(programId, {
        draft_program_definition: draftProgramDefinition,
        draft_prompt_version_id: draftPromptVersionId,
        input_episode_id: inputEpisodeId,
      })
      setDetail(null)
      setDetailError(null)
      setLoadingDetail(true)
      setDryRunId(result.id)
      router.replace(`${pathname}?dry_run_id=${result.id}`, { scroll: false })
    } catch (err) {
      if (err instanceof DryRunQueueFullError) {
        setQueueRetryAfter(err.retryAfterSeconds)
        setFormError(err.message)
      } else if (err instanceof DryRunApiError) {
        setFormError(err.message)
      } else {
        setFormError('テスト生成の受付に失敗しました。通信状態を確認してもう一度お試しください。')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const variants: DryRunVariant[] = detail?.script_json
    ? ((Object.keys(detail.script_json) as DryRunVariant[]).filter((variant) => detail.script_json?.[variant]))
    : []

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <h1 className="text-lg font-semibold text-slate-900">テスト生成・比較テスト</h1>
        <p className="mt-1 text-sm text-slate-500">
          番組ID: {programId} の台本をこの場で試しに生成し、現在版と下書き版の結果を比較できます。保存は行われません。
        </p>
        {disabled && (
          <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            この番組タイプはテスト生成未対応
          </div>
        )}
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <h2 className="text-sm font-semibold text-slate-900">比較したい下書き（任意）</h2>
        <div className="mt-3 space-y-3">
          <div>
            <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
              <label className="block text-xs font-medium text-slate-500">下書き番組定義（JSON）</label>
              <button
                type="button"
                onClick={handlePrefillDraft}
                disabled={disabled}
                className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 transition hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-50"
              >
                現在の番組定義をコピー
              </button>
            </div>
            <textarea
              value={draftText}
              onChange={(e) => setDraftText(e.target.value)}
              disabled={disabled}
              rows={8}
              placeholder="未入力の場合は現在版のみでテスト生成します"
              aria-label="下書き番組定義（JSON）"
              className="w-full resize-y rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-xs text-slate-900 transition focus:border-sky-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100 disabled:cursor-not-allowed disabled:opacity-60"
            />
            <p className="mt-1 text-xs text-slate-400">ここでの編集は保存されません。テスト生成にのみ使われます。</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-500">下書きプロンプト版ID</label>
              <input
                type="number"
                min={1}
                value={promptVersionText}
                onChange={(e) => setPromptVersionText(e.target.value)}
                disabled={disabled}
                aria-label="下書きプロンプト版ID"
                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-900 disabled:cursor-not-allowed disabled:opacity-60"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-500">過去回ID（入力を固定する場合）</label>
              <input
                type="number"
                min={1}
                value={episodeText}
                onChange={(e) => setEpisodeText(e.target.value)}
                disabled={disabled}
                aria-label="過去回ID"
                className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-900 disabled:cursor-not-allowed disabled:opacity-60"
              />
            </div>
          </div>
        </div>
      </div>

      {formError && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {formError}
          {queueRetryAfter !== null && (
            <p className="mt-1 text-xs text-red-600">{queueRetryAfter}秒ほど待ってから再実行してください。</p>
          )}
        </div>
      )}

      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <button
          type="button"
          onClick={() => void handleSubmit()}
          disabled={disabled || submitting}
          title={disabled ? 'この番組タイプはテスト生成未対応' : undefined}
          className="inline-flex min-h-11 items-center gap-1.5 rounded-full bg-sky-600 px-5 py-2 text-sm font-medium text-white transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />}
          テスト生成を実行
        </button>
      </div>

      {dryRunId !== null && (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold text-slate-900">実行結果（ジョブID: {dryRunId}）</h2>
            {detail && (
              <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_BADGE_CLASS[detail.status]}`}>
                {STATUS_LABEL[detail.status]}
              </span>
            )}
          </div>

          {loadingDetail && !detail && <p className="mt-3 text-sm text-slate-500">状態を確認しています…</p>}
          {detailError && <p className="mt-3 text-sm text-red-700">{detailError}</p>}

          {(detail?.status === 'queued' || detail?.status === 'running') && (
            <p className="mt-3 text-sm text-slate-500">
              {detail.status === 'queued' ? '順番待ちです。' : '台本を生成しています。'}
              完了すると自動的に結果を表示します。
            </p>
          )}

          {detail?.status === 'failed' && (
            <div className="mt-3 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {detail.error ?? 'テスト生成に失敗しました。'}
            </div>
          )}

          {detail?.status === 'completed' && (
            <div className={`mt-4 grid gap-4 ${variants.length > 1 ? 'lg:grid-cols-2' : ''}`}>
              {variants.map((variant) => (
                <DryRunResultPanel
                  key={variant}
                  label={VARIANT_LABEL[variant]}
                  script={detail.script_json?.[variant] ?? null}
                  findings={detail.validation_json?.[variant] ?? []}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function findingsForLine(findings: ValidationFinding[], index: number): ValidationFinding[] {
  return findings.filter((finding) => finding.line_indices.includes(index))
}

function globalFindings(findings: ValidationFinding[]): ValidationFinding[] {
  return findings.filter((finding) => finding.line_indices.length === 0)
}

function DryRunResultPanel({
  label,
  script,
  findings,
}: {
  label: string
  script: AdminScriptReviewScript | null
  findings: ValidationFinding[]
}) {
  if (!script) return null
  const globals = globalFindings(findings)

  return (
    <div className="space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <h3 className="text-sm font-semibold text-slate-900">{label}</h3>

      {globals.length > 0 && (
        <div className="space-y-1 rounded-xl border border-red-200 bg-red-50 p-3 text-xs">
          {globals.map((finding, i) => (
            <p key={i} className={finding.severity === 'error' ? 'text-red-700' : 'text-amber-700'}>
              {finding.severity === 'error' ? '[エラー] ' : '[警告] '}
              {finding.message}
            </p>
          ))}
        </div>
      )}

      <div className="space-y-2">
        {script.lines.map((line, index) => {
          const lineFindings = findingsForLine(findings, index)
          const hasError = lineFindings.some((f) => f.severity === 'error')
          const hasWarning = lineFindings.some((f) => f.severity === 'warning')
          const borderClass = hasError
            ? 'border-red-300 bg-red-50'
            : hasWarning
            ? 'border-amber-300 bg-amber-50'
            : 'border-slate-200 bg-white'
          return (
            <div key={index} className={`rounded-xl border p-3 text-sm ${borderClass}`}>
              <p className="text-xs text-slate-400">
                行{index + 1} ・ {String(line.speaker)}
              </p>
              <p className="mt-1 whitespace-pre-wrap text-slate-800">{String(line.text)}</p>
              {lineFindings.length > 0 && (
                <div className="mt-2 space-y-1">
                  {lineFindings.map((finding, i) => (
                    <p key={i} className={`text-xs ${finding.severity === 'error' ? 'text-red-700' : 'text-amber-700'}`}>
                      {finding.severity === 'error' ? '[エラー] ' : '[警告] '}
                      {finding.message}
                    </p>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
