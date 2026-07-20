'use client'

import { useState } from 'react'
import type { AdminMisreadingReport } from '../lib/admin-misreading-reports'

interface Props {
  initialData: AdminMisreadingReport[]
}

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

export default function AdminMisreadingReportsShell({ initialData }: Props) {
  const [reports] = useState<AdminMisreadingReport[]>(initialData)
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set())

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
                  <Th>メモ</Th>
                </tr>
              </thead>
              <tbody>
                {reports.map((report) => (
                  <tr
                    key={report.id}
                    className="border-b border-slate-50 transition last:border-0 hover:bg-slate-50/50"
                  >
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-400">
                      {report.id}
                    </td>
                    <td className="max-w-[220px] truncate px-4 py-3 font-medium text-slate-900">
                      {report.target_text}
                    </td>
                    <td className="max-w-[180px] truncate px-4 py-3 text-slate-600">
                      {report.correct_reading}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-400">
                      {report.article_id ?? '—'}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-400">
                      {formatDate(report.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      {report.notes ? (
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
                          {expandedIds.has(report.id) ? '閉じる' : '表示'}
                        </button>
                      ) : (
                        <span className="text-xs text-slate-300">—</span>
                      )}
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
