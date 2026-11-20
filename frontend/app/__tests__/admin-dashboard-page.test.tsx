/** @jest-environment node */

jest.mock('next/headers', () => ({
  cookies: jest.fn(() => ({ get: jest.fn(() => undefined) })),
}))
jest.mock('next/navigation', () => ({
  redirect: jest.fn(() => { throw new Error('NEXT_REDIRECT') }),
  useRouter: jest.fn(),
}))
jest.mock('../lib/admin-dashboard', () => ({
  ...jest.requireActual('../lib/admin-dashboard'),
  fetchDashboardStats: jest.fn(),
}))

import { redirect } from 'next/navigation'
import { cookies } from 'next/headers'
import AdminDashboardPage from '../admin/dashboard/page'
import { fetchDashboardStats } from '../lib/admin-dashboard'

describe('/admin/dashboard SSR', () => {
  beforeEach(() => jest.clearAllMocks())

  it('未認証時はログインへリダイレクトし、集計を取得しない', async () => {
    await expect(AdminDashboardPage()).rejects.toThrow('NEXT_REDIRECT')
    expect(redirect).toHaveBeenCalledWith('/admin/login')
    expect(fetchDashboardStats).not.toHaveBeenCalled()
  })

  it('無効Cookieは/admin/meで検証されログインへリダイレクトする', async () => {
    ;(cookies as jest.Mock).mockReturnValue({ get: () => ({ value: 'invalid' }) })
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 401 })
    await expect(AdminDashboardPage()).rejects.toThrow('NEXT_REDIRECT')
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/admin/me'),
      expect.objectContaining({ headers: { Cookie: 'admin_session=invalid' } }),
    )
  })

  it('認証済みで集計APIが失敗してもエラー表示でページを返す（既定は7日）', async () => {
    ;(cookies as jest.Mock).mockReturnValue({ get: () => ({ value: 'valid' }) })
    global.fetch = jest.fn().mockResolvedValue({ ok: true, status: 200 })
    ;(fetchDashboardStats as jest.Mock).mockRejectedValue(new Error('500'))
    await expect(AdminDashboardPage()).resolves.toBeTruthy()
    expect(fetchDashboardStats).toHaveBeenCalledWith('7d')
  })
})
