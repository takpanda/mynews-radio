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
      className="fixed inset-x-0 bottom-0 z-40 h-14 border-t border-slate-200 bg-white lg:hidden"
    >
      <div className="mx-auto flex h-full max-w-3xl items-center justify-center gap-1 px-2">
        <a
          href="/"
          className="flex h-full flex-1 items-center justify-center rounded-lg px-1 text-xs font-medium text-slate-700 transition hover:bg-slate-100"
        >
          ホーム
        </a>
        <a
          href="#player"
          className="flex h-full flex-1 items-center justify-center rounded-lg px-1 text-xs font-medium text-slate-700 transition hover:bg-slate-100"
        >
          再生位置へ
        </a>
        {hasScript && (
          <a
            href="#script"
            className="flex h-full flex-1 items-center justify-center rounded-lg px-1 text-xs font-medium text-slate-700 transition hover:bg-slate-100"
          >
            台本
          </a>
        )}
        {hasArticles && (
          <a
            href="#articles"
            className="flex h-full flex-1 items-center justify-center rounded-lg px-1 text-xs font-medium text-slate-700 transition hover:bg-slate-100"
          >
            元記事
          </a>
        )}
        <button
          type="button"
          onClick={handleTopClick}
          className="flex h-full flex-1 items-center justify-center rounded-lg px-1 text-xs font-medium text-sky-700 transition hover:bg-sky-50"
        >
          トップへ戻る
        </button>
      </div>
    </nav>
  )
}
