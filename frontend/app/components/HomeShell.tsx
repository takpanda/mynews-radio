'use client'

import { useState, useMemo, useCallback, useRef } from 'react'
import Link from 'next/link'
import type { EpisodeListItem, PaginatedEpisodesResponse } from '../lib/api'
import { fetchEpisodes } from '../lib/api'
import type { Chapter } from '../lib/chapters'
import EpisodeAudioPlayer from './EpisodeAudioPlayer'
import SynthesizeAudioButton from './SynthesizeAudioButton'
import PushSubscriptionToggle from './PushSubscriptionToggle'

export interface HeroEpisode {
  id: number
  title: string
  subtitle: string
  dateLabel: string
  isCommentary: boolean
  sourceUrl: string | null
  audioUrl: string | null
  durationSeconds: number
  keyPoints?: string[]
  categories?: string[]
}

interface Props {
  latest: HeroEpisode | null
  chapters: Chapter[]
  initialEpisodes: EpisodeListItem[]
  initialHasNext: boolean
  isAuthenticated?: boolean
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
  if ((ep.categories ?? []).some((c) => TECH_CATEGORY_LABELS.has(c))) return 'tech'
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

const CATEGORY_THUMBNAIL_IMAGE: Record<Exclude<CategoryKey, 'all'>, string> = {
  general: '/images/categories/general.png',
  tech: '/images/categories/tech.jpg',
  commentary: '/images/categories/commentary.png',
}

// サムネイル画像の出し分けは保存済み categories を根拠にする（タイトル文字列は使わない）。
const TECH_CATEGORY_LABELS = new Set(['テック・IT', 'AI・先端技術'])

function cardCategoryKey(ep: EpisodeListItem): Exclude<CategoryKey, 'all'> {
  if (ep.type === 'commentary') return 'commentary'
  if ((ep.categories ?? []).some((c) => TECH_CATEGORY_LABELS.has(c))) return 'tech'
  return 'general'
}

function cardThumbnailLabel(ep: EpisodeListItem): string | null {
  if (ep.categories && ep.categories.length > 0) return ep.categories[0]
  if (ep.type === 'commentary') return '解説'
  return null
}

const MAX_HERO_TOPICS = 3

function heroTopics(latest: HeroEpisode | null): string[] {
  if (!latest) return []
  if (latest.keyPoints && latest.keyPoints.length > 0) {
    return latest.keyPoints.slice(0, MAX_HERO_TOPICS)
  }
  if (latest.categories && latest.categories.length > 0) {
    return latest.categories.slice(0, MAX_HERO_TOPICS)
  }
  return []
}

export default function HomeShell({ latest, chapters, initialEpisodes, initialHasNext, isAuthenticated = false }: Props) {
  const [category, setCategory] = useState<CategoryKey>('all')
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<EpisodeListItem[]>(initialEpisodes)
  const [hasNext, setHasNext] = useState(initialHasNext)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const searchLoadRef = useRef<boolean>(false)
  const heroTopicItems = useMemo(() => heroTopics(latest), [latest])

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
        if (ctrl.signal.aborted) { setLoading(false); searchLoadRef.current = false; return }
        allItems = [...allItems, ...data.items]
        offset += data.items.length
        more = data.has_next
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') { setLoading(false); searchLoadRef.current = false; return }
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
      setLoading(false)
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

            {heroTopicItems.length > 0 && (
              <div className="mt-3">
                <p className="text-xs font-medium tracking-wide text-slate-500">今回の3トピック</p>
                <ul className="mt-1.5 flex flex-wrap gap-1.5" aria-label="今回の3トピック">
                  {heroTopicItems.map((topic, index) => (
                    <li
                      key={`${topic}-${index}`}
                      className="inline-flex max-w-full items-center rounded-full border border-sky-100 bg-sky-50 px-2.5 py-1 text-xs font-medium leading-4 text-sky-700"
                    >
                      {topic}
                    </li>
                  ))}
                </ul>
              </div>
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

            <div className="mt-4">
              <PushSubscriptionToggle />
            </div>
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
        className="archive-panel scroll-mt-20 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"
      >
        <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="archive-kicker">PUBLIC ARCHIVE</p>
            <h2 className="mt-1 text-xl font-semibold tracking-tight text-slate-900">エピソード一覧</h2>
            <p className="mt-1 text-xs text-slate-500">気になる回を選んで、いつでも再生できます。</p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {CATEGORY_TABS.map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => handleCategoryChange(tab.key)}
                className={`rounded-full px-3.5 py-1.5 text-xs transition ${
                  category === tab.key
                    ? 'bg-sky-50 font-medium text-sky-700'
                    : 'border border-slate-200 bg-white text-slate-500 hover:bg-slate-50 hover:text-slate-800'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        <div className="relative mb-5 w-full sm:ml-auto sm:w-56">
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500"
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
              className="w-full rounded-full border border-slate-200 bg-slate-50 py-2 pl-8 pr-3 text-xs text-slate-800 placeholder:text-slate-400 transition focus:border-sky-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-sky-100"
              aria-label="エピソードを検索"
            />
          </div>

        {filteredEpisodes.length === 0 ? (
          <p className="rounded-xl border border-dashed border-slate-200 py-10 text-center text-sm text-slate-500">
            {loading ? '読み込み中...' : '該当するエピソードがありません'}
          </p>
        ) : (
          <div>
            {groupedByMonth.map((group) => (
              <div key={group.month} className="mb-7 last:mb-0">
                <p className="mb-3 text-xs font-medium tracking-[0.18em] text-slate-500">{group.month}</p>
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {group.items.map((ep) => {
                    const thumbnailImage = CATEGORY_THUMBNAIL_IMAGE[cardCategoryKey(ep)]
                    const thumbnailLabel = cardThumbnailLabel(ep)
                    return (
                    <article key={ep.id} className="archive-card group">
                      <Link
                        href={`/episodes/${ep.id}`}
                        className="block h-full"
                      >
                        <div className="archive-thumb">
                          <img
                            src={thumbnailImage}
                            alt=""
                            className="absolute inset-0 h-full w-full object-contain"
                          />
                          <span className="archive-thumb-date">{dayLabel(ep.date)}</span>
                          {thumbnailLabel && (
                            <span className="archive-thumb-category">{thumbnailLabel}</span>
                          )}
                          <span className="archive-play-icon" aria-hidden="true">
                            <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4"><path d="M8 5.5v13a1 1 0 0 0 1.52.86l10.2-6.5a1 1 0 0 0 0-1.7L9.52 4.63A1 1 0 0 0 8 5.5Z" /></svg>
                          </span>
                        </div>
                        <div className="flex min-h-[174px] flex-col p-4">
                          <div className="flex items-center justify-between gap-2">
                            <p className="text-xs text-slate-500">{dayLabel(ep.date)}{durationLabel(ep.duration) && ` ・ ${durationLabel(ep.duration)}`}</p>
                            {ep.status === 'generating' && (
                              <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700">
                                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />生成中
                              </span>
                            )}
                          </div>
                          {ep.categories && ep.categories.length > 0 && (
                            <div className="mt-2 flex flex-wrap gap-1.5" aria-label="カテゴリ">
                              {ep.categories.slice(0, 3).map((category) => (
                                <span
                                  key={category}
                                  className="inline-flex max-w-full items-center rounded-full border border-sky-100 bg-sky-50 px-2 py-0.5 text-[10px] font-medium leading-4 text-sky-700"
                                >
                                  {category}
                                </span>
                              ))}
                            </div>
                          )}
                          <h3 className="archive-card-title mt-2">{ep.title || `エピソード #${ep.id}`}</h3>
                          <p className="archive-card-description mt-2">{ep.subtitle || 'このエピソードの詳細を聴いてみましょう。'}</p>
                          <span className="mt-auto inline-flex items-center gap-1.5 pt-4 text-xs font-medium text-sky-700">▶ 再生する</span>
                        </div>
                      </Link>
                      {ep.has_script && !ep.audio_url && (
                        <div className="border-t border-slate-200 px-4 pb-3 pt-2">
                          {isAuthenticated ? <SynthesizeAudioButton episodeId={ep.id} compact /> : <Link href="/admin/login" className="rounded-sm text-xs text-sky-700 underline decoration-sky-300 underline-offset-2 transition hover:text-sky-800 hover:decoration-sky-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300 focus-visible:ring-offset-2 focus-visible:ring-offset-white">ログインして再合成</Link>}
                        </div>
                      )}
                    </article>
                    )
                  })}
                </div>
              </div>
            ))}

            {loadError && (
              <p className="mt-3 text-center text-xs text-red-600">{loadError}</p>
            )}

            {hasNext && !loadError && (
              <button
                type="button"
                onClick={handleLoadMore}
                disabled={loading}
                className="mt-5 w-full rounded-lg border border-slate-200 py-2.5 text-center text-sm text-slate-500 transition hover:bg-slate-50 hover:text-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading ? '読み込み中...' : 'もっと見る'}
              </button>
            )}

            {!hasNext && items.length > 0 && (
              <p className="mt-5 text-center text-xs text-slate-500">
                これ以上ありません
              </p>
            )}
          </div>
        )}
      </section>
    </div>
  )
}
