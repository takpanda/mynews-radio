/** @jest-environment node */

jest.mock('next/headers', () => ({
  cookies: jest.fn(),
}))

import { cookies } from 'next/headers'
import { hasValidAdminSession } from '../admin/auth'

describe('公開ページのオーナーUI用セッション検証', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    global.fetch = jest.fn()
  })

  it('Cookieがない場合はバックエンドを呼ばず未認証とする', async () => {
    ;(cookies as jest.Mock).mockReturnValue({ get: () => undefined })
    await expect(hasValidAdminSession()).resolves.toBe(false)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('期限切れ・不正Cookieは/admin/meの401で未認証とする', async () => {
    ;(cookies as jest.Mock).mockReturnValue({ get: () => ({ value: 'invalid-token' }) })
    ;(global.fetch as jest.Mock).mockResolvedValue({ ok: false, status: 401 })
    await expect(hasValidAdminSession()).resolves.toBe(false)
    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('/admin/me'), expect.objectContaining({
      headers: { Cookie: 'admin_session=invalid-token' },
    }))
  })

  it('有効Cookieは/admin/meの成功時だけ認証済みとする', async () => {
    ;(cookies as jest.Mock).mockReturnValue({ get: () => ({ value: 'valid-token' }) })
    ;(global.fetch as jest.Mock).mockResolvedValue({ ok: true, status: 200 })
    await expect(hasValidAdminSession()).resolves.toBe(true)
  })
})
