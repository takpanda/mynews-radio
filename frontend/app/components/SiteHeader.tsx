'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import GenerateEpisodeButton from './GenerateEpisodeButton'

export default function SiteHeader({ isAuthenticated = false }: { isAuthenticated?: boolean }) {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open])

  return (
    <>
      <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-3xl items-center justify-between px-3 sm:px-6">
          <Link href="/" className="flex shrink-0 items-center gap-1.5 text-slate-900 sm:gap-2">
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              className="h-4 w-4 shrink-0 text-sky-600 sm:h-5 sm:w-5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="12" cy="12" r="2" />
              <path d="M16.24 7.76a6 6 0 0 1 0 8.49" />
              <path d="M7.76 16.24a6 6 0 0 1 0-8.49" />
              <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
              <path d="M4.93 19.07a10 10 0 0 1 0-14.14" />
            </svg>
            <span className="whitespace-nowrap text-xs font-semibold sm:text-sm">MyNews Radio</span>
          </Link>
          <nav className="flex shrink-0 items-center gap-1 sm:gap-2">
            <Link
              href="/#archive"
              className="whitespace-nowrap rounded-full px-2 py-1.5 text-xs text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 sm:px-3 sm:text-sm"
            >
              アーカイブ
            </Link>
            {isAuthenticated ? (
              <button
                type="button"
                onClick={() => setOpen(true)}
                className="whitespace-nowrap rounded-full border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-800 transition hover:border-slate-400 hover:bg-slate-50 sm:px-3.5 sm:text-sm"
              >
                番組を生成
              </button>
            ) : (
              <Link
                href="/admin/login"
                className="whitespace-nowrap rounded-full border border-sky-200 bg-sky-50 px-2.5 py-1.5 text-xs font-medium text-sky-700 transition hover:bg-sky-100 sm:px-3.5 sm:text-sm"
              >
                ログインして生成
              </Link>
            )}
          </nav>
        </div>
      </header>

      {/* 生成パネルは閉じてもポーリングを継続するため常にマウントし、表示のみ切り替える */}
      <div
        className={`fixed inset-0 z-50 ${open ? '' : 'pointer-events-none'}`}
        aria-hidden={!open}
      >
        <div
          className={`absolute inset-0 bg-slate-900/40 transition-opacity duration-300 ${open ? 'opacity-100' : 'opacity-0'}`}
          onClick={() => setOpen(false)}
        />
        <div
          className={`absolute inset-y-0 right-0 flex w-full max-w-2xl flex-col bg-slate-50 shadow-2xl transition-transform duration-300 ${open ? 'translate-x-0' : 'translate-x-full'}`}
          role="dialog"
          aria-modal="true"
          aria-label="番組を生成"
        >
          <div className="flex items-center justify-between border-b border-slate-200 bg-white/90 px-4 py-3 backdrop-blur sm:px-5">
            <p className="text-sm font-semibold text-slate-900">番組を生成</p>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="flex h-8 w-8 items-center justify-center rounded-full text-slate-500 transition hover:bg-slate-100 hover:text-slate-800"
              aria-label="閉じる"
            >
              <svg
                aria-hidden="true"
                viewBox="0 0 24 24"
                className="h-4.5 w-4.5"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              >
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-4 sm:p-5">
            <GenerateEpisodeButton isAuthenticated={isAuthenticated} />
          </div>
        </div>
      </div>
    </>
  )
}
