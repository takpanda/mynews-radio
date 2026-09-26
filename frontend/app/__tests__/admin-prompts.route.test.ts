/** @jest-environment node */

import { NextRequest } from 'next/server'
import { GET, POST } from '../api/admin/prompts/[[...slug]]/route'

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

describe('/api/admin/prompts Route Handler', () => {
  it('GET: Cookieなしは401で上流へ到達しない', async () => {
    const response = await GET(request('http://localhost/api/admin/prompts'))
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('GET: 有効Cookieは/admin/me検証後に一覧APIへ転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, '[]'))

    const response = await GET(
      request('http://localhost/api/admin/prompts', { cookie: 'admin_session=valid-token' }),
    )

    expect(response.status).toBe(200)
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/admin/prompts',
      expect.objectContaining({ method: 'GET', headers: expect.objectContaining({ Cookie: 'admin_session=valid-token' }) }),
    )
  })

  it('GET: program_idクエリを上流へ転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, '[]'))

    await GET(
      request('http://localhost/api/admin/prompts?program_id=radio-test', { cookie: 'admin_session=valid-token' }),
    )

    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/admin/prompts?program_id=radio-test',
      expect.objectContaining({ method: 'GET' }),
    )
  })

  it('GET: サブパスは版一覧APIへ転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, '{"versions":[]}'))

    const response = await GET(
      request('http://localhost/api/admin/prompts/1/versions', { cookie: 'admin_session=valid-token' }),
    )

    expect(response.status).toBe(200)
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/admin/prompts/1/versions',
      expect.objectContaining({ method: 'GET' }),
    )
  })

  it('POST: bodyとCookieを上流へ転送する', async () => {
    const payload = JSON.stringify({ template_key: 'category', program_id: 'radio-test' })
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(201, '{"id":1}'))

    const response = await POST(
      request('http://localhost/api/admin/prompts', { cookie: 'admin_session=valid-token', method: 'POST', body: payload }),
    )

    expect(response.status).toBe(201)
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/admin/prompts',
      expect.objectContaining({ method: 'POST', body: payload }),
    )
  })

  it('POST: サブパスへの版作成で上流の422をそのまま透過する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(422, '{"detail":"Missing required variables: source"}'))

    const response = await POST(
      request('http://localhost/api/admin/prompts/1/versions', {
        cookie: 'admin_session=valid-token',
        method: 'POST',
        body: '{"content":"x"}',
      }),
    )

    expect(response.status).toBe(422)
    const body = await response.json()
    expect(body.detail).toBe('Missing required variables: source')
  })
})
