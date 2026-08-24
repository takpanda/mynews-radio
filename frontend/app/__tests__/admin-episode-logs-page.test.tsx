/** @jest-environment node */

jest.mock('next/headers', () => ({
  cookies: jest.fn(() => ({ get: jest.fn(() => ({ value: 'valid-token' })) })),
}))
jest.mock('next/navigation', () => ({
  redirect: jest.fn(() => { throw new Error('NEXT_REDIRECT') }),
  notFound: jest.fn(() => { throw new Error('NEXT_NOT_FOUND') }),
  useRouter: jest.fn(() => ({ push: jest.fn(), refresh: jest.fn() })),
}))
jest.mock('../lib/admin-episode-logs', () => ({
  ...jest.requireActual('../lib/admin-episode-logs'),
  fetchAdminEpisodeLogs: jest.fn(),
}))

import { notFound } from 'next/navigation'
import { renderToStaticMarkup } from 'react-dom/server'
import AdminEpisodeLogsPage from '../admin/episodes/[id]/logs/page'
import { fetchAdminEpisodeLogs } from '../lib/admin-episode-logs'
import type { AdminEpisodeLogs } from '../lib/admin-episode-logs'

const VALID_DATA: AdminEpisodeLogs = {
  episode: {
    id: 7, episode_date: '2026-08-14', seq: 1, status: 'completed', type: 'daily',
    created_at: '2026-08-14T10:00:00+00:00', updated_at: '2026-08-14T10:03:00+00:00',
  },
  generation_jobs: [],
  timeline: [],
  llm_calls: [],
  lines: [],
}

describe('AdminEpisodeLogsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    global.fetch = jest.fn().mockResolvedValue({ ok: true })
  })

  it('取得したログデータでシェルを描画する', async () => {
    ;(fetchAdminEpisodeLogs as jest.Mock).mockResolvedValue(VALID_DATA)
    const element = await AdminEpisodeLogsPage({ params: Promise.resolve({ id: '7' }) })
    expect(fetchAdminEpisodeLogs).toHaveBeenCalledWith(7)
    expect(renderToStaticMarkup(element)).toContain('エピソード概要')
  })

  it('エピソードが存在しない場合はnotFoundを呼ぶ', async () => {
    ;(fetchAdminEpisodeLogs as jest.Mock).mockResolvedValue(null)
    await expect(AdminEpisodeLogsPage({ params: Promise.resolve({ id: '999' }) })).rejects.toThrow('NEXT_NOT_FOUND')
    expect(notFound).toHaveBeenCalled()
  })

  it('IDが数値でない場合はnotFoundを呼ぶ', async () => {
    await expect(AdminEpisodeLogsPage({ params: Promise.resolve({ id: 'abc' }) })).rejects.toThrow('NEXT_NOT_FOUND')
    expect(fetchAdminEpisodeLogs).not.toHaveBeenCalled()
  })

  it('API取得に失敗した場合はエラーメッセージを表示する', async () => {
    ;(fetchAdminEpisodeLogs as jest.Mock).mockRejectedValue(new Error('boom'))
    const element = await AdminEpisodeLogsPage({ params: Promise.resolve({ id: '7' }) })
    expect(renderToStaticMarkup(element)).toContain('エラーが発生しました')
  })
})
