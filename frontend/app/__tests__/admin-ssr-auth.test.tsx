/** @jest-environment node */

jest.mock('next/headers', () => ({
  cookies: jest.fn(() => ({ get: jest.fn(() => undefined) })),
}))
jest.mock('next/navigation', () => ({
  redirect: jest.fn(() => { throw new Error('NEXT_REDIRECT') }),
}))
jest.mock('../lib/admin-dictionary', () => ({ fetchDictionaryEntries: jest.fn() }))
jest.mock('../lib/admin-misreading-reports', () => ({ fetchAdminMisreadingReports: jest.fn() }))
jest.mock('../lib/admin-episode-logs', () => ({ fetchAdminEpisodeLogs: jest.fn() }))
jest.mock('../lib/admin-voice-settings', () => ({
  fetchVoiceSettings: jest.fn(),
  fetchVoiceOptions: jest.fn(),
}))
jest.mock('../lib/admin-episodes', () => ({
  ...jest.requireActual('../lib/admin-episodes'),
  fetchAwaitingReviewEpisodes: jest.fn(),
}))
jest.mock('../lib/admin-programs', () => ({
  fetchPrograms: jest.fn(),
  fetchProgram: jest.fn(),
  fetchMcs: jest.fn(),
}))

import { redirect } from 'next/navigation'
import { cookies } from 'next/headers'
import AdminDictionaryPage from '../admin/dictionary/page'
import AdminMisreadingReportsPage from '../admin/misreading-reports/page'
import AdminEpisodeLogsPage from '../admin/episodes/[id]/logs/page'
import AdminVoiceSettingsPage from '../admin/settings/voice/page'
import AdminAwaitingReviewEpisodesPage from '../admin/episodes/page'
import AdminProgramsPage from '../admin/programs/page'
import AdminNewProgramPage from '../admin/programs/new/page'
import AdminEditProgramPage from '../admin/programs/[id]/page'
import AdminMcsPage from '../admin/mcs/page'
import { fetchAwaitingReviewEpisodes } from '../lib/admin-episodes'
import { fetchPrograms, fetchProgram, fetchMcs } from '../lib/admin-programs'

describe('管理画面SSRの認証境界', () => {
  beforeEach(() => jest.clearAllMocks())

  it('辞書管理ページは未認証時にログインへリダイレクトする', async () => {
    await expect(AdminDictionaryPage()).rejects.toThrow('NEXT_REDIRECT')
    expect(redirect).toHaveBeenCalledWith('/admin/login')
  })

  it('読み間違い報告ページは未認証時にログインへリダイレクトする', async () => {
    await expect(AdminMisreadingReportsPage()).rejects.toThrow('NEXT_REDIRECT')
    expect(redirect).toHaveBeenCalledWith('/admin/login')
  })

  it('辞書管理ページは無効Cookieを/admin/meで検証しログインへリダイレクトする', async () => {
    ;(cookies as jest.Mock).mockReturnValue({ get: () => ({ value: 'invalid-token' }) })
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 401 })
    await expect(AdminDictionaryPage()).rejects.toThrow('NEXT_REDIRECT')
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/admin/me'),
      expect.objectContaining({ headers: { Cookie: 'admin_session=invalid-token' } }),
    )
    expect(redirect).toHaveBeenCalledWith('/admin/login')
  })

  it('読み間違い報告ページも無効Cookieを検証してリダイレクトする', async () => {
    ;(cookies as jest.Mock).mockReturnValue({ get: () => ({ value: 'expired-token' }) })
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 401 })
    await expect(AdminMisreadingReportsPage()).rejects.toThrow('NEXT_REDIRECT')
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/admin/me'),
      expect.objectContaining({ headers: { Cookie: 'admin_session=expired-token' } }),
    )
    expect(redirect).toHaveBeenCalledWith('/admin/login')
  })

  it('エピソード詳細ログページはCookieなしでログインへリダイレクトし、ログ取得を行わない', async () => {
    const { fetchAdminEpisodeLogs } = jest.requireMock('../lib/admin-episode-logs')
    await expect(AdminEpisodeLogsPage({ params: Promise.resolve({ id: '1' }) })).rejects.toThrow('NEXT_REDIRECT')
    expect(redirect).toHaveBeenCalledWith('/admin/login')
    expect(fetchAdminEpisodeLogs).not.toHaveBeenCalled()
  })

  it('エピソード詳細ログページは無効Cookieを検証してリダイレクトする', async () => {
    const { fetchAdminEpisodeLogs } = jest.requireMock('../lib/admin-episode-logs')
    ;(cookies as jest.Mock).mockReturnValue({ get: () => ({ value: 'invalid-token' }) })
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 401 })
    await expect(AdminEpisodeLogsPage({ params: Promise.resolve({ id: '1' }) })).rejects.toThrow('NEXT_REDIRECT')
    expect(redirect).toHaveBeenCalledWith('/admin/login')
    expect(fetchAdminEpisodeLogs).not.toHaveBeenCalled()
  })

  it('ボイス設定ページはCookieなしでログインへリダイレクトし、設定取得を行わない', async () => {
    const { fetchVoiceSettings } = jest.requireMock('../lib/admin-voice-settings')
    await expect(AdminVoiceSettingsPage()).rejects.toThrow('NEXT_REDIRECT')
    expect(redirect).toHaveBeenCalledWith('/admin/login')
    expect(fetchVoiceSettings).not.toHaveBeenCalled()
  })

  it('ボイス設定ページは無効Cookieを/admin/meで検証しログインへリダイレクトする', async () => {
    ;(cookies as jest.Mock).mockReturnValue({ get: () => ({ value: 'invalid-token' }) })
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 401 })
    await expect(AdminVoiceSettingsPage()).rejects.toThrow('NEXT_REDIRECT')
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/admin/me'),
      expect.objectContaining({ headers: { Cookie: 'admin_session=invalid-token' } }),
    )
    expect(redirect).toHaveBeenCalledWith('/admin/login')
  })

  it('確認待ち一覧ページはCookieなしでログインへリダイレクトし、一覧取得を行わない', async () => {
    await expect(AdminAwaitingReviewEpisodesPage()).rejects.toThrow('NEXT_REDIRECT')
    expect(redirect).toHaveBeenCalledWith('/admin/login')
    expect(fetchAwaitingReviewEpisodes).not.toHaveBeenCalled()
  })

  it('番組管理ページはCookieなしでログインへリダイレクトし、一覧取得を行わない', async () => {
    await expect(AdminProgramsPage()).rejects.toThrow('NEXT_REDIRECT')
    expect(redirect).toHaveBeenCalledWith('/admin/login')
    expect(fetchPrograms).not.toHaveBeenCalled()
  })

  it('番組新規作成ページはCookieなしでログインへリダイレクトし、MC取得を行わない', async () => {
    await expect(AdminNewProgramPage()).rejects.toThrow('NEXT_REDIRECT')
    expect(redirect).toHaveBeenCalledWith('/admin/login')
    expect(fetchMcs).not.toHaveBeenCalled()
  })

  it('番組編集ページはCookieなしでログインへリダイレクトし、番組取得を行わない', async () => {
    await expect(AdminEditProgramPage({ params: Promise.resolve({ id: 'p1' }) })).rejects.toThrow('NEXT_REDIRECT')
    expect(redirect).toHaveBeenCalledWith('/admin/login')
    expect(fetchProgram).not.toHaveBeenCalled()
  })

  it('MC管理ページはCookieなしでログインへリダイレクトし、一覧取得を行わない', async () => {
    await expect(AdminMcsPage()).rejects.toThrow('NEXT_REDIRECT')
    expect(redirect).toHaveBeenCalledWith('/admin/login')
    expect(fetchMcs).not.toHaveBeenCalled()
  })

  it('番組管理ページは無効Cookieを/admin/meで検証しログインへリダイレクトする', async () => {
    ;(cookies as jest.Mock).mockReturnValue({ get: () => ({ value: 'invalid-token' }) })
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 401 })
    await expect(AdminProgramsPage()).rejects.toThrow('NEXT_REDIRECT')
    expect(redirect).toHaveBeenCalledWith('/admin/login')
  })

  it('確認待ち一覧ページは無効Cookieを/admin/meで検証しログインへリダイレクトする', async () => {
    ;(cookies as jest.Mock).mockReturnValue({ get: () => ({ value: 'invalid-token' }) })
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 401 })
    await expect(AdminAwaitingReviewEpisodesPage()).rejects.toThrow('NEXT_REDIRECT')
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/admin/me'),
      expect.objectContaining({ headers: { Cookie: 'admin_session=invalid-token' } }),
    )
    expect(redirect).toHaveBeenCalledWith('/admin/login')
  })
})
