'use client'

import { useState, useCallback, useEffect, useRef } from 'react'
import toast from 'react-hot-toast'
import {
  fetchDictionaryEntries,
  updateDictionaryStatus,
  type DictionaryEntry,
  type DictionaryStats,
  type PaginatedDictionaryResponse,
} from '../lib/admin-dictionary'
import DictionaryFormModal from './DictionaryFormModal'

const PAGE_SIZE = 20

interface Props {
  initialData: PaginatedDictionaryResponse
}

type SortField = 'word' | 'reading' | 'category' | 'status' | 'updated_at'
type SortDirection = 'asc' | 'desc'

const CATEGORIES = ['固有名詞', '地名', '人名', '技術用語', '業界用語', 'その他']

function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  return d.toLocaleDateString('ja-JP', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export default function AdminDictionaryShell({ initialData }: Props) {
  const [items, setItems] = useState<DictionaryEntry[]>(initialData.items)
  const [total, setTotal] = useState(initialData.total)
  const [stats, setStats] = useState<DictionaryStats>(initialData.stats)
  const [hasNext, setHasNext] = useState(initialData.has_next)
  const [offset, setOffset] = useState(0)

  const [query, setQuery] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')

  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [sortField, setSortField] = useState<SortField>('updated_at')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')

  const [modalOpen, setModalOpen] = useState(false)
  const [editingEntry, setEditingEntry] = useState<DictionaryEntry | null>(null)
  const [togglingIds, setTogglingIds] = useState<Set<number>>(new Set())

  const abortRef = useRef<AbortController | null>(null)

  const fetchData = useCallback(
    async (newOffset: number, append = false) => {
      abortRef.current?.abort()
      const ctrl = new AbortController()
      abortRef.current = ctrl
      setLoading(true)
      setLoadError(null)
      try {
        const data = await fetchDictionaryEntries({
          search: query || undefined,
          category: categoryFilter || undefined,
          status: statusFilter || undefined,
          limit: PAGE_SIZE,
          offset: newOffset,
        })
        if (ctrl.signal.aborted) return
        if (append) {
          setItems((prev) => [...prev, ...data.items])
        } else {
          setItems(data.items)
        }
        setTotal(data.total)
        setStats(data.stats)
        setHasNext(data.has_next)
        setOffset(newOffset)
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setLoadError('読み込みに失敗しました')
      } finally {
        setLoading(false)
      }
    },
    [query, categoryFilter, statusFilter],
  )

  const handleSearch = () => {
    fetchData(0, false)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') handleSearch()
  }

  const handleFilterChange = () => {
    fetchData(0, false)
  }

  const handleLoadMore = () => {
    fetchData(offset + PAGE_SIZE, true)
  }

  const handleToggleStatus = async (entry: DictionaryEntry) => {
    const newStatus: 'active' | 'inactive' = entry.status === 'active' ? 'inactive' : 'active'
    setTogglingIds((prev) => new Set(prev).add(entry.id))
    try {
      const updated = await updateDictionaryStatus(entry.id, newStatus)
      setItems((prev) => prev.map((item) => (item.id === entry.id ? updated : item)))
      setTotal((prev) => prev)
      toast.success(
        `「${updated.word}」を${newStatus === 'active' ? '有効' : '無効'}にしました`,
      )
    } catch {
      toast.error('状態の更新に失敗しました')
    } finally {
      setTogglingIds((prev) => {
        const next = new Set(prev)
        next.delete(entry.id)
        return next
      })
    }
  }

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(field)
      setSortDirection('asc')
    }
  }

  const handleEdit = (entry: DictionaryEntry) => {
    setEditingEntry(entry)
    setModalOpen(true)
  }

  const handleAdd = () => {
    setEditingEntry(null)
    setModalOpen(true)
  }

  const handleModalClose = () => {
    setModalOpen(false)
    setEditingEntry(null)
  }

  const handleModalSuccess = () => {
    handleModalClose()
    fetchData(0, false)
  }

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sortField !== field) return null
    return (
      <span className="ml-0.5 inline-block text-[10px]">
        {sortDirection === 'asc' ? '▲' : '▼'}
      </span>
    )
  }

  return (
    <div className="space-y-5">
      {/* 案内バナー */}
      <div className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-3 text-sm text-amber-800">
        <div className="flex items-start gap-2.5">
          <svg
            aria-hidden="true"
            viewBox="0 0 24 24"
            className="mt-0.5 h-4 w-4 shrink-0 text-amber-500"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
          >
            <circle cx="12" cy="12" r="10" />
            <path d="M12 16v-4" />
            <path d="M12 8h.01" />
          </svg>
          <span>
            辞書の変更は、次回の番組生成時から反映されます。現在生成中の番組には反映されません。
          </span>
        </div>
      </div>

      {/* ヘッダー */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-slate-900">辞書管理</h1>
            <p className="mt-1 text-sm text-slate-500">
              読み上げの調整や正しい発音を設定するための辞書を管理します。
            </p>
          </div>
          <button
            type="button"
            onClick={handleAdd}
            className="inline-flex items-center gap-1.5 rounded-full bg-sky-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-sky-700"
          >
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              className="h-4 w-4"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            >
              <path d="M12 5v14M5 12h14" />
            </svg>
            辞書を追加
          </button>
        </div>
      </div>

      {/* 検索・フィルタ */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-0 flex-1 sm:max-w-xs">
            <label className="mb-1 block text-xs font-medium text-slate-500">検索</label>
            <div className="relative">
              <svg
                aria-hidden="true"
                viewBox="0 0 24 24"
                className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              >
                <circle cx="11" cy="11" r="7" />
                <path d="m20 20-3.5-3.5" />
              </svg>
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="単語名で検索"
                className="w-full rounded-full border border-slate-200 bg-slate-50 py-1.5 pl-8 pr-3 text-sm text-slate-800 placeholder:text-slate-400 transition focus:border-sky-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100"
                aria-label="単語名で検索"
              />
            </div>
          </div>
          <div className="w-full sm:w-auto">
            <label className="mb-1 block text-xs font-medium text-slate-500">カテゴリ</label>
            <select
              value={categoryFilter}
              onChange={(e) => {
                setCategoryFilter(e.target.value)
                handleFilterChange()
              }}
              className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-sm text-slate-700 transition focus:border-sky-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100 sm:w-40"
              aria-label="カテゴリで絞り込み"
            >
              <option value="">すべて</option>
              {CATEGORIES.map((cat) => (
                <option key={cat} value={cat}>
                  {cat}
                </option>
              ))}
            </select>
          </div>
          <div className="w-full sm:w-auto">
            <label className="mb-1 block text-xs font-medium text-slate-500">状態</label>
            <select
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value)
                handleFilterChange()
              }}
              className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-sm text-slate-700 transition focus:border-sky-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100 sm:w-32"
              aria-label="状態で絞り込み"
            >
              <option value="">すべて</option>
              <option value="active">有効</option>
              <option value="inactive">無効</option>
            </select>
          </div>
          <button
            type="button"
            onClick={handleSearch}
            className="rounded-full bg-slate-100 px-4 py-1.5 text-sm text-slate-700 transition hover:bg-slate-200"
          >
            検索
          </button>
        </div>
      </div>

      {/* 統計バー */}
      <div className="rounded-2xl border border-slate-200 bg-white px-5 py-3 shadow-sm">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-sm">
          <span className="text-slate-500">
            全<span className="font-semibold text-slate-800">{stats.total}</span>件
          </span>
          <span className="flex items-center gap-1.5 text-slate-500">
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            有効<span className="font-semibold text-slate-800">{stats.active}</span>
          </span>
          <span className="flex items-center gap-1.5 text-slate-500">
            <span className="h-2 w-2 rounded-full bg-slate-300" />
            無効<span className="font-semibold text-slate-800">{stats.inactive}</span>
          </span>
        </div>
      </div>

      {/* エラー表示 */}
      {loadError && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {loadError}
        </div>
      )}

      {/* テーブル */}
      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        {items.length === 0 && !loading ? (
          <div className="py-12 text-center">
            <p className="text-sm text-slate-400">
              {query || categoryFilter || statusFilter
                ? '該当する辞書エントリがありません'
                : '辞書エントリがまだありません。「辞書を追加」から追加してください。'}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-100">
                  <Th onClick={() => handleSort('word')}>
                    単語<SortIcon field="word" />
                  </Th>
                  <Th onClick={() => handleSort('reading')}>
                    読み仮名<SortIcon field="reading" />
                  </Th>
                  <Th onClick={() => handleSort('category')}>
                    カテゴリ<SortIcon field="category" />
                  </Th>
                  <Th onClick={() => handleSort('status')}>
                    状態<SortIcon field="status" />
                  </Th>
                  <Th onClick={() => handleSort('updated_at')}>
                    更新日<SortIcon field="updated_at" />
                  </Th>
                  <Th>操作</Th>
                </tr>
              </thead>
              <tbody>
                {items.map((entry) => (
                  <tr
                    key={entry.id}
                    className="border-b border-slate-50 transition last:border-0 hover:bg-slate-50/50"
                  >
                    <td className="max-w-[180px] truncate px-4 py-3 font-medium text-slate-900">
                      {entry.word}
                    </td>
                    <td className="max-w-[160px] truncate px-4 py-3 text-slate-600">
                      {entry.reading}
                    </td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center rounded-full bg-sky-50 px-2.5 py-0.5 text-xs font-medium text-sky-700">
                        {entry.category}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center gap-1.5 text-xs font-medium ${
                          entry.status === 'active' ? 'text-emerald-700' : 'text-slate-400'
                        }`}
                      >
                        <span
                          className={`h-2 w-2 rounded-full ${
                            entry.status === 'active' ? 'bg-emerald-500' : 'bg-slate-300'
                          }`}
                        />
                        {entry.status === 'active' ? '有効' : '無効'}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-400">
                      {formatDate(entry.updated_at)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => handleEdit(entry)}
                          className="text-xs text-sky-600 transition hover:text-sky-800"
                        >
                          編集
                        </button>
                        <span className="text-slate-200">|</span>
                        <button
                          type="button"
                          onClick={() => handleToggleStatus(entry)}
                          disabled={togglingIds.has(entry.id)}
                          className="relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition disabled:cursor-not-allowed disabled:opacity-50"
                          role="switch"
                          aria-checked={entry.status === 'active'}
                          aria-label={
                            entry.status === 'active'
                              ? `${entry.word}を無効にする`
                              : `${entry.word}を有効にする`
                          }
                        >
                          <span
                            className={`inline-block h-5 w-9 rounded-full transition-colors ${
                              entry.status === 'active' ? 'bg-emerald-500' : 'bg-slate-300'
                            }`}
                          />
                          <span
                            className={`absolute left-0.5 inline-block h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform ${
                              entry.status === 'active' ? 'translate-x-4' : 'translate-x-0.5'
                            }`}
                          />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* 読み込み中 */}
        {loading && (
          <div className="border-t border-slate-100 py-4 text-center text-sm text-slate-400">
            読み込み中...
          </div>
        )}

        {/* ページネーション */}
        {hasNext && !loading && items.length > 0 && (
          <div className="border-t border-slate-100 px-4 py-3">
            <button
              type="button"
              onClick={handleLoadMore}
              className="w-full rounded-lg py-2 text-center text-sm text-slate-500 transition hover:bg-slate-50 hover:text-slate-800"
            >
              もっと見る（{total - offset - PAGE_SIZE}件残り）
            </button>
          </div>
        )}

        {!hasNext && items.length > 0 && (
          <div className="border-t border-slate-100 px-4 py-3 text-center text-xs text-slate-400">
            全{total}件を表示しています
          </div>
        )}
      </div>

      {/* モーダル */}
      {modalOpen && (
        <DictionaryFormModal
          entry={editingEntry}
          onClose={handleModalClose}
          onSuccess={handleModalSuccess}
        />
      )}
    </div>
  )
}

function Th({ children, onClick }: { children: React.ReactNode; onClick?: () => void }) {
  return (
    <th
      onClick={onClick}
      className={`cursor-pointer select-none whitespace-nowrap px-4 py-3 text-xs font-medium text-slate-500 transition hover:text-slate-700 ${onClick ? 'cursor-pointer' : ''}`}
    >
      {children}
    </th>
  )
}
