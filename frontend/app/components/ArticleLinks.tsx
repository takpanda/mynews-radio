'use client'

import { useState, useEffect, useRef } from 'react'
import type { Article } from '../lib/api'

interface Props {
  articles: Article[]
  sourceUrl?: string | null
  onReportArticle?: (article: Article) => void
}

function LinkIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      className="mt-0.5 h-4 w-4 shrink-0 text-slate-400"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
      <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
    </svg>
  )
}

function ArticleActions({ article, onReport }: { article: Article; onReport?: (article: Article) => void }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        type="button"
        onClick={(e) => { e.preventDefault(); setOpen((v) => !v) }}
        className="rounded-full p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600"
        aria-label="その他"
        aria-haspopup="true"
        aria-expanded={open}
      >
        <svg aria-hidden="true" viewBox="0 0 24 24" className="h-4 w-4" fill="currentColor">
          <circle cx="12" cy="5.5" r="1.5" />
          <circle cx="12" cy="12" r="1.5" />
          <circle cx="12" cy="18.5" r="1.5" />
        </svg>
      </button>
      {open && onReport && (
        <div
          className="absolute right-0 top-full z-20 mt-1 min-w-40 rounded-xl border border-slate-200 bg-white py-1 shadow-lg"
          role="menu"
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => { setOpen(false); onReport(article) }}
            className="flex w-full items-center gap-2 px-4 py-2 text-left text-sm text-slate-700 transition hover:bg-slate-50"
          >
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              className="h-4 w-4 text-slate-400"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 20h9" />
              <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
            </svg>
            読み間違いを報告
          </button>
        </div>
      )}
    </div>
  )
}

export default function ArticleLinks({ articles, sourceUrl, onReportArticle }: Props) {
  const articlesWithUrl = articles.filter((a) => a.url)

  if (articlesWithUrl.length === 0 && !sourceUrl) return null

  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-4 shadow-sm sm:px-5">
      {sourceUrl && (
        <a
          href={sourceUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-start gap-3 border-b border-slate-100 py-3.5 transition last:border-b-0 hover:bg-slate-50"
        >
          <LinkIcon />
          <div className="min-w-0">
            <p className="break-all text-sm text-sky-700 line-clamp-2 hover:underline">
              {sourceUrl}
            </p>
            <p className="mt-0.5 text-xs text-slate-400">解説元URL</p>
          </div>
        </a>
      )}
      {articlesWithUrl.map((article) => (
        <div
          key={article.id}
          className="group flex items-start gap-3 border-b border-slate-100 py-3.5 transition last:border-b-0 hover:bg-slate-50"
        >
          <a
            href={article.url!}
            target="_blank"
            rel="noopener noreferrer"
            className="flex min-w-0 flex-1 items-start gap-3"
          >
            <LinkIcon />
            <div className="min-w-0">
              <p className="text-sm text-sky-700 line-clamp-2 hover:underline">{article.title}</p>
              {article.source && <p className="mt-0.5 text-xs text-slate-400">{article.source}</p>}
            </div>
          </a>
          {onReportArticle && (
            <div className="shrink-0 opacity-60 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity">
              <ArticleActions article={article} onReport={onReportArticle} />
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
