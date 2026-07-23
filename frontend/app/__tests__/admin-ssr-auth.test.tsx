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
})
