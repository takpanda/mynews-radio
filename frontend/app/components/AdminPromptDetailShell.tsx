'use client'

import { useRef, useState } from 'react'
import toast from 'react-hot-toast'
import { createPromptVersion, fetchPromptVersions, type PromptVersionDetail } from '../lib/admin-prompts'

interface Props {
  promptId: number
  templateKey: string
  programId: string | null
  programName: string | null
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

export default function AdminPromptDetailShell({
  promptId,
  templateKey,
  programId,
  programName,
  requiredVariables,
  allowedVariables,
  initialVersions,
}: Props) {
  const [versions, setVersions] = useState<PromptVersionDetail[]>(initialVersions)
  const [content, setContent] = useState(initialVersions[0]?.content ?? '')
  const [expanded, setExpanded] = useState<Record<number, boolean>>({})
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  const target = programId === null ? '共通' : programName ?? programId

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
          {versions.map((version) => (
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
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
