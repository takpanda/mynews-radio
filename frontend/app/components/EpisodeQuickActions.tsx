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
    <nav
      aria-label="エピソード操作"
      className="fixed inset-x-0 bottom-0 z-40 h-14 border-t border-slate-200 bg-white
        lg:inset-x-auto lg:bottom-6 lg:left-1/2 lg:h-16 lg:w-full lg:max-w-6xl lg:-translate-x-1/2
        lg:rounded-2xl lg:border-slate-200/60 lg:bg-white/85 lg:backdrop-blur-md
        lg:shadow-[0_4px_24px_rgba(15,23,42,0.08)]"
    >
      <div className="mx-auto flex h-full max-w-3xl items-center justify-center gap-1 px-2 lg:gap-2 lg:px-4">
        <a
          href="/"
          className="flex h-full flex-1 items-center justify-center rounded-lg px-1 text-xs font-medium text-slate-700 transition hover:bg-slate-100 lg:px-3 lg:text-sm"
        >
          ホーム
        </a>
        <a
          href="#player"
          className="flex h-full flex-1 items-center justify-center rounded-lg px-1 text-xs font-medium text-slate-700 transition hover:bg-slate-100 lg:px-3 lg:text-sm"
        >
          再生位置へ
        </a>
        {hasScript && (
          <a
            href="#script"
            className="flex h-full flex-1 items-center justify-center rounded-lg px-1 text-xs font-medium text-slate-700 transition hover:bg-slate-100 lg:px-3 lg:text-sm"
          >
            台本
          </a>
        )}
        {hasArticles && (
          <a
            href="#articles"
            className="flex h-full flex-1 items-center justify-center rounded-lg px-1 text-xs font-medium text-slate-700 transition hover:bg-slate-100 lg:px-3 lg:text-sm"
          >
            元記事
          </a>
        )}
        <button
          type="button"
          onClick={handleTopClick}
          className="flex h-full flex-1 items-center justify-center rounded-lg px-1 text-xs font-medium text-sky-700 transition hover:bg-sky-50 lg:px-3 lg:text-sm"
        >
          トップへ戻る
        </button>
      </div>
    </nav>
  )
}
