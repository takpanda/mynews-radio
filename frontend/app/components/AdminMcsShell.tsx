'use client'

import { useCallback, useState } from 'react'
import Link from 'next/link'
import toast from 'react-hot-toast'
import { fetchMcs, type Mc } from '../lib/admin-programs'
import AdminMcFormModal from './AdminMcFormModal'

interface Props {
  initialMcs: Mc[]
  initialIncludeInactive: boolean
}

export default function AdminMcsShell({ initialMcs, initialIncludeInactive }: Props) {
  const [mcs, setMcs] = useState<Mc[]>(initialMcs)
  const [includeInactive, setIncludeInactive] = useState(initialIncludeInactive)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingMc, setEditingMc] = useState<Mc | null>(null)

  const reload = useCallback(async (nextIncludeInactive: boolean) => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await fetchMcs(nextIncludeInactive)
      setMcs(data)
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

  const handleAdd = () => {
    setEditingMc(null)
    setModalOpen(true)
  }

  const handleEdit = (mc: Mc) => {
    setEditingMc(mc)
    setModalOpen(true)
  }

  const handleModalClose = () => {
    setModalOpen(false)
    setEditingMc(null)
  }

  const handleModalSuccess = () => {
    toast.success(editingMc ? 'MCを更新しました' : 'MCを追加しました')
    handleModalClose()
    reload(includeInactive)
  }

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-slate-900">MC管理</h1>
            <p className="mt-1 text-sm text-slate-500">番組で使用するMCプロファイルを管理します。</p>
            <Link href="/admin/programs" className="mt-2 inline-block text-xs text-sky-600 hover:text-sky-800">
              番組管理へ戻る
            </Link>
          </div>
          <button
            type="button"
            onClick={handleAdd}
            className="hidden items-center gap-1.5 rounded-full bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-700 md:inline-flex"
          >
            MCを追加
          </button>
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
          無効なMCも表示する
        </label>
      </div>

      {loadError && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{loadError}</div>
      )}

      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        {mcs.length === 0 && !loading ? (
          <div className="py-12 text-center">
            <p className="text-sm text-slate-400">
              {includeInactive ? 'MCがまだありません。' : '有効なMCがありません。'}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-100">
                  <Th>ID</Th>
                  <Th>名前</Th>
                  <Th>役割</Th>
                  <Th>Fish S2 Pro</Th>
                  <Th>AivisSpeech</Th>
                  <Th>VOICEVOX</Th>
                  <Th>状態</Th>
                  <Th className="hidden md:table-cell">操作</Th>
                </tr>
              </thead>
              <tbody>
                {mcs.map((mc) => (
                  <tr key={mc.id} className="border-b border-slate-50 transition last:border-0 hover:bg-slate-50/50">
                    <td className="px-4 py-3 font-medium text-slate-900">{mc.id}</td>
                    <td className="px-4 py-3 text-slate-700">{mc.name || '—'}</td>
                    <td className="px-4 py-3 text-slate-600">{mc.role || '—'}</td>
                    <td className="px-4 py-3 text-slate-500">{mc.voice_fishs2pro ?? '—'}</td>
                    <td className="px-4 py-3 text-slate-500">{mc.voice_aivispeech ?? '—'}</td>
                    <td className="px-4 py-3 text-slate-500">{mc.voice_voicevox ?? '—'}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center gap-1.5 text-xs font-medium ${
                          mc.is_active ? 'text-emerald-700' : 'text-slate-400'
                        }`}
                      >
                        <span className={`h-2 w-2 rounded-full ${mc.is_active ? 'bg-emerald-500' : 'bg-slate-300'}`} />
                        {mc.is_active ? '有効' : '無効'}
                      </span>
                    </td>
                    <td className="hidden px-4 py-3 md:table-cell">
                      <button
                        type="button"
                        onClick={() => handleEdit(mc)}
                        className="text-xs text-sky-600 transition hover:text-sky-800"
                      >
                        編集
                      </button>
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

      {modalOpen && <AdminMcFormModal mc={editingMc} onClose={handleModalClose} onSuccess={handleModalSuccess} />}
    </div>
  )
}

function Th({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <th className={`whitespace-nowrap px-4 py-3 text-xs font-medium text-slate-500 ${className ?? ''}`}>
      {children}
    </th>
  )
}
