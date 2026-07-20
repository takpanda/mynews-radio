'use client'

import { useState, useCallback, useEffect } from 'react'
import toast from 'react-hot-toast'
import type { AdminMisreadingReport } from '../lib/admin-misreading-reports'
import { approveMisreadingReport } from '../lib/admin-misreading-reports'

interface Props {
  initialData: AdminMisreadingReport[]
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  return d.toLocaleDateString('ja-JP', {
    timeZone: 'Asia/Tokyo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export default function AdminMisreadingReportsShell({ initialData }: Props) {
  const [reports, setReports] = useState<AdminMisreadingReport[]>(initialData)
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())
  const [approvingIds, setApprovingIds] = useState<Set<number>>(new Set())

  const toggleExpand = (id: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const handleApprove = useCallback(async (report: AdminMisreadingReport) => {
    setApprovingIds((prev) => new Set(prev).add(report.id))
    try {
      const result = await approveMisreadingReport(report.id)
      setReports((prev) =>
        prev.map((r) =>
          r.id === report.id
            ? {
                ...r,
                approved: true,
                approved_at: new Date().toISOString(),
                approved_dictionary_entry_id:
                  result.dictionary_entry_id ?? null,
              }
            : r,
        ),
      )
      if (result.status === 'approved') {
        toast.success(
          `「${report.target_text}」を承認し辞書に登録しました`,
        )
      } else if (result.status === 'skipped') {
        toast(
          '既存の辞書エントリがあるため登録をスキップしました',
          { icon: 'ℹ️' },
        )
      } else {
        toast('既に承認済みです', { icon: 'ℹ️' })
      }
    } catch {
      toast.error('承認処理に失敗しました。もう一度お試しください。')
    } finally {
      setApprovingIds((prev) => {
        const next = new Set(prev)
        next.delete(report.id)
        return next
      })
    }
  }, [])

  useEffect(() => {
    const hash = window.location.hash
    if (hash && hash.startsWith('#report-')) {
      const id = hash.replace('#report-', '')
      const el = document.getElementById(`report-${id}`)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
        el.classList.add('ring-2', 'ring-sky-300', 'rounded-xl')
      }
    }
  }, [])

  return (
    <div className="space-y-5">
      {/* ヘッダー */}
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">読み間違い報告</h1>
          <p className="mt-1 text-sm text-slate-500">
            利用者から寄せられた読み間違い報告を確認できます。
          </p>
        </div>
      </div>

      {/* テーブル */}
      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        {reports.length === 0 ? (
          <div className="py-12 text-center">
            <p className="text-sm text-slate-400">読み間違い報告はまだありません。</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-100">
                  <Th>ID</Th>
                  <Th>対象テキスト</Th>
                  <Th>正しい読み</Th>
                  <Th>記事ID</Th>
                  <Th>報告日時</Th>
                  <Th>状態</Th>
                  <Th>操作</Th>
                </tr>
              </thead>
              <tbody>
                {reports.map((report) => (
                  <tr
                    key={report.id}
                    id={`report-${report.id}`}
                    className="border-b border-slate-50 transition last:border-0 hover:bg-slate-50/50"
                  >
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-400">
                      {report.id}
                    </td>
                    <td className="max-w-[200px] truncate px-4 py-3 font-medium text-slate-900">
                      {report.target_text}
                    </td>
                    <td className="max-w-[160px] truncate px-4 py-3 text-slate-600">
                      {report.correct_reading}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-400">
                      {report.article_id ?? '—'}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-400">
                      {formatDate(report.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      {report.approved ? (
                        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-700">
                          <span className="h-2 w-2 rounded-full bg-emerald-500" />
                          承認済み
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-amber-600">
                          <span className="h-2 w-2 rounded-full bg-amber-400" />
                          未承認
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        {report.notes && (
                          <button
                            type="button"
                            onClick={() => toggleExpand(report.id)}
                            className="inline-flex items-center gap-1 text-xs text-sky-600 transition hover:text-sky-800"
                          >
                            <svg
                              aria-hidden="true"
                              viewBox="0 0 24 24"
                              className={`h-3.5 w-3.5 transition-transform ${expandedIds.has(report.id) ? 'rotate-90' : ''}`}
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2"
                              strokeLinecap="round"
                            >
                              <path d="M9 6l6 6-6 6" />
                            </svg>
                            {expandedIds.has(report.id) ? 'メモを閉じる' : 'メモ'}
                          </button>
                        )}
                        {!report.approved && (
                          <>
                            {report.notes && (
                              <span className="text-xs text-slate-200">|</span>
                            )}
                            <button
                              type="button"
                              onClick={() => handleApprove(report)}
                              disabled={approvingIds.has(report.id)}
                              className="inline-flex items-center gap-1 rounded-full bg-emerald-600 px-3 py-1 text-xs font-medium text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              {approvingIds.has(report.id) ? (
                                <>
                                  <svg
                                    aria-hidden="true"
                                    className="h-3 w-3 animate-spin"
                                    viewBox="0 0 24 24"
                                    fill="none"
                                  >
                                    <circle
                                      className="opacity-25"
                                      cx="12"
                                      cy="12"
                                      r="10"
                                      stroke="currentColor"
                                      strokeWidth="4"
                                    />
                                    <path
                                      className="opacity-75"
                                      fill="currentColor"
                                      d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
                                    />
                                  </svg>
                                  処理中...
                                </>
                              ) : (
                                '承認'
                              )}
                            </button>
                          </>
                        )}
                      </div>
                      {expandedIds.has(report.id) && report.notes && (
                        <div className="mt-2 whitespace-pre-wrap rounded-lg border border-slate-100 bg-slate-50 p-3 text-xs text-slate-700">
                          {report.notes}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* フッター */}
        {reports.length > 0 && (
          <div className="border-t border-slate-100 px-4 py-3 text-center text-xs text-slate-400">
            全{reports.length}件
          </div>
        )}
      </div>
    </div>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="whitespace-nowrap px-4 py-3 text-xs font-medium text-slate-500">
      {children}
    </th>
  )
}
