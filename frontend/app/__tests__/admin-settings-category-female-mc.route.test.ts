/** @jest-environment node */

import { NextRequest } from 'next/server'
import { GET, PUT } from '../api/admin/settings/voices/categories/route'
import { GET as GET_SAMPLE } from '../api/admin/settings/voices/categories/samples/[voice_name]/route'

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
  return {
    status,
    ok: status >= 200 && status < 400,
    text: () => Promise.resolve(body),
    headers: { get: () => null },
  }
}

function upstreamBinary(status: number, body: ArrayBuffer, headers: Record<string, string> = {}) {
  return {
    status,
    ok: status >= 200 && status < 400,
    arrayBuffer: () => Promise.resolve(body),
    text: () => Promise.resolve(''),
    headers: { get: (key: string) => headers[key.toLowerCase()] ?? null },
  }
}

beforeEach(() => {
  global.fetch = jest.fn()
})

const sampleResponseBody = JSON.stringify({
  categories: ['テック・IT', '経済・ビジネス'],
  category_female_voices: { 'テック・IT': 'morigawa', '経済・ビジネス': null },
  default_voice: 'morigawa',
  voices: [
    {
      display_name: 'morigawa',
      value: 'morigawa',
      sample: { url: '/settings/voices/categories/samples/morigawa', text: 'サンプル文', media_type: 'audio/wav', available: true },
    },
  ],
})

describe('/api/admin/settings/voices/categories Route Handler', () => {
  it('GET: Cookieなしは401で上流へ到達しない', async () => {
    const response = await GET(request('http://localhost/api/admin/settings/voices/categories'))
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('GET: 有効Cookieは/admin/me検証後にCookieを上流のカテゴリ設定APIへ転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, sampleResponseBody))

    const response = await GET(
      request('http://localhost/api/admin/settings/voices/categories', { cookie: 'admin_session=valid-token' }),
    )

    expect(response.status).toBe(200)
    const body = await response.json()
    expect(body.category_female_voices['テック・IT']).toBe('morigawa')
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/settings/voices/categories',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({ Cookie: 'admin_session=valid-token' }),
      }),
    )
  })

  it('PUT: bodyとCookieを上流へ転送する', async () => {
    const payload = JSON.stringify({ category_female_voices: { 'テック・IT': 'morigawa' } })
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, sampleResponseBody))

    const response = await PUT(
      request('http://localhost/api/admin/settings/voices/categories', {
        cookie: 'admin_session=valid-token',
        method: 'PUT',
        body: payload,
      }),
    )

    expect(response.status).toBe(200)
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/settings/voices/categories',
      expect.objectContaining({
        method: 'PUT',
        body: payload,
        headers: expect.objectContaining({ Cookie: 'admin_session=valid-token' }),
      }),
    )
  })

  it('PUT: 上流が422を返した場合はそのまま転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(422, '{"detail":"候補外の女性MCです"}'))

    const response = await PUT(
      request('http://localhost/api/admin/settings/voices/categories', {
        cookie: 'admin_session=valid-token',
        method: 'PUT',
        body: '{}',
      }),
    )

    expect(response.status).toBe(422)
    const body = await response.json()
    expect(body.detail).toBe('候補外の女性MCです')
  })

  it('PUT: 上流への接続に失敗した場合は504を返す', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockRejectedValueOnce(new Error('network error'))

    const response = await PUT(
      request('http://localhost/api/admin/settings/voices/categories', {
        cookie: 'admin_session=valid-token',
        method: 'PUT',
        body: '{}',
      }),
    )
    expect(response.status).toBe(504)
  })
})

describe('/api/admin/settings/voices/categories/samples/[voice_name] Route Handler', () => {
  function sampleRequest(cookie?: string) {
    const headers: Record<string, string> = {}
    if (cookie) headers.cookie = cookie
    return new NextRequest('http://localhost/api/admin/settings/voices/categories/samples/morigawa', { headers })
  }

  it('Cookieなしは401で上流へ到達しない', async () => {
    const response = await GET_SAMPLE(sampleRequest(), { params: Promise.resolve({ voice_name: 'morigawa' }) })
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('有効Cookieは音声バイナリをContent-Type付きで転送する', async () => {
    const audioBytes = new Uint8Array([1, 2, 3]).buffer
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(
        upstreamBinary(200, audioBytes, { 'content-type': 'audio/wav', 'cache-control': 'private, max-age=3600' }),
      )

    const response = await GET_SAMPLE(sampleRequest('admin_session=valid-token'), {
      params: Promise.resolve({ voice_name: 'morigawa' }),
    })

    expect(response.status).toBe(200)
    expect(response.headers.get('content-type')).toBe('audio/wav')
    expect(response.headers.get('cache-control')).toBe('private, max-age=3600')
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/settings/voices/categories/samples/morigawa',
      expect.objectContaining({ headers: expect.objectContaining({ Cookie: 'admin_session=valid-token' }) }),
    )
  })

  it('上流が404を返した場合はそのまま転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(404, '{"detail":"Voice sample not found"}'))

    const response = await GET_SAMPLE(sampleRequest('admin_session=valid-token'), {
      params: Promise.resolve({ voice_name: 'unknown' }),
    })
    expect(response.status).toBe(404)
  })

  it('上流への接続に失敗した場合は504を返す', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockRejectedValueOnce(new Error('network error'))

    const response = await GET_SAMPLE(sampleRequest('admin_session=valid-token'), {
      params: Promise.resolve({ voice_name: 'morigawa' }),
    })
    expect(response.status).toBe(504)
  })
})
