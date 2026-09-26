import Link from 'next/link'
import AdminNav from '../../components/AdminNav'
import { requireAdminSessionForPage } from '../auth'
import {
  AWAITING_REVIEW_LIST_LIMIT,
  fetchAwaitingReviewEpisodes,
  isAwaitingReviewListTruncated,
} from '../../lib/admin-episodes'
import { formatEventDateTime } from '../../lib/admin-episode-logs'

export default async function AdminAwaitingReviewEpisodesPage() {
  await requireAdminSessionForPage()

  let episodes: Awaited<ReturnType<typeof fetchAwaitingReviewEpisodes>> = []
  let error: string | null = null

  try {
    episodes = await fetchAwaitingReviewEpisodes()
  } catch {
    error = 'エラーが発生しました。しばらく後でもう一度お試しください。'
  }

  const truncated = !error && isAwaitingReviewListTruncated(episodes)

  return (
    <main className="mx-auto max-w-5xl px-4 pb-24 pt-6 sm:px-6">
      <AdminNav />
      <h1 className="text-lg font-semibold text-slate-900">確認待ちの台本</h1>
      <p className="mt-1 text-sm text-slate-500">確認待ち（awaiting_review）のエピソード一覧です。</p>

      {error ? (
        <div className="mt-4 rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>
      ) : episodes.length === 0 ? (
        <p className="mt-4 text-sm text-slate-400">確認待ちのエピソードはありません。</p>
      ) : (
        <>
          {truncated && (
            <p className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
              表示件数が上限（{AWAITING_REVIEW_LIST_LIMIT}件）に達しています。実際の件数はこれより多い可能性があります。
            </p>
          )}
          <ul className="mt-4 space-y-2">
            {episodes.map((episode) => (
              <li key={episode.id}>
                <Link
                  href={`/admin/episodes/${episode.id}/review`}
                  className="flex min-h-11 flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm shadow-sm transition hover:border-slate-300"
                >
                  <span className="font-medium text-slate-900">
                    {episode.episode_date} 第{episode.seq}回
                  </span>
                  <span className="text-xs text-slate-500">更新: {formatEventDateTime(episode.updated_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </main>
  )
}
