'use client'

import { useState, useMemo, useCallback, useRef } from 'react'
import Link from 'next/link'
import type { EpisodeListItem, PaginatedEpisodesResponse } from '../lib/api'
import { fetchEpisodes } from '../lib/api'
import type { Chapter } from '../lib/chapters'
import EpisodeAudioPlayer from './EpisodeAudioPlayer'
import SynthesizeAudioButton from './SynthesizeAudioButton'

export interface HeroEpisode {
  id: number
  title: string
  subtitle: string
  dateLabel: string
  isCommentary: boolean
  sourceUrl: string | null
  audioUrl: string | null
  durationSeconds: number
}

interface Props {
  latest: HeroEpisode | null
  chapters: Chapter[]
  initialEpisodes: EpisodeListItem[]
  initialHasNext: boolean
}

type CategoryKey = 'all' | 'tech' | 'general' | 'commentary'

const CATEGORY_TABS: Array<{ key: CategoryKey; label: string }> = [
  { key: 'all', label: 'すべて' },
  { key: 'tech', label: 'テック' },
  { key: 'general', label: '一般' },
  { key: 'commentary', label: '解説' },
]

const PAGE_SIZE = 20

function categorize(ep: EpisodeListItem): Exclude<CategoryKey, 'all'> {
  if (ep.type === 'commentary') return 'commentary'
  if ((ep.title || '').includes('テック')) return 'tech'
  return 'general'
}

function monthLabel(dateStr: string): string {
  const [y, m] = dateStr.slice(0, 10).split('-')
  if (!y || !m) return dateStr
  return `${y}年${Number(m)}月`
}

function dayLabel(dateStr: string): string {
  const [, m, d] = dateStr.slice(0, 10).split('-')
  if (!m || !d) return dateStr
  return `${Number(m)}月${Number(d)}日`
}

function durationLabel(seconds: number): string {
  if (!seconds || seconds <= 0) return ''
  return `${Math.max(1, Math.round(seconds / 60))}分`
}

export default function HomeShell({ latest, chapters, initialEpisodes, initialHasNext }: Props) {
  const [category, setCategory] = useState<CategoryKey>('all')
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<EpisodeListItem[]>(initialEpisodes)
  const [hasNext, setHasNext] = useState(initialHasNext)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const searchLoadRef = useRef<boolean>(false)

  const filteredEpisodes = useMemo(() => {
    const q = query.trim().toLowerCase()
    return items.filter((ep) => {
      if (category !== 'all' && categorize(ep) !== category) return false
      if (!q) return true
      return (
        (ep.title || '').toLowerCase().includes(q) ||
        (ep.subtitle || '').toLowerCase().includes(q)
      )
    })
  }, [items, category, query])

  const groupedByMonth = useMemo(() => {
    const groups: Array<{ month: string; items: EpisodeListItem[] }> = []
    for (const ep of filteredEpisodes) {
      const month = monthLabel(ep.date)
      const last = groups.at(-1)
      if (last && last.month === month) {
        last.items.push(ep)
      } else {
        groups.push({ month, items: [ep] })
      }
    }
    return groups
  }, [filteredEpisodes])

  const loadAllRemaining = useCallback(async (currentItems: EpisodeListItem[], currentHasNext: boolean) => {
    if (!currentHasNext || searchLoadRef.current) return
    searchLoadRef.current = true
    setLoading(true)
    let allItems = [...currentItems]
    let offset = allItems.length
    let more: boolean = currentHasNext
    while (more) {
      abortRef.current?.abort()
      const ctrl = new AbortController()
      abortRef.current = ctrl
      try {
        const data = await fetchEpisodes(PAGE_SIZE, offset, ctrl.signal) as PaginatedEpisodesResponse
        if (ctrl.signal.aborted) { searchLoadRef.current = false; return }
        allItems = [...allItems, ...data.items]
        offset += data.items.length
        more = data.has_next
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') { searchLoadRef.current = false; return }
        setLoadError('読み込みに失敗しました')
        searchLoadRef.current = false
        setLoading(false)
        return
      }
    }
    setItems(allItems)
    setHasNext(false)
    setLoading(false)
    searchLoadRef.current = false
  }, [])

  const handleLoadMore = useCallback(async () => {
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setLoading(true)
    setLoadError(null)
    try {
      const data = await fetchEpisodes(PAGE_SIZE, items.length, ctrl.signal) as PaginatedEpisodesResponse
      if (ctrl.signal.aborted) return
      setItems(prev => [...prev, ...data.items])
      setHasNext(data.has_next)
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      setLoadError('読み込みに失敗しました')
    } finally {
      if (!ctrl.signal.aborted) {
        setLoading(false)
      }
    }
  }, [items.length])

  const handleCategoryChange = (key: CategoryKey) => {
    abortRef.current?.abort()
    abortRef.current = new AbortController()
    searchLoadRef.current = false
    setCategory(key)
    setItems(initialEpisodes)
    setHasNext(initialHasNext)
    setLoadError(null)
  }

  const handleSearchChange = (value: string) => {
    setQuery(value)
    loadAllRemaining(items, hasNext)
  }

  return (
    <div className="space-y-6">
      {/* 最新エピソード（ヒーロープレーヤー） */}
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
        {latest ? (
          <>
            <p className="text-xs text-slate-400">最新エピソード ・ {latest.dateLabel}</p>
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <Link
                href={`/episodes/${latest.id}`}
                className="text-lg font-semibold leading-snug text-slate-900 transition hover:text-sky-700 sm:text-xl"
              >
                {latest.title || `エピソード #${latest.id}`}
              </Link>
              {latest.isCommentary && (
                <span className="inline-flex items-center rounded-full bg-violet-50 px-2.5 py-0.5 text-xs font-medium text-violet-700">
                  解説
                </span>
              )}
            </div>
            {latest.subtitle && (
              <p className="mt-1 text-sm leading-6 text-slate-500">{latest.subtitle}</p>
            )}

            {latest.audioUrl ? (
              <div className="mt-5">
                <EpisodeAudioPlayer
                  audioUrl={latest.audioUrl}
                  title={latest.title || `エピソード #${latest.id}`}
                  durationSeconds={latest.durationSeconds}
                  chapters={chapters}
                />
              </div>
            ) : (
              <div className="mt-5 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-5 text-center text-sm text-slate-500">
                音声ファイルを準備中です
              </div>
            )}
          </>
        ) : (
          <div className="py-10 text-center">
            <p className="text-lg font-semibold text-slate-900">まだエピソードがありません</p>
            <p className="mt-2 text-sm leading-7 text-slate-500">
              右上の「番組を生成」から今日の番組を作成すると、ここに最新エピソードが表示されます。
            </p>
          </div>
        )}
      </section>

      {/* アーカイブ */}
      <section
        id="archive"
        className="scroll-mt-20 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"
      >
        <div className="flex flex-wrap items-center gap-1.5">
          {CATEGORY_TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => handleCategoryChange(tab.key)}
              className={`rounded-full px-3.5 py-1.5 text-xs transition ${
                category === tab.key
                  ? 'bg-slate-900 font-medium text-white'
                  : 'text-slate-500 hover:bg-slate-100 hover:text-slate-800'
              }`}
            >
              {tab.label}
            </button>
          ))}
          <div className="relative ml-auto w-full sm:w-48">
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
              onChange={(e) => handleSearchChange(e.target.value)}
              placeholder="検索"
              className="w-full rounded-full border border-slate-200 bg-slate-50 py-1.5 pl-8 pr-3 text-xs text-slate-800 placeholder:text-slate-400 transition focus:border-sky-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100"
              aria-label="エピソードを検索"
            />
          </div>
        </div>

        {filteredEpisodes.length === 0 ? (
          <p className="py-10 text-center text-sm text-slate-400">
            {loading ? '読み込み中...' : '該当するエピソードがありません'}
          </p>
        ) : (
          <div className="mt-4">
            {groupedByMonth.map((group) => (
              <div key={group.month}>
                <p className="mb-1 mt-4 text-xs text-slate-400 first:mt-0">{group.month}</p>
                <div className="border-t border-slate-100">
                  {group.items.map((ep) => (
                    <div key={ep.id} className="border-b border-slate-100">
                      <Link
                        href={`/episodes/${ep.id}`}
                        className="flex items-center gap-3 px-1 py-2.5 transition hover:bg-slate-50"
                      >
                        <svg
                          aria-hidden="true"
                          viewBox="0 0 24 24"
                          className="h-4 w-4 shrink-0 text-slate-400"
                          fill="currentColor"
                        >
                          <path d="M8 5.5v13a1 1 0 0 0 1.52.86l10.2-6.5a1 1 0 0 0 0-1.7L9.52 4.63A1 1 0 0 0 8 5.5Z" />
                        </svg>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <p className="truncate text-sm text-slate-900">
                              {ep.title || `エピソード #${ep.id}`}
                            </p>
                            {ep.status === 'generating' && (
                              <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-700">
                                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
                                生成中
                              </span>
                            )}
                          </div>
                          <p className="mt-0.5 text-xs text-slate-400">
                            {dayLabel(ep.date)}
                            {durationLabel(ep.duration) && ` ・ ${durationLabel(ep.duration)}`}
                          </p>
                        </div>
                        {ep.type === 'commentary' && (
                          <span className="shrink-0 rounded-full bg-violet-50 px-2 py-0.5 text-[11px] font-medium text-violet-700">
                            解説
                          </span>
                        )}
                      </Link>
                      {ep.has_script && !ep.audio_url && (
                        <div className="px-1 pb-2.5 pl-8">
                          <SynthesizeAudioButton episodeId={ep.id} compact />
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}

            {loadError && (
              <p className="mt-3 text-center text-xs text-red-500">{loadError}</p>
            )}

            {hasNext && !loadError && (
              <button
                type="button"
                onClick={handleLoadMore}
                disabled={loading}
                className="mt-1 w-full rounded-lg py-2.5 text-center text-sm text-slate-500 transition hover:bg-slate-50 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading ? '読み込み中...' : 'もっと見る'}
              </button>
            )}

            {!hasNext && items.length > 0 && (
              <p className="mt-4 text-center text-xs text-slate-400">
                これ以上ありません
              </p>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
