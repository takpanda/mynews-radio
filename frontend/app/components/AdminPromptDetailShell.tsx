'use client'

import { useRef, useState, type MutableRefObject } from 'react'
import Link from 'next/link'
import toast from 'react-hot-toast'
import {
  activatePromptVersion,
  createPromptVersion,
  fetchPromptVersions,
  previewProgramPrompt,
  renderPromptVersion,
  rollbackPromptVersion,
  PromptApiError,
  type PromptVersionDetail,
} from '../lib/admin-prompts'
import type { ProgramKind } from '../lib/admin-programs'
import { diffLines } from '../lib/text-diff'

interface Props {
  promptId: number
  templateKey: string
  programId: string | null
  programName: string | null
  programKind: ProgramKind | null
  radioPrograms: { id: string; name: string }[]
  radioProgramsError?: boolean
  requiredVariables: string[]
  allowedVariables: string[]
  initialVersions: PromptVersionDetail[]
}

const STATUS_LABEL: Record<string, string> = { draft: '下書き', active: '公開中', archived: '過去版' }
const STATUS_CLASS: Record<string, string> = {
  draft: 'bg-amber-100 text-amber-700',
  active: 'bg-emerald-100 text-emerald-700',
  archived: 'bg-slate-100 text-slate-500',
}

interface PreviewRowState {
  episodeId: string
  loading: boolean
  error: string | null
  prompt: string | null
  resultEpisodeId: number | null
  prodLoading: boolean
  prodError: string | null
  prodVersionId: number | null
  prodPrompt: string | null
  prodResultEpisodeId: number | null
}

const EMPTY_PREVIEW: PreviewRowState = {
  episodeId: '',
  loading: false,
  error: null,
  prompt: null,
  resultEpisodeId: null,
  prodLoading: false,
  prodError: null,
  prodVersionId: null,
  prodPrompt: null,
  prodResultEpisodeId: null,
}

interface ActionState {
  versionId: number
  kind: 'activate' | 'rollback'
  note: string
  submitting: boolean
  error: string | null
  conflict: boolean
}

function parseEpisodeId(text: string): number | null {
  const value = Number(text.trim())
  return Number.isInteger(value) && value >= 1 ? value : null
}

export default function AdminPromptDetailShell({
  promptId,
  templateKey,
  programId,
  programName,
  programKind,
  radioPrograms,
  radioProgramsError = false,
  requiredVariables,
  allowedVariables,
  initialVersions,
}: Props) {
  const [versions, setVersions] = useState<PromptVersionDetail[]>(initialVersions)
  const [content, setContent] = useState(initialVersions[0]?.content ?? '')
  const [expanded, setExpanded] = useState<Record<number, boolean>>({})
  const [diffOpen, setDiffOpen] = useState<Record<number, boolean>>({})
  const [previews, setPreviews] = useState<Record<number, PreviewRowState>>({})
  const [targetProgramId, setTargetProgramId] = useState('')
  const [action, setAction] = useState<ActionState | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  // 過去回IDが変わった後に前の回への応答が届いても上書きしないよう、行・種別ごとに直近のリクエストだけを採用する。
  const renderSeqRef = useRef<Record<number, number>>({})
  const prodSeqRef = useRef<Record<number, number>>({})

  const target = programId === null ? '共通' : programName ?? programId
  const currentActive = versions.find((v) => v.status === 'active') ?? null

  const getPreview = (versionId: number): PreviewRowState => previews[versionId] ?? EMPTY_PREVIEW
  const updatePreview = (versionId: number, patch: Partial<PreviewRowState>) => {
    setPreviews((prev) => ({ ...prev, [versionId]: { ...getPreview(versionId), ...patch } }))
  }

  const insertVariable = (name: string) => {
    const token = `{${name}}`
    const textarea = textareaRef.current
    if (!textarea) {
      setContent((prev) => prev + token)
      return
    }
    const start = textarea.selectionStart ?? content.length
    const end = textarea.selectionEnd ?? content.length
    const next = content.slice(0, start) + token + content.slice(end)
    setContent(next)
    requestAnimationFrame(() => {
      textarea.focus()
      const cursor = start + token.length
      textarea.setSelectionRange(cursor, cursor)
    })
  }

  const toggleExpanded = (id: number) => {
    setExpanded((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  const toggleDiff = (id: number) => {
    setDiffOpen((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  const refreshVersions = async () => {
    try {
      const refreshed = await fetchPromptVersions(promptId)
      setVersions(refreshed.versions)
    } catch {
      toast.error('版履歴の再取得に失敗しました。画面を再読み込みして確認してください。')
    }
  }

  const bumpSeq = (ref: MutableRefObject<Record<number, number>>, versionId: number): number => {
    const next = (ref.current[versionId] ?? 0) + 1
    ref.current[versionId] = next
    return next
  }

  const handleEpisodeIdChange = (versionId: number, value: string) => {
    // 入力中のIDと表示中の結果が食い違って別回の結果を取り違えないよう、ID変更時は前回の結果を破棄する。
    // seqも進めて、変更前に開始した通信中のリクエストが後から届いても古い結果で上書きしないようにする。
    bumpSeq(renderSeqRef, versionId)
    bumpSeq(prodSeqRef, versionId)
    updatePreview(versionId, {
      episodeId: value,
      loading: false,
      prompt: null,
      error: null,
      resultEpisodeId: null,
      prodLoading: false,
      prodPrompt: null,
      prodError: null,
      prodVersionId: null,
      prodResultEpisodeId: null,
    })
  }

  const runRenderPreview = async (versionId: number) => {
    const episodeId = parseEpisodeId(getPreview(versionId).episodeId)
    if (episodeId === null) {
      bumpSeq(renderSeqRef, versionId)
      updatePreview(versionId, { error: '過去回IDは1以上の整数で入力してください。', prompt: null, resultEpisodeId: null })
      return
    }
    const seq = bumpSeq(renderSeqRef, versionId)
    updatePreview(versionId, { loading: true, error: null })
    try {
      const result = await renderPromptVersion(versionId, episodeId)
      if (renderSeqRef.current[versionId] !== seq) return
      updatePreview(versionId, { loading: false, prompt: result.prompt, resultEpisodeId: episodeId })
    } catch (err) {
      if (renderSeqRef.current[versionId] !== seq) return
      updatePreview(versionId, {
        loading: false,
        prompt: null,
        resultEpisodeId: null,
        error: err instanceof Error ? err.message : '展開プレビューの取得に失敗しました。',
      })
    }
  }

  const runProgramPreview = async (versionId: number) => {
    if (!programId) return
    const episodeId = parseEpisodeId(getPreview(versionId).episodeId)
    if (episodeId === null) {
      bumpSeq(prodSeqRef, versionId)
      updatePreview(versionId, {
        prodError: '過去回IDは1以上の整数で入力してください。',
        prodPrompt: null,
        prodResultEpisodeId: null,
      })
      return
    }
    const seq = bumpSeq(prodSeqRef, versionId)
    updatePreview(versionId, { prodLoading: true, prodError: null })
    try {
      const result = await previewProgramPrompt(programId, templateKey, episodeId)
      if (prodSeqRef.current[versionId] !== seq) return
      updatePreview(versionId, {
        prodLoading: false,
        prodVersionId: result.version_id,
        prodPrompt: result.prompt,
        prodResultEpisodeId: episodeId,
      })
    } catch (err) {
      if (prodSeqRef.current[versionId] !== seq) return
      updatePreview(versionId, {
        prodLoading: false,
        prodPrompt: null,
        prodResultEpisodeId: null,
        prodError: err instanceof Error ? err.message : '対象番組の運用結果の取得に失敗しました。',
      })
    }
  }

  const openAction = (versionId: number, kind: 'activate' | 'rollback') => {
    setAction({ versionId, kind, note: '', submitting: false, error: null, conflict: false })
  }

  const closeAction = () => setAction(null)

  const submitAction = async () => {
    if (!action) return
    const note = action.note.trim()
    if (!note) return
    setAction({ ...action, submitting: true, error: null, conflict: false })
    const expectedActiveVersionId = currentActive?.id ?? null
    try {
      if (action.kind === 'activate') {
        await activatePromptVersion(action.versionId, {
          change_note: note,
          expected_active_version_id: expectedActiveVersionId,
        })
        const activated = versions.find((v) => v.id === action.versionId)
        toast.success(`v${activated?.version ?? action.versionId} を本番適用しました`)
      } else {
        const result = await rollbackPromptVersion(action.versionId, {
          change_note: note,
          expected_active_version_id: expectedActiveVersionId,
        })
        toast.success(`ロールバックにより新しい版（v${result.version}）を作成し、本番適用しました`)
      }
      setAction(null)
      await refreshVersions()
    } catch (err) {
      if (err instanceof PromptApiError && err.status === 409) {
        setAction({
          ...action,
          submitting: false,
          conflict: true,
          error: '現在版が更新されています。最新の状態を取得してください。',
        })
      } else {
        setAction({
          ...action,
          submitting: false,
          conflict: false,
          error: err instanceof Error ? err.message : '操作に失敗しました。',
        })
      }
    }
  }

  const handleConflictRefresh = async () => {
    await refreshVersions()
    setAction(null)
  }

  const handleSave = async () => {
    if (!content.trim()) {
      setSaveError('本文を入力してください')
      return
    }
    setSaving(true)
    setSaveError(null)

    let created
    try {
      created = await createPromptVersion(promptId, content)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : '保存に失敗しました')
      setSaving(false)
      return
    }

    // ここから下は下書きの作成自体は成功済み。再取得の失敗を保存失敗として表示すると、
    // 利用者が「保存できていない」と誤解して再送信し、重複した下書き版を作ってしまう。
    toast.success(`下書き（v${created.version}）を保存しました`)
    try {
      const refreshed = await fetchPromptVersions(promptId)
      setVersions(refreshed.versions)
    } catch {
      setVersions((prev) => [
        {
          id: created.id,
          version: created.version,
          content: created.content,
          status: created.status,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        ...prev,
      ])
      toast.error('下書きは保存されましたが、版履歴の再取得に失敗しました。画面を再読み込みして確認してください。')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <p className="text-xs text-slate-400">{templateKey}</p>
        <h1 className="text-lg font-semibold text-slate-900">{target}</h1>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div>
            <h2 className="text-xs font-medium text-slate-500">必須変数</h2>
            <p className="mt-1 text-sm text-slate-700">
              {requiredVariables.length > 0 ? requiredVariables.join(', ') : 'なし'}
            </p>
          </div>
          <div>
            <h2 className="text-xs font-medium text-slate-500">使用可能な変数</h2>
            <p className="mt-1 text-sm text-slate-700">
              {allowedVariables.length > 0 ? allowedVariables.join(', ') : 'なし'}
            </p>
          </div>
        </div>
      </div>

      {/* PC: Markdown編集 */}
      <div
        className="hidden space-y-3 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6 md:block"
        data-testid="prompt-edit-form"
      >
        <h2 className="text-sm font-semibold text-slate-900">新しい下書きを作成</h2>
        <div className="flex flex-wrap gap-1.5">
          {allowedVariables.map((name) => (
            <button
              key={name}
              type="button"
              onClick={() => insertVariable(name)}
              className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 transition hover:bg-slate-200"
            >
              {`{${name}}`}
            </button>
          ))}
        </div>
        <textarea
          ref={textareaRef}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={16}
          spellCheck={false}
          aria-label="プロンプト本文"
          className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 font-mono text-sm text-slate-900 transition focus:border-sky-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100"
        />
        {saveError && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{saveError}</div>
        )}
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="inline-flex items-center gap-1.5 rounded-full bg-sky-600 px-5 py-2 text-sm font-medium text-white transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {saving && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />}
          下書きとして保存
        </button>
      </div>
      <p className="text-xs text-slate-400 md:hidden" data-testid="prompt-mobile-note">
        スマホ表示では閲覧のみできます。編集・保存はPCから行ってください。
      </p>

      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-100 px-5 py-3">
          <h2 className="text-sm font-semibold text-slate-900">版履歴</h2>
        </div>
        <ul className="divide-y divide-slate-50">
          {versions.length === 0 && (
            <li className="px-5 py-8 text-center text-sm text-slate-400">過去版がありません</li>
          )}
          {versions.map((version) => {
            const preview = getPreview(version.id)
            const isDryRunEligible = templateKey === 'generate_radio_script'
            const dryRunProgramId = programId ?? (targetProgramId || null)
            return (
              <li key={version.id} className="px-5 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-slate-900">v{version.version}</span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_CLASS[version.status] ?? 'bg-slate-100 text-slate-500'}`}
                  >
                    {STATUS_LABEL[version.status] ?? version.status}
                  </span>
                  <span className="text-xs text-slate-400">更新: {version.updated_at}</span>
                  <button
                    type="button"
                    onClick={() => toggleExpanded(version.id)}
                    className="ml-auto text-xs text-sky-600 hover:text-sky-800"
                  >
                    {expanded[version.id] ? '本文を隠す' : '本文を表示'}
                  </button>
                </div>
                {expanded[version.id] && (
                  <pre className="mt-2 whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-3 text-xs text-slate-700">
                    {version.content}
                  </pre>
                )}

                {version.status !== 'active' && currentActive && (
                  <div className="mt-2">
                    <button
                      type="button"
                      onClick={() => toggleDiff(version.id)}
                      className="text-xs text-sky-600 hover:text-sky-800"
                    >
                      {diffOpen[version.id] ? '差分を隠す' : '現在版との差分を見る'}
                    </button>
                    {diffOpen[version.id] && (
                      <DiffView oldText={currentActive.content} newText={version.content} />
                    )}
                  </div>
                )}

                <div className="mt-3 rounded-xl border border-slate-100 bg-slate-50/60 p-3">
                  <h3 className="text-xs font-semibold text-slate-600">展開プレビュー</h3>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <label className="text-xs text-slate-500" htmlFor={`episode-${version.id}`}>
                      過去回ID
                    </label>
                    <input
                      id={`episode-${version.id}`}
                      type="number"
                      min={1}
                      value={preview.episodeId}
                      onChange={(e) => handleEpisodeIdChange(version.id, e.target.value)}
                      aria-label={`v${version.version}の展開プレビュー用過去回ID`}
                      className="w-28 rounded-lg border border-slate-200 bg-white px-2 py-1 text-sm text-slate-900"
                    />
                    <button
                      type="button"
                      onClick={() => runRenderPreview(version.id)}
                      disabled={preview.loading}
                      className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 transition hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      この版で展開プレビューを実行
                    </button>
                    {programId && (
                      <button
                        type="button"
                        onClick={() => runProgramPreview(version.id)}
                        disabled={preview.prodLoading}
                        className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 transition hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        対象番組の現在の運用結果を確認
                      </button>
                    )}
                  </div>
                  {preview.error && <p className="mt-2 text-xs text-red-700">{preview.error}</p>}
                  {preview.prompt !== null && (
                    <div className="mt-2">
                      <p className="text-xs text-slate-500">対象の過去回ID: {preview.resultEpisodeId}</p>
                      <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-white p-3 text-xs text-slate-700">
                        {preview.prompt}
                      </pre>
                    </div>
                  )}
                  {preview.prodError && <p className="mt-2 text-xs text-red-700">{preview.prodError}</p>}
                  {preview.prodPrompt !== null && (
                    <div className="mt-2">
                      <p className="text-xs text-slate-500">
                        対象の過去回ID: {preview.prodResultEpisodeId} ・ 運用中の版: v{preview.prodVersionId}
                      </p>
                      <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-white p-3 text-xs text-slate-700">
                        {preview.prodPrompt}
                      </pre>
                    </div>
                  )}
                </div>

                {version.status === 'draft' && (
                  <div className="mt-3">
                    {!isDryRunEligible ? (
                      <p className="text-xs text-slate-400">
                        テスト生成は generate_radio_script の下書き版のみ対応しています
                      </p>
                    ) : programId && programKind !== 'radio' ? (
                      <p className="text-xs text-slate-400">対象番組がradioではないためテスト生成できません</p>
                    ) : !programId && radioProgramsError ? (
                      <p className="text-xs text-red-700">
                        対象番組一覧の取得に失敗しました。画面を再読み込みしてください。
                      </p>
                    ) : !programId && radioPrograms.length === 0 ? (
                      <p className="text-xs text-slate-400">テスト生成に使えるradio番組が登録されていません</p>
                    ) : (
                      <div className="flex flex-wrap items-center gap-2">
                        {!programId && (
                          <select
                            value={targetProgramId}
                            onChange={(e) => setTargetProgramId(e.target.value)}
                            aria-label="テスト生成の対象番組"
                            className="rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs"
                          >
                            <option value="">対象番組を選択</option>
                            {radioPrograms.map((p) => (
                              <option key={p.id} value={p.id}>
                                {p.name}
                              </option>
                            ))}
                          </select>
                        )}
                        {dryRunProgramId ? (
                          <Link
                            href={`/admin/programs/${encodeURIComponent(dryRunProgramId)}/dry-run?draft_prompt_version_id=${version.id}`}
                            className="rounded-full bg-sky-100 px-3 py-1.5 text-xs font-medium text-sky-700 transition hover:bg-sky-200"
                          >
                            テスト生成・比較テスト画面へ
                          </Link>
                        ) : (
                          <span className="text-xs text-slate-400">対象番組を選択してください</span>
                        )}
                      </div>
                    )}
                  </div>
                )}

                <div className="hidden md:block">
                  {version.status === 'draft' && (
                    <button
                      type="button"
                      onClick={() => openAction(version.id, 'activate')}
                      className="mt-3 rounded-full bg-emerald-600 px-4 py-1.5 text-xs font-medium text-white transition hover:bg-emerald-700"
                    >
                      本番適用
                    </button>
                  )}
                  {version.status === 'archived' && (
                    <button
                      type="button"
                      onClick={() => openAction(version.id, 'rollback')}
                      className="mt-3 rounded-full bg-amber-600 px-4 py-1.5 text-xs font-medium text-white transition hover:bg-amber-700"
                    >
                      この版へロールバック
                    </button>
                  )}
                  {action && action.versionId === version.id && (
                    <div className="mt-2 space-y-2 rounded-xl border border-slate-200 bg-white p-3">
                      <label className="block text-xs font-medium text-slate-500" htmlFor={`change-note-${version.id}`}>
                        変更メモ（必須）
                      </label>
                      <textarea
                        id={`change-note-${version.id}`}
                        value={action.note}
                        onChange={(e) => setAction({ ...action, note: e.target.value })}
                        rows={2}
                        aria-label="変更メモ"
                        className="w-full rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5 text-sm text-slate-900"
                      />
                      {action.error && <p className="text-xs text-red-700">{action.error}</p>}
                      {action.conflict && (
                        <button
                          type="button"
                          onClick={handleConflictRefresh}
                          className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700 transition hover:bg-slate-200"
                        >
                          最新の状態を取得
                        </button>
                      )}
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={submitAction}
                          disabled={!action.note.trim() || action.submitting}
                          className="rounded-full bg-sky-600 px-4 py-1.5 text-xs font-medium text-white transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {action.kind === 'activate' ? '適用する' : 'ロールバックする'}
                        </button>
                        <button
                          type="button"
                          onClick={closeAction}
                          className="rounded-full bg-slate-100 px-4 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-200"
                        >
                          キャンセル
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}

function DiffView({ oldText, newText }: { oldText: string; newText: string }) {
  const diff = diffLines(oldText, newText)
  return (
    <div className="mt-2 space-y-0.5 rounded-lg bg-slate-50 p-3 font-mono text-xs" data-testid="diff-view">
      {diff.map((line, i) => (
        <p
          key={i}
          className={
            line.type === 'added'
              ? 'whitespace-pre-wrap break-words bg-emerald-50 text-emerald-800'
              : line.type === 'removed'
              ? 'whitespace-pre-wrap break-words bg-red-50 text-red-700'
              : 'whitespace-pre-wrap break-words text-slate-600'
          }
        >
          {line.type === 'added' ? '+ ' : line.type === 'removed' ? '- ' : '  '}
          {line.text}
        </p>
      ))}
    </div>
  )
}
