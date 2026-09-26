'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import toast from 'react-hot-toast'
import { createPromptTemplate, type PromptTemplate } from '../lib/admin-prompts'
import type { Program } from '../lib/admin-programs'

interface Props {
  initialTemplates: PromptTemplate[]
  programs: Program[]
}

function groupByTemplateKey(templates: PromptTemplate[]): Map<string, PromptTemplate[]> {
  const map = new Map<string, PromptTemplate[]>()
  for (const template of templates) {
    const list = map.get(template.template_key) ?? []
    list.push(template)
    map.set(template.template_key, list)
  }
  return map
}

function activeVersion(template: PromptTemplate) {
  return template.versions.find((version) => version.status === 'active') ?? null
}

export default function AdminPromptsShell({ initialTemplates, programs }: Props) {
  const router = useRouter()
  const [templates] = useState<PromptTemplate[]>(initialTemplates)
  const [selections, setSelections] = useState<Record<string, string>>({})
  const [creatingKey, setCreatingKey] = useState<string | null>(null)
  const [createErrors, setCreateErrors] = useState<Record<string, string>>({})

  const programName = (id: string | null): string => {
    if (id === null) return '共通'
    return programs.find((program) => program.id === id)?.name ?? id
  }

  const groups = groupByTemplateKey(templates)

  const handleCreate = async (templateKey: string) => {
    const programId = selections[templateKey]
    if (!programId) return
    setCreatingKey(templateKey)
    setCreateErrors((prev) => ({ ...prev, [templateKey]: '' }))
    try {
      const created = await createPromptTemplate({ template_key: templateKey, program_id: programId })
      toast.success('番組固有版を作成しました')
      router.push(`/admin/prompts/${created.id}`)
    } catch (err) {
      setCreateErrors((prev) => ({
        ...prev,
        [templateKey]: err instanceof Error ? err.message : '作成に失敗しました',
      }))
    } finally {
      setCreatingKey(null)
    }
  }

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <h1 className="text-lg font-semibold text-slate-900">プロンプト管理</h1>
        <p className="mt-1 text-sm text-slate-500">
          共通テンプレートと番組固有テンプレートの版を確認・編集します。
        </p>
      </div>

      {templates.length === 0 ? (
        <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-400 shadow-sm">
          プロンプトテンプレートがまだありません。
        </div>
      ) : (
        Array.from(groups.entries()).map(([templateKey, group]) => {
          const usedProgramIds = new Set(
            group.map((template) => template.program_id).filter((id): id is string => id !== null),
          )
          const availablePrograms = programs.filter((program) => !usedProgramIds.has(program.id))

          return (
            <div key={templateKey} className="rounded-2xl border border-slate-200 bg-white shadow-sm">
              <div className="border-b border-slate-100 px-5 py-3">
                <h2 className="text-sm font-semibold text-slate-900">{templateKey}</h2>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-slate-100">
                      <Th>対象</Th>
                      <Th>現在版</Th>
                      <Th>更新日時</Th>
                      <Th>操作</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {group.map((template) => {
                      const active = activeVersion(template)
                      return (
                        <tr key={template.id} className="border-b border-slate-50 transition last:border-0 hover:bg-slate-50/50">
                          <td className="px-5 py-3 text-slate-700">
                            {template.program_id === null ? (
                              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">共通</span>
                            ) : (
                              programName(template.program_id)
                            )}
                          </td>
                          <td className="px-5 py-3 text-slate-600">{active ? `v${active.version}` : '(なし)'}</td>
                          <td className="px-5 py-3 text-slate-600">{active ? active.updated_at : '—'}</td>
                          <td className="px-5 py-3">
                            <Link href={`/admin/prompts/${template.id}`} className="text-xs text-sky-600 transition hover:text-sky-800">
                              詳細
                            </Link>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              {availablePrograms.length > 0 && (
                <div
                  className="hidden flex-wrap items-center gap-2 border-t border-slate-100 px-5 py-3 md:flex"
                  data-testid={`add-override-${templateKey}`}
                >
                  <select
                    value={selections[templateKey] ?? ''}
                    onChange={(e) => setSelections((prev) => ({ ...prev, [templateKey]: e.target.value }))}
                    aria-label={`${templateKey}の番組固有版を追加する対象番組`}
                    className="rounded-lg border border-slate-200 bg-slate-50 px-2 py-1.5 text-xs"
                  >
                    <option value="">番組を選択</option>
                    {availablePrograms.map((program) => (
                      <option key={program.id} value={program.id}>
                        {program.name}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => handleCreate(templateKey)}
                    disabled={!selections[templateKey] || creatingKey === templateKey}
                    className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-200 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    番組固有版を追加
                  </button>
                  {createErrors[templateKey] && (
                    <span className="text-xs text-red-600">{createErrors[templateKey]}</span>
                  )}
                </div>
              )}
            </div>
          )
        })
      )}
    </div>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="whitespace-nowrap px-5 py-3 text-xs font-medium text-slate-500">{children}</th>
}
