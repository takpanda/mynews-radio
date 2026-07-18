'use client'

import { useEffect, useRef } from 'react'
import type { DuplicateEpisodeInfo } from '../lib/api'

interface Props {
  type: 'duplicate-found' | 'search-error'
  episodes: DuplicateEpisodeInfo[]
  sourceUrl: string
  onCancel: () => void
  onContinue: () => void
}

export default function DuplicateUrlConfirmDialog({ type, episodes, sourceUrl, onCancel, onContinue }: Props) {
  const backdropRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onCancel])

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === backdropRef.current) onCancel()
  }

  return (
    <div
      ref={backdropRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onClick={handleBackdropClick}
    >
      <div
        className="flex w-full max-w-lg flex-col rounded-2xl border border-slate-200 bg-white shadow-xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="duplicate-dialog-title"
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <h2 id="duplicate-dialog-title" className="text-base font-semibold text-slate-900">
            {type === 'duplicate-found' ? 'URLの重複を検出しました' : '重複の確認に失敗しました'}
          </h2>
          <button
            type="button"
            onClick={onCancel}
            className="flex h-8 w-8 items-center justify-center rounded-full text-slate-500 transition hover:bg-slate-100 hover:text-slate-800"
            aria-label="閉じる"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4.5 w-4.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>

        {type === 'duplicate-found' ? (
          <div className="space-y-4 overflow-y-auto px-5 py-4">
            <p className="text-sm leading-6 text-slate-600">
              以下のURLは既に解説済みです。続行すると重複した内容が生成されます。
            </p>
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-800">
              <p className="break-all">{sourceUrl}</p>
            </div>
            {episodes.length > 0 && (
              <div className="space-y-2">
                <p className="text-xs font-medium text-slate-500">該当するエピソード</p>
                <ul className="space-y-1.5">
                  {episodes.map((ep) => (
                    <li key={ep.id} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs leading-5 text-slate-700">
                      <span className="font-medium">{ep.title || `エピソード #${ep.id}`}</span>
                      <span className="ml-2 text-slate-400">{ep.episode_date}</span>
                      <span className="ml-2 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">
                        {ep.status}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-4 overflow-y-auto px-5 py-4">
            <p className="text-sm leading-6 text-slate-600">
              既存のエピソードとの重複を確認できませんでした。続行する場合は、重複の可能性があることをご了承ください。
            </p>
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-500">
              <p className="break-all">{sourceUrl}</p>
            </div>
          </div>
        )}

        <div className="flex items-center justify-end gap-2 border-t border-slate-100 px-5 py-4">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
          >
            中止
          </button>
          <button
            type="button"
            onClick={onContinue}
            className="inline-flex items-center gap-1.5 rounded-full bg-sky-600 px-5 py-2 text-sm font-medium text-white transition hover:bg-sky-700"
          >
            生成を続行
          </button>
        </div>
      </div>
    </div>
  )
}
