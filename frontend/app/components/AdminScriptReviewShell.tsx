'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'react-hot-toast'
import ConfirmDialog from './ConfirmDialog'
import {
  approveScriptClient,
  buildSpeakerOptions,
  clearDraftFromStorage,
  diffScriptLines,
  fetchScriptClient,
  initialSpeakerKey,
  loadDraftFromStorage,
  previewAudioClient,
  rejectScriptClient,
  saveDraftToStorage,
  saveScriptClient,
  shouldShowSpeakerSelect,
  ScriptApiError,
  ScriptRevisionConflictError,
  ScriptValidationBlockedError,
  validateScriptClient,
  type AdminScriptReviewCastMember,
  type AdminScriptReviewLine,
  type AdminScriptReviewScript,
  type ScriptDraft,
  type ValidationFinding,
  type ValidationResult,
} from '../lib/admin-script-review'

interface Props {
  episodeId: number
  initialRevision: number
  initialScript: AdminScriptReviewScript
  initialCast?: AdminScriptReviewCastMember[] | null
}

interface ConflictState {
  latestRevision: number
  serverScript: AdminScriptReviewScript
}

interface ApproveErrorState {
  message: string
  results?: ValidationFinding[]
}

function findingsForLine(validation: ValidationResult | null, index: number): ValidationFinding[] {
  if (!validation) return []
  return validation.results.filter((finding) => finding.line_indices.includes(index))
}

function globalFindings(validation: ValidationResult | null): ValidationFinding[] {
  if (!validation) return []
  return validation.results.filter((finding) => finding.line_indices.length === 0)
}

export default function AdminScriptReviewShell({ episodeId, initialRevision, initialScript, initialCast = null }: Props) {
  const [revision, setRevision] = useState(initialRevision)
  const [script, setScript] = useState(initialScript)
  const [dirty, setDirty] = useState(false)

  const [validation, setValidation] = useState<ValidationResult | null>(null)
  const [validating, setValidating] = useState(false)
  const [validationError, setValidationError] = useState<string | null>(null)

  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [conflict, setConflict] = useState<ConflictState | null>(null)

  const [previewingIndex, setPreviewingIndex] = useState<number | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const previewUrlRef = useRef<string | null>(null)

  const [approveDialogOpen, setApproveDialogOpen] = useState(false)
  const [approving, setApproving] = useState(false)
  const [approveError, setApproveError] = useState<ApproveErrorState | null>(null)
  const [approvedJobId, setApprovedJobId] = useState<number | null>(null)

  const [discardDialogOpen, setDiscardDialogOpen] = useState(false)
  const [discarding, setDiscarding] = useState(false)
  const [discardError, setDiscardError] = useState<string | null>(null)
  const [discarded, setDiscarded] = useState(false)

  const [draftPrompt, setDraftPrompt] = useState<ScriptDraft | null>(null)

  // 保存・試し聴きの実行中に編集が入り込むと、送信済みの内容と画面表示がずれてしまう。
  // 台本内容を変更するたびに増やし、非同期処理の応答が「その時点より後の編集」を跨いでいないかの照合に使う。
  const editTokenRef = useRef(0)

  const busy = saving || previewingIndex !== null

  // 端末下書きの確認は初回マウント時のみ。ユーザーが選択するまで編集内容には反映しない。
  useEffect(() => {
    const draft = loadDraftFromStorage(episodeId)
    if (draft) setDraftPrompt(draft)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!dirty) return
    saveDraftToStorage(episodeId, revision, script)
  }, [episodeId, revision, script, dirty])

  useEffect(() => {
    return () => {
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current)
    }
  }, [])

  const updateLines = useCallback(
    (updater: (lines: AdminScriptReviewLine[]) => AdminScriptReviewLine[]) => {
      // 保存中・試し聴き中は送信済みの内容と画面がずれるため、編集操作そのものを受け付けない。
      if (busy) return
      editTokenRef.current += 1
      setScript((prev) => ({ ...prev, lines: updater(prev.lines) }))
      setDirty(true)
      setValidation(null)
    },
    [busy],
  )

  const handleTextChange = (index: number, text: string) => {
    updateLines((lines) => lines.map((line, i) => (i === index ? { ...line, text } : line)))
  }

  const handleSpeakerChange = (index: number, speaker: string) => {
    updateLines((lines) => lines.map((line, i) => (i === index ? { ...line, speaker } : line)))
  }

  const handleAddLine = () => {
    const lastLine = script.lines[script.lines.length - 1]
    const newLine: AdminScriptReviewLine = {
      speaker: initialSpeakerKey(initialCast, script.lines),
      text: '',
      section: lastLine?.section ?? 'news',
    }
    updateLines((lines) => [...lines, newLine])
  }

  const handleRemoveLine = (index: number) => {
    updateLines((lines) => lines.filter((_, i) => i !== index))
  }

  const handleMoveLine = (index: number, direction: -1 | 1) => {
    const target = index + direction
    if (target < 0 || target >= script.lines.length) return
    updateLines((lines) => {
      const next = [...lines]
      const [moved] = next.splice(index, 1)
      next.splice(target, 0, moved)
      return next
    })
  }

  const performSave = useCallback(
    async (revisionToUse: number) => {
      setSaving(true)
      setSaveError(null)
      try {
        const result = await saveScriptClient(episodeId, revisionToUse, script)
        editTokenRef.current += 1
        setScript(result.script)
        setRevision(result.revision)
        setDirty(false)
        setConflict(null)
        clearDraftFromStorage(episodeId)
        toast.success('保存しました')
      } catch (err) {
        if (err instanceof ScriptRevisionConflictError) {
          try {
            const latest = await fetchScriptClient(episodeId)
            setConflict({ latestRevision: latest.revision, serverScript: latest.script })
          } catch {
            setSaveError('最新版の取得に失敗しました。しばらく後でもう一度お試しください。')
          }
        } else if (err instanceof ScriptApiError) {
          setSaveError(err.message)
        } else {
          setSaveError('保存に失敗しました。通信状態を確認してもう一度お試しください。')
        }
      } finally {
        setSaving(false)
      }
    },
    [episodeId, script],
  )

  const handleSave = () => {
    if (saving) return
    void performSave(revision)
  }

  const handleUseServerVersion = () => {
    if (!conflict) return
    editTokenRef.current += 1
    setScript(conflict.serverScript)
    setRevision(conflict.latestRevision)
    setDirty(false)
    setConflict(null)
    clearDraftFromStorage(episodeId)
    setValidation(null)
  }

  const handleRetrySaveWithLatestRevision = () => {
    if (!conflict) return
    const latestRevision = conflict.latestRevision
    setRevision(latestRevision)
    setConflict(null)
    void performSave(latestRevision)
  }

  const handleValidate = async () => {
    if (dirty || validating) return
    const requestToken = editTokenRef.current
    setValidating(true)
    setValidationError(null)
    try {
      const result = await validateScriptClient(episodeId)
      // 検査中に編集されていたら、保存済み最新版に対する結果ではなくなっているため反映しない。
      if (editTokenRef.current !== requestToken) return
      setValidation(result)
    } catch (err) {
      if (editTokenRef.current !== requestToken) return
      setValidationError(err instanceof ScriptApiError ? err.message : '検査に失敗しました。もう一度お試しください。')
    } finally {
      setValidating(false)
    }
  }

  const handlePreview = async (index: number) => {
    if (dirty || busy) return
    const requestToken = editTokenRef.current
    setPreviewingIndex(index)
    setPreviewError(null)
    try {
      const blob = await previewAudioClient(episodeId, index)
      // 応答を待つ間に台本が変わっていたら、画面表示と異なる内容の音声のため再生しない。
      if (editTokenRef.current !== requestToken) return
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current)
      const url = URL.createObjectURL(blob)
      previewUrlRef.current = url
      if (audioRef.current) {
        audioRef.current.src = url
        await audioRef.current.play()
      }
    } catch (err) {
      if (editTokenRef.current !== requestToken) return
      setPreviewError(err instanceof ScriptApiError ? err.message : '試し聴きに失敗しました。もう一度お試しください。')
    } finally {
      setPreviewingIndex(null)
    }
  }

  const handleApproveConfirmed = async () => {
    setApproving(true)
    setApproveError(null)
    try {
      const result = await approveScriptClient(episodeId)
      setApprovedJobId(result.job_id)
      setApproveDialogOpen(false)
      clearDraftFromStorage(episodeId)
      toast.success('承認しました。音声生成を開始します。')
    } catch (err) {
      if (err instanceof ScriptValidationBlockedError) {
        setApproveError({ message: '検査エラーが残っているため承認できません。', results: err.results })
      } else if (err instanceof ScriptApiError) {
        setApproveError({ message: err.message })
      } else {
        setApproveError({ message: '承認に失敗しました。もう一度お試しください。' })
      }
    } finally {
      setApproving(false)
    }
  }

  const handleDiscardConfirmed = async () => {
    setDiscarding(true)
    setDiscardError(null)
    try {
      await rejectScriptClient(episodeId, 'discard')
      setDiscarded(true)
      setDiscardDialogOpen(false)
      clearDraftFromStorage(episodeId)
      toast.success('破棄しました')
    } catch (err) {
      setDiscardError(err instanceof ScriptApiError ? err.message : '破棄に失敗しました。もう一度お試しください。')
    } finally {
      setDiscarding(false)
    }
  }

  const handleRestoreDraftSameRevision = () => {
    if (!draftPrompt) return
    editTokenRef.current += 1
    setScript(draftPrompt.script)
    setDirty(true)
    setDraftPrompt(null)
  }

  const handleApplyDraftAnyway = () => {
    if (!draftPrompt) return
    editTokenRef.current += 1
    setScript(draftPrompt.script)
    setDirty(true)
    setDraftPrompt(null)
  }

  const handleDiscardDraft = () => {
    clearDraftFromStorage(episodeId)
    setDraftPrompt(null)
  }

  if (discarded) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-700 shadow-sm sm:p-6">
        <p className="font-medium text-slate-900">この台本は破棄されました。</p>
        <p className="mt-1 text-slate-500">確認待ち一覧から他のエピソードを確認できます。</p>
      </div>
    )
  }

  if (approvedJobId !== null) {
    return (
      <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5 text-sm text-emerald-800 shadow-sm sm:p-6">
        <p className="font-medium">承認しました。音声生成を開始しました（ジョブID: {approvedJobId}）。</p>
        <p className="mt-1 text-emerald-700">生成状況は生成詳細ログから確認できます。</p>
      </div>
    )
  }

  const speakerOptions = buildSpeakerOptions(initialCast, script.lines)
  const showSpeakerSelect = shouldShowSpeakerSelect(initialCast, script.lines)
  const findings = globalFindings(validation)
  const draftIsSameRevision = draftPrompt?.baseRevision === revision

  return (
    <div className="space-y-5">
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <audio ref={audioRef} className="hidden" />

      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <h1 className="text-lg font-semibold text-slate-900">台本確認・編集</h1>
        <p className="mt-1 text-sm text-slate-500">
          エピソードID: {episodeId} ・ 版: {revision}
          {dirty && <span className="ml-2 font-medium text-amber-600">未保存の変更があります</span>}
        </p>
      </div>

      {draftPrompt && (
        <div className="rounded-2xl border border-sky-200 bg-sky-50 p-4 text-sm text-sky-900 shadow-sm">
          <p className="font-medium">端末に保存された下書きがあります。</p>
          {draftIsSameRevision ? (
            <>
              <p className="mt-1 text-sky-700">前回の編集内容を復元できます。</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={handleRestoreDraftSameRevision}
                  disabled={busy}
                  className="min-h-11 rounded-full bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  下書きを復元する
                </button>
                <button
                  type="button"
                  onClick={handleDiscardDraft}
                  disabled={busy}
                  className="min-h-11 rounded-full border border-sky-200 bg-white px-4 py-2 text-sm font-medium text-sky-700 transition hover:bg-sky-100 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  下書きを破棄する
                </button>
              </div>
            </>
          ) : (
            <>
              <p className="mt-1 text-sky-700">
                下書きの作成後にサーバー側の版が進んでいます（下書きの元版: {draftPrompt.baseRevision} / 現在の版: {revision}）。
                内容を確認してから選んでください。
              </p>
              <div className="mt-3 max-h-64 space-y-1 overflow-y-auto rounded-xl border border-sky-100 bg-white p-3 text-xs">
                {diffScriptLines(draftPrompt.script.lines, script.lines).map((op, i) => (
                  <p
                    key={i}
                    className={
                      op.kind === 'same'
                        ? 'text-slate-500'
                        : op.kind === 'local-only'
                        ? 'bg-amber-50 text-amber-800'
                        : 'bg-slate-100 text-slate-700'
                    }
                  >
                    {op.kind === 'local-only' ? '下書き: ' : op.kind === 'server-only' ? 'サーバー: ' : ''}
                    {op.line.text || '（空行）'}
                  </p>
                ))}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={handleApplyDraftAnyway}
                  disabled={busy}
                  className="min-h-11 rounded-full bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  下書きの内容を反映する
                </button>
                <button
                  type="button"
                  onClick={handleDiscardDraft}
                  disabled={busy}
                  className="min-h-11 rounded-full border border-sky-200 bg-white px-4 py-2 text-sm font-medium text-sky-700 transition hover:bg-sky-100 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  サーバー最新版を使う（下書きを破棄）
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {conflict && (
        <div className="rounded-2xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900 shadow-sm">
          <p className="font-medium">保存できませんでした。他の操作でサーバー側の版が進んでいます（現在の版: {conflict.latestRevision}）。</p>
          <p className="mt-1 text-amber-700">内容を比較してから選んでください。自動的には上書きしません。</p>
          <div className="mt-3 max-h-64 space-y-1 overflow-y-auto rounded-xl border border-amber-200 bg-white p-3 text-xs">
            {diffScriptLines(script.lines, conflict.serverScript.lines).map((op, i) => (
              <p
                key={i}
                className={
                  op.kind === 'same'
                    ? 'text-slate-500'
                    : op.kind === 'local-only'
                    ? 'bg-amber-100 text-amber-900'
                    : 'bg-slate-100 text-slate-700'
                }
              >
                {op.kind === 'local-only' ? 'あなたの編集: ' : op.kind === 'server-only' ? 'サーバー最新版: ' : ''}
                {op.line.text || '（空行）'}
              </p>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={handleRetrySaveWithLatestRevision}
              disabled={busy}
              className="min-h-11 rounded-full bg-amber-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              この内容で保存し直す
            </button>
            <button
              type="button"
              onClick={handleUseServerVersion}
              disabled={busy}
              className="min-h-11 rounded-full border border-amber-300 bg-white px-4 py-2 text-sm font-medium text-amber-800 transition hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-60"
            >
              サーバーの最新版を使う（編集を破棄）
            </button>
          </div>
        </div>
      )}

      {findings.length > 0 && (
        <div className="space-y-2 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 shadow-sm">
          <p className="font-medium">台本全体に関する指摘</p>
          {findings.map((finding, i) => (
            <p key={i} className={finding.severity === 'error' ? 'text-red-700' : 'text-amber-700'}>
              {finding.severity === 'error' ? '[エラー] ' : '[警告] '}
              {finding.message}
            </p>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <button
          type="button"
          onClick={handleSave}
          disabled={saving || !dirty}
          className="inline-flex min-h-11 items-center gap-1.5 rounded-full bg-sky-600 px-5 py-2 text-sm font-medium text-white transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {saving && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />}
          保存する
        </button>
        <button
          type="button"
          onClick={handleValidate}
          disabled={dirty || validating}
          title={dirty ? '保存してから再チェックしてください' : undefined}
          className="min-h-11 rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {validating ? '検査中...' : '再チェック'}
        </button>
        {dirty && <span className="text-xs text-amber-600">未保存の変更があるため、再チェックと試し聴きは保存後に行えます</span>}
      </div>

      {saveError && <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{saveError}</div>}
      {validationError && <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{validationError}</div>}
      {previewError && <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{previewError}</div>}
      {validation && (
        <p className="text-xs text-slate-500">
          {validation.can_approve ? '検査エラーはありません。' : '検査エラーが残っています。承認する前に修正してください。'}
        </p>
      )}

      <div className="space-y-3">
        {script.lines.map((line, index) => {
          const lineFindings = findingsForLine(validation, index)
          const hasError = lineFindings.some((f) => f.severity === 'error')
          const hasWarning = lineFindings.some((f) => f.severity === 'warning')
          const borderClass = hasError
            ? 'border-red-300 bg-red-50'
            : hasWarning
            ? 'border-amber-300 bg-amber-50'
            : 'border-slate-200 bg-white'
          return (
            <div key={index} className={`rounded-2xl border p-4 shadow-sm ${borderClass}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  {showSpeakerSelect ? (
                    <select
                      value={line.speaker}
                      onChange={(e) => handleSpeakerChange(index, e.target.value)}
                      disabled={busy}
                      aria-label={`行${index + 1}の話者`}
                      className="min-h-11 rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-sm text-slate-900 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {speakerOptions.map((option) => (
                        <option key={option.key} value={option.key}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className="text-xs text-slate-400">行{index + 1}</span>
                  )}
                </div>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => handleMoveLine(index, -1)}
                    disabled={index === 0 || busy}
                    aria-label={`行${index + 1}を上へ`}
                    className="flex h-11 w-11 items-center justify-center rounded-lg text-slate-500 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-30"
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    onClick={() => handleMoveLine(index, 1)}
                    disabled={index === script.lines.length - 1 || busy}
                    aria-label={`行${index + 1}を下へ`}
                    className="flex h-11 w-11 items-center justify-center rounded-lg text-slate-500 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-30"
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    onClick={() => handlePreview(index)}
                    disabled={dirty || busy}
                    title={dirty ? '保存してから試し聴きしてください' : undefined}
                    aria-label={`行${index + 1}を試し聴き`}
                    className="flex h-11 w-11 items-center justify-center rounded-lg text-sky-600 transition hover:bg-sky-50 disabled:cursor-not-allowed disabled:opacity-30"
                  >
                    {previewingIndex === index ? (
                      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-sky-300 border-t-sky-600" />
                    ) : (
                      '▶'
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleRemoveLine(index)}
                    disabled={busy}
                    aria-label={`行${index + 1}を削除`}
                    className="flex h-11 w-11 items-center justify-center rounded-lg text-red-500 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-30"
                  >
                    ✕
                  </button>
                </div>
              </div>
              <textarea
                value={line.text}
                onChange={(e) => handleTextChange(index, e.target.value)}
                rows={2}
                disabled={busy}
                aria-label={`行${index + 1}の本文`}
                className="mt-2 w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 transition focus:border-sky-400 focus:outline-none focus:ring-2 focus:ring-sky-100 disabled:cursor-not-allowed disabled:opacity-60"
              />
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

      <button
        type="button"
        onClick={handleAddLine}
        disabled={busy}
        className="min-h-11 w-full rounded-2xl border border-dashed border-slate-300 bg-white px-4 py-3 text-sm font-medium text-slate-600 transition hover:border-slate-400 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
      >
        + 行を追加
      </button>

      <div className="flex flex-wrap gap-2 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <button
          type="button"
          onClick={() => setDiscardDialogOpen(true)}
          className="min-h-11 flex-1 rounded-full border border-red-200 bg-white px-4 py-2 text-sm font-medium text-red-700 transition hover:bg-red-50"
        >
          破棄する
        </button>
        <button
          type="button"
          onClick={() => setApproveDialogOpen(true)}
          disabled={dirty}
          title={dirty ? '保存してから承認してください' : undefined}
          className="min-h-11 flex-1 rounded-full bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          承認する
        </button>
      </div>

      {approveDialogOpen && (
        <ConfirmDialog
          title="この台本を承認しますか？"
          message="承認すると音声生成が開始されます。承認後の取り消しはできません。"
          confirmLabel="承認する"
          confirming={approving}
          error={approveError?.message ?? null}
          onConfirm={handleApproveConfirmed}
          onCancel={() => {
            if (!approving) {
              setApproveDialogOpen(false)
              setApproveError(null)
            }
          }}
        >
          {approveError?.results && approveError.results.length > 0 && (
            <ul className="space-y-1 rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-700">
              {approveError.results
                .filter((f) => f.severity === 'error')
                .map((f, i) => (
                  <li key={i}>{f.message}</li>
                ))}
            </ul>
          )}
        </ConfirmDialog>
      )}

      {discardDialogOpen && (
        <ConfirmDialog
          title="この台本を破棄しますか？"
          message="破棄するとこのエピソードは公開されません。この操作は取り消せません。"
          confirmLabel="破棄する"
          danger
          confirming={discarding}
          error={discardError}
          onConfirm={handleDiscardConfirmed}
          onCancel={() => {
            if (!discarding) {
              setDiscardDialogOpen(false)
              setDiscardError(null)
            }
          }}
        />
      )}
    </div>
  )
}
