'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { AWAITING_REVIEW_LIST_LIMIT, fetchAwaitingReviewEpisodesClient } from '../lib/admin-episodes'

const NAV_LINKS: Array<{ href: string; label: string; badge?: boolean }> = [
  { href: '/admin/episodes', label: '確認待ち一覧', badge: true },
  { href: '/admin/programs', label: '番組・MC管理' },
  { href: '/admin/prompts', label: 'プロンプト管理' },
  { href: '/admin/dictionary', label: '辞書管理' },
  { href: '/admin/misreading-reports', label: '読み間違い報告' },
  { href: '/admin/settings/voice', label: 'ボイス設定' },
]

function AwaitingReviewBadge({ count }: { count: number }) {
  const label = count >= AWAITING_REVIEW_LIST_LIMIT ? `${AWAITING_REVIEW_LIST_LIMIT}+` : String(count)
  return (
    <span
      aria-label={`確認待ち${label}件`}
      className="inline-flex min-w-[1.25rem] items-center justify-center rounded-full bg-rose-500 px-1.5 py-0.5 text-[11px] font-semibold leading-none text-white"
    >
      {label}
    </span>
  )
}

export default function AdminNav() {
  const router = useRouter()
  const [menuOpen, setMenuOpen] = useState(false)
  const [awaitingReviewCount, setAwaitingReviewCount] = useState<number | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchAwaitingReviewEpisodesClient()
      .then((episodes) => {
        if (!cancelled) setAwaitingReviewCount(episodes.length)
      })
      .catch(() => {
        if (!cancelled) setAwaitingReviewCount(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const logout = async () => {
    await fetch('/api/admin/logout', { method: 'POST' })
    router.push('/admin/login')
    router.refresh()
  }

  return (
    <nav className="mb-6 rounded-xl bg-slate-900 text-sm text-white">
      <div className="flex items-center gap-4 px-4 py-3">
        <span className="font-semibold">管理</span>

        <div className="hidden items-center gap-4 lg:flex">
          {NAV_LINKS.map((link) => (
            <Link key={link.href} href={link.href} className="flex items-center gap-1.5">
              {link.label}
              {link.badge && awaitingReviewCount !== null && awaitingReviewCount > 0 && (
                <AwaitingReviewBadge count={awaitingReviewCount} />
              )}
            </Link>
          ))}
          <Link className="ml-auto" href="/">
            公開サイトへ
          </Link>
          <button type="button" onClick={logout}>
            ログアウト
          </button>
        </div>

        <button
          type="button"
          onClick={() => setMenuOpen((open) => !open)}
          aria-expanded={menuOpen}
          aria-controls="admin-nav-mobile-menu"
          aria-label={menuOpen ? 'メニューを閉じる' : 'メニューを開く'}
          className="relative ml-auto flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-white lg:hidden"
        >
          {awaitingReviewCount !== null && awaitingReviewCount > 0 && !menuOpen && (
            <span className="absolute right-2.5 top-2.5">
              <AwaitingReviewBadge count={awaitingReviewCount} />
            </span>
          )}
          <span aria-hidden="true" className="relative block h-4 w-5">
            <span
              className={`absolute left-0 top-0 h-0.5 w-5 rounded bg-white transition ${menuOpen ? 'translate-y-[7px] rotate-45' : ''}`}
            />
            <span
              className={`absolute left-0 top-[7px] h-0.5 w-5 rounded bg-white transition ${menuOpen ? 'opacity-0' : ''}`}
            />
            <span
              className={`absolute left-0 top-[14px] h-0.5 w-5 rounded bg-white transition ${menuOpen ? '-translate-y-[7px] -rotate-45' : ''}`}
            />
          </span>
        </button>
      </div>

      {menuOpen && (
        <div id="admin-nav-mobile-menu" className="space-y-1 border-t border-white/10 px-2 pb-3 pt-2 lg:hidden">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              onClick={() => setMenuOpen(false)}
              className="flex min-h-11 items-center justify-between gap-2 rounded-lg px-3 py-2"
            >
              <span>{link.label}</span>
              {link.badge && awaitingReviewCount !== null && awaitingReviewCount > 0 && (
                <AwaitingReviewBadge count={awaitingReviewCount} />
              )}
            </Link>
          ))}
          <Link
            href="/"
            onClick={() => setMenuOpen(false)}
            className="flex min-h-11 items-center rounded-lg px-3 py-2"
          >
            公開サイトへ
          </Link>
          <button
            type="button"
            onClick={logout}
            className="flex min-h-11 w-full items-center rounded-lg px-3 py-2 text-left"
          >
            ログアウト
          </button>
        </div>
      )}
    </nav>
  )
}
