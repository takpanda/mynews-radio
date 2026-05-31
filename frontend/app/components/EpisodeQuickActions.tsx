'use client'

import { useCallback } from 'react'

interface Props {
  hasScript: boolean
  hasArticles: boolean
}

function scrollToTop() {
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

export default function EpisodeQuickActions({ hasScript, hasArticles }: Props) {
  const handleTopClick = useCallback(() => {
    scrollToTop()
  }, [])

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-4 z-40 px-4">
      <div className="mx-auto flex max-w-3xl justify-center">
        <nav
          aria-label="エピソード操作"
          className="pointer-events-auto flex flex-wrap items-center justify-center gap-2 rounded-full border border-white/80 bg-white/90 px-3 py-3 shadow-[0_18px_40px_rgba(15,23,42,0.16)] backdrop-blur"
        >
          <a
            href="/"
            className="inline-flex min-h-11 items-center justify-center rounded-full bg-slate-900 px-4 text-sm font-medium text-white transition hover:bg-slate-800"
          >
            ホーム
          </a>
          <a
            href="#player"
            className="inline-flex min-h-11 items-center justify-center rounded-full border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50"
          >
            再生位置へ
          </a>
          {hasScript && (
            <a
              href="#script"
              className="inline-flex min-h-11 items-center justify-center rounded-full border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50"
            >
              台本
            </a>
          )}
          {hasArticles && (
            <a
              href="#articles"
              className="inline-flex min-h-11 items-center justify-center rounded-full border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 transition hover:border-slate-300 hover:bg-slate-50"
            >
              元記事
            </a>
          )}
          <button
            type="button"
            onClick={handleTopClick}
            className="inline-flex min-h-11 items-center justify-center rounded-full border border-sky-200 bg-sky-50 px-4 text-sm font-medium text-sky-700 transition hover:bg-sky-100"
          >
            トップへ戻る
          </button>
        </nav>
      </div>
    </div>
  )
}