/** @jest-environment node */

import { NextRequest } from 'next/server'
import { GET, POST, PUT } from '../api/admin/programs/[[...slug]]/route'
import { GET as MC_GET, POST as MC_POST, PUT as MC_PUT } from '../api/admin/mcs/[[...slug]]/route'

function request(url: string, init?: { cookie?: string; method?: string; body?: string }) {
  const headers: Record<string, string> = {}
  if (init?.cookie) headers.cookie = init.cookie
  return new NextRequest(url, {
    method: init?.method,
    headers,
    ...(init?.body !== undefined ? { body: init.body } : {}),
  })
}

function upstream(status = 200, body = '{}') {
  return { status, ok: status >= 200 && status < 400, text: () => Promise.resolve(body) }
}

beforeEach(() => {
  global.fetch = jest.fn()
})

describe('/api/admin/programs Route Handler', () => {
  it('GET: Cookieなしは401で上流へ到達しない', async () => {
    const response = await GET(request('http://localhost/api/admin/programs'))
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('GET: 有効Cookieは/admin/me検証後にクエリ付きで上流へ転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, '[]'))

    const response = await GET(
      request('http://localhost/api/admin/programs?include_inactive=true', { cookie: 'admin_session=valid-token' }),
    )

    expect(response.status).toBe(200)
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/admin/programs?include_inactive=true',
      expect.objectContaining({ method: 'GET', headers: expect.objectContaining({ Cookie: 'admin_session=valid-token' }) }),
    )
  })

  it('GET: サブパスは番組IDへ転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, '{"id":"radio_news_neighbor"}'))

    const response = await GET(
      request('http://localhost/api/admin/programs/radio_news_neighbor', { cookie: 'admin_session=valid-token' }),
    )

    expect(response.status).toBe(200)
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/admin/programs/radio_news_neighbor',
      expect.objectContaining({ method: 'GET' }),
    )
  })

  it('POST: bodyとCookieを上流へ転送する', async () => {
    const payload = JSON.stringify({ id: 'p1', name: 'test' })
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(201, '{"id":"p1"}'))

    const response = await POST(
      request('http://localhost/api/admin/programs', { cookie: 'admin_session=valid-token', method: 'POST', body: payload }),
    )

    expect(response.status).toBe(201)
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/admin/programs',
      expect.objectContaining({ method: 'POST', body: payload }),
    )
  })

  it('PUT: 上流の422をそのまま透過する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(422, '{"detail":"Unknown or inactive MC: x"}'))

    const response = await PUT(
      request('http://localhost/api/admin/programs/p1', {
        cookie: 'admin_session=valid-token',
        method: 'PUT',
        body: '{}',
      }),
    )

    expect(response.status).toBe(422)
    const body = await response.json()
    expect(body.detail).toBe('Unknown or inactive MC: x')
  })
})

describe('/api/admin/mcs Route Handler', () => {
  it('GET: Cookieなしは401で上流へ到達しない', async () => {
    const response = await MC_GET(request('http://localhost/api/admin/mcs'))
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('GET: 有効Cookieは上流のMC一覧APIへ転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, '[]'))

    const response = await MC_GET(request('http://localhost/api/admin/mcs', { cookie: 'admin_session=valid-token' }))

    expect(response.status).toBe(200)
    expect(global.fetch).toHaveBeenNthCalledWith(2, 'http://api:8010/admin/mcs', expect.objectContaining({ method: 'GET' }))
  })

  it('POST: 上流の409をそのまま透過する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(409, '{"detail":"MC id already exists"}'))

    const response = await MC_POST(
      request('http://localhost/api/admin/mcs', { cookie: 'admin_session=valid-token', method: 'POST', body: '{}' }),
    )

    expect(response.status).toBe(409)
  })

  it('PUT: bodyとCookieを上流へ転送する', async () => {
    const payload = JSON.stringify({ id: 'mc1', name: 'test' })
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, '{"id":"mc1"}'))

    const response = await MC_PUT(
      request('http://localhost/api/admin/mcs/mc1', { cookie: 'admin_session=valid-token', method: 'PUT', body: payload }),
    )

    expect(response.status).toBe(200)
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/admin/mcs/mc1',
      expect.objectContaining({ method: 'PUT', body: payload }),
    )
  })
})
