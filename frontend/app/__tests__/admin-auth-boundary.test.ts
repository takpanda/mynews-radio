/** @jest-environment node */

import { NextRequest } from 'next/server'

import * as dictionaryRoute from '../api/admin/dictionary/[[...slug]]/route'
import * as loginRoute from '../api/admin/login/route'
import * as logoutRoute from '../api/admin/logout/route'

function request(url: string, cookie?: string, init?: RequestInit) {
  const options: any = {
    ...init,
    headers: cookie ? { ...(init?.headers as Record<string, string>), cookie } : init?.headers,
  }
  return new NextRequest(url, options)
}

function upstream(status = 200, body = '{}') {
  return { status, ok: status >= 200 && status < 400, text: () => Promise.resolve(body), headers: new Headers() }
}

beforeEach(() => {
  global.fetch = jest.fn()
})

describe('辞書管理Route Handlerの認証境界', () => {
  it.each([
    ['GET', dictionaryRoute.GET],
    ['POST', dictionaryRoute.POST],
    ['PUT', dictionaryRoute.PUT],
    ['PATCH', dictionaryRoute.PATCH],
    ['DELETE', dictionaryRoute.DELETE],
  ])('%s はCookieなしでは401で上流へ到達しない', async (_method, handler) => {
    const response = await handler(request('http://localhost/api/admin/dictionary'))
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('有効Cookieは/admin/me検証後にCookieを上流へ転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, '{"items":[]}'))
    const response = await dictionaryRoute.GET(
      request('http://localhost/api/admin/dictionary', 'admin_session=valid-token'),
    )
    expect(response.status).toBe(200)
    expect(global.fetch).toHaveBeenNthCalledWith(
      1,
      expect.stringContaining('/admin/me'),
      expect.objectContaining({ headers: { Cookie: 'admin_session=valid-token' } }),
    )
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining('/admin/dictionary'),
      expect.objectContaining({ headers: expect.objectContaining({ Cookie: 'admin_session=valid-token' }) }),
    )
  })
})

describe('ログイン／ログアウトRoute Handler', () => {
  it('ログインのSet-Cookieを同一オリジンへ転送する', async () => {
    const upstreamResponse = upstream(200, '{"admin_user_id":1}')
    upstreamResponse.headers.set('set-cookie', 'admin_session=token; HttpOnly; Secure')
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(upstreamResponse)
    const response = await loginRoute.POST(
      request('http://localhost/api/admin/login', undefined, {
        method: 'POST',
        body: '{"username":"admin","password":"password"}',
      }),
    )
    expect(response.status).toBe(200)
    expect(response.headers.get('set-cookie')).toContain('admin_session=token')
  })

  it('ログアウト時にCookieを上流へ転送し削除Cookieを返す', async () => {
    const upstreamResponse = upstream(200, '{"status":"logged_out"}')
    upstreamResponse.headers.set('set-cookie', 'admin_session=""; Max-Age=0')
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(upstreamResponse)
    const response = await logoutRoute.POST(
      request('http://localhost/api/admin/logout', 'admin_session=token', { method: 'POST' }),
    )
    expect(response.status).toBe(200)
    expect(response.headers.get('set-cookie')).toContain('Max-Age=0')
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/admin/logout'),
      expect.objectContaining({ headers: { Cookie: 'admin_session=token' } }),
    )
  })
})
