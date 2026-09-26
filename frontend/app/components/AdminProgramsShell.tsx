'use client'

import { useCallback, useState } from 'react'
import Link from 'next/link'
import { fetchPrograms, type Program } from '../lib/admin-programs'

interface Props {
  initialPrograms: Program[]
  initialIncludeInactive: boolean
}

const KIND_LABEL: Record<string, string> = { radio: 'ラジオ', commentary: '解説' }

export default function AdminProgramsShell({ initialPrograms, initialIncludeInactive }: Props) {
  const [programs, setPrograms] = useState<Program[]>(initialPrograms)
  const [includeInactive, setIncludeInactive] = useState(initialIncludeInactive)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  const reload = useCallback(async (nextIncludeInactive: boolean) => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await fetchPrograms(nextIncludeInactive)
      setPrograms(data)
    } catch {
      setLoadError('読み込みに失敗しました')
    } finally {
      setLoading(false)
    }
  }, [])

  const handleIncludeInactiveChange = (checked: boolean) => {
    setIncludeInactive(checked)
    reload(checked)
  }

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-slate-900">番組管理</h1>
            <p className="mt-1 text-sm text-slate-500">
              番組の出演者・セグメント構成を管理します。変更は保存後すぐに反映されます。
            </p>
            <Link href="/admin/mcs" className="mt-2 inline-block text-xs text-sky-600 hover:text-sky-800">
              MC管理へ
            </Link>
          </div>
          <Link
            href="/admin/programs/new"
            className="hidden items-center gap-1.5 rounded-full bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-700 md:inline-flex"
          >
            番組を新規作成
          </Link>
        </div>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <label className="inline-flex items-center gap-2 text-sm text-slate-600">
          <input
            type="checkbox"
            checked={includeInactive}
            onChange={(e) => handleIncludeInactiveChange(e.target.checked)}
            className="h-4 w-4 rounded border-slate-300 text-sky-600 focus:ring-sky-300"
          />
          無効な番組も表示する
        </label>
      </div>

      {loadError && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{loadError}</div>
      )}

      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        {programs.length === 0 && !loading ? (
          <div className="py-12 text-center">
            <p className="text-sm text-slate-400">
              {includeInactive ? '番組がまだありません。「番組を新規作成」から追加してください。' : '有効な番組がありません。'}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-100">
                  <Th>ID</Th>
                  <Th>名前</Th>
                  <Th>種別</Th>
                  <Th>状態</Th>
                  <Th>操作</Th>
                </tr>
              </thead>
              <tbody>
                {programs.map((program) => (
                  <tr key={program.id} className="border-b border-slate-50 transition last:border-0 hover:bg-slate-50/50">
                    <td className="px-4 py-3 font-medium text-slate-900">{program.id}</td>
                    <td className="px-4 py-3 text-slate-700">{program.name}</td>
                    <td className="px-4 py-3 text-slate-600">{KIND_LABEL[program.kind] ?? program.kind}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center gap-1.5 text-xs font-medium ${
                          program.is_active ? 'text-emerald-700' : 'text-slate-400'
                        }`}
                      >
                        <span className={`h-2 w-2 rounded-full ${program.is_active ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                        {program.is_active ? '有効' : '無効'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <Link href={`/admin/programs/${encodeURIComponent(program.id)}`} className="text-xs text-sky-600 transition hover:text-sky-800">
                        詳細
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {loading && (
          <div className="border-t border-slate-100 py-4 text-center text-sm text-slate-400">読み込み中...</div>
        )}
      </div>
    </div>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="whitespace-nowrap px-4 py-3 text-xs font-medium text-slate-500">{children}</th>
}
