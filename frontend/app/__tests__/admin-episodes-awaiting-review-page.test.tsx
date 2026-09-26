/** @jest-environment node */

jest.mock('next/headers', () => ({
  cookies: jest.fn(() => ({ get: jest.fn(() => ({ value: 'valid-token' })) })),
}))
jest.mock('next/navigation', () => ({
  redirect: jest.fn(() => { throw new Error('NEXT_REDIRECT') }),
  useRouter: jest.fn(() => ({ push: jest.fn(), refresh: jest.fn() })),
}))
jest.mock('../lib/admin-episodes', () => ({
  ...jest.requireActual('../lib/admin-episodes'),
  fetchAwaitingReviewEpisodes: jest.fn(),
}))

import { renderToStaticMarkup } from 'react-dom/server'
import AdminAwaitingReviewEpisodesPage from '../admin/episodes/page'
import { fetchAwaitingReviewEpisodes, AWAITING_REVIEW_LIST_LIMIT } from '../lib/admin-episodes'
import type { AdminEpisodeSummary } from '../lib/admin-episodes'

function episode(overrides: Partial<AdminEpisodeSummary> = {}): AdminEpisodeSummary {
  return {
    id: 1,
    episode_date: '2026-09-20',
    seq: 1,
    status: 'awaiting_review',
    phase: null,
    generation_message: null,
    review_mode: null,
    updated_at: '2026-09-20T10:00:00+00:00',
    ...overrides,
  }
}

describe('AdminAwaitingReviewEpisodesPage', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    global.fetch = jest.fn().mockResolvedValue({ ok: true })
  })

  it('確認待ちエピソードへのレビュー画面リンクを描画する', async () => {
    ;(fetchAwaitingReviewEpisodes as jest.Mock).mockResolvedValue([episode({ id: 42 })])
    const element = await AdminAwaitingReviewEpisodesPage()
    const html = renderToStaticMarkup(element)
    expect(html).toContain('/admin/episodes/42/review')
    expect(html).toContain('確認待ちの台本')
  })

  it('0件の場合は空状態メッセージを表示する', async () => {
    ;(fetchAwaitingReviewEpisodes as jest.Mock).mockResolvedValue([])
    const element = await AdminAwaitingReviewEpisodesPage()
    expect(renderToStaticMarkup(element)).toContain('確認待ちのエピソードはありません')
  })

  it('取得に失敗した場合はエラーメッセージを表示する', async () => {
    ;(fetchAwaitingReviewEpisodes as jest.Mock).mockRejectedValue(new Error('boom'))
    const element = await AdminAwaitingReviewEpisodesPage()
    expect(renderToStaticMarkup(element)).toContain('エラーが発生しました')
  })

  it('上限件数に達している場合は正確な総件数と誤認させない注記を表示する', async () => {
    const episodes = Array.from({ length: AWAITING_REVIEW_LIST_LIMIT }, (_, i) => episode({ id: i + 1 }))
    ;(fetchAwaitingReviewEpisodes as jest.Mock).mockResolvedValue(episodes)
    const element = await AdminAwaitingReviewEpisodesPage()
    const html = renderToStaticMarkup(element)
    expect(html).toContain('上限')
    expect(html).toContain(String(AWAITING_REVIEW_LIST_LIMIT))
  })
})
