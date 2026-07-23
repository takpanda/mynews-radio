/** @jest-environment node */

jest.mock('next/headers', () => ({
  cookies: jest.fn(() => ({ get: jest.fn(() => undefined) })),
}))
jest.mock('next/navigation', () => ({
  redirect: jest.fn(() => { throw new Error('NEXT_REDIRECT') }),
}))
jest.mock('../lib/admin-dictionary', () => ({ fetchDictionaryEntries: jest.fn() }))
jest.mock('../lib/admin-misreading-reports', () => ({ fetchAdminMisreadingReports: jest.fn() }))

import { redirect } from 'next/navigation'
import { cookies } from 'next/headers'
import AdminDictionaryPage from '../admin/dictionary/page'
import AdminMisreadingReportsPage from '../admin/misreading-reports/page'

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
})
