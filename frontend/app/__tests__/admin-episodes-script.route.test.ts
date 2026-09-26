/** @jest-environment node */

import { NextRequest } from 'next/server'
import { GET, PUT } from '../api/admin/episodes/[id]/script/route'
import { GET as GET_REVISIONS } from '../api/admin/episodes/[id]/script/revisions/route'

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

describe('/api/admin/episodes/[id]/script Route Handler', () => {
  it('GET: Cookieなしは401で上流へ到達しない', async () => {
    const response = await GET(request('http://localhost/api/admin/episodes/7/script'), {
      params: Promise.resolve({ id: '7' }),
    })
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('GET: 有効Cookieは上流の台本取得APIへ転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, '{"episode_id":7,"revision":3,"script":{"lines":[]}}'))

    const response = await GET(
      request('http://localhost/api/admin/episodes/7/script', { cookie: 'admin_session=valid-token' }),
      { params: Promise.resolve({ id: '7' }) },
    )

    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({ episode_id: 7, revision: 3, script: { lines: [] } })
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/admin/episodes/7/script',
      expect.objectContaining({ headers: expect.objectContaining({ Cookie: 'admin_session=valid-token' }) }),
    )
  })

  it('PUT: bodyとCookieを上流へ転送する', async () => {
    const payload = JSON.stringify({ revision: 3, script: { lines: [] } })
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, payload))

    const response = await PUT(
      request('http://localhost/api/admin/episodes/7/script', {
        cookie: 'admin_session=valid-token',
        method: 'PUT',
        body: payload,
      }),
      { params: Promise.resolve({ id: '7' }) },
    )

    expect(response.status).toBe(200)
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/admin/episodes/7/script',
      expect.objectContaining({
        method: 'PUT',
        body: payload,
        headers: expect.objectContaining({ Cookie: 'admin_session=valid-token' }),
      }),
    )
  })

  it('PUT: 上流の409（revision競合）はlatest_revisionを含めてそのまま転送する', async () => {
    const conflict = JSON.stringify({ detail: { message: 'Script revision conflict', latest_revision: 5 } })
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(409, conflict))

    const response = await PUT(
      request('http://localhost/api/admin/episodes/7/script', {
        cookie: 'admin_session=valid-token',
        method: 'PUT',
        body: JSON.stringify({ revision: 3, script: { lines: [] } }),
      }),
      { params: Promise.resolve({ id: '7' }) },
    )

    expect(response.status).toBe(409)
    expect((await response.json()).detail.latest_revision).toBe(5)
  })

  it('PUT: 上流への接続に失敗した場合は504を返す', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockRejectedValueOnce(new Error('network error'))

    const response = await PUT(
      request('http://localhost/api/admin/episodes/7/script', {
        cookie: 'admin_session=valid-token',
        method: 'PUT',
        body: '{}',
      }),
      { params: Promise.resolve({ id: '7' }) },
    )
    expect(response.status).toBe(504)
  })
})

describe('/api/admin/episodes/[id]/script/revisions Route Handler', () => {
  it('Cookieなしは401で上流へ到達しない', async () => {
    const response = await GET_REVISIONS(request('http://localhost/api/admin/episodes/7/script/revisions'), {
      params: Promise.resolve({ id: '7' }),
    })
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('有効Cookieは上流の版一覧APIへ転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, '[{"revision":2},{"revision":1}]'))

    const response = await GET_REVISIONS(
      request('http://localhost/api/admin/episodes/7/script/revisions', { cookie: 'admin_session=valid-token' }),
      { params: Promise.resolve({ id: '7' }) },
    )

    expect(response.status).toBe(200)
    expect(await response.json()).toEqual([{ revision: 2 }, { revision: 1 }])
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/admin/episodes/7/script/revisions',
      expect.anything(),
    )
  })
})
