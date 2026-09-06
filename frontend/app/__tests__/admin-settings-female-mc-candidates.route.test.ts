/** @jest-environment node */

import { NextRequest } from 'next/server'
import { GET, POST } from '../api/admin/settings/voices/female-mc-candidates/route'
import { PATCH } from '../api/admin/settings/voices/female-mc-candidates/[voice_name]/route'

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

const candidateBody = JSON.stringify({
  id: 1,
  voice_name: 'morigawa',
  display_name: 'もりかわ',
  sample_text: 'サンプル文',
  is_active: true,
  sample: { url: '/settings/voices/categories/samples/morigawa', text: 'サンプル文', media_type: 'audio/wav', available: true },
})

describe('/api/admin/settings/voices/female-mc-candidates Route Handler', () => {
  it('GET: Cookieなしは401で上流へ到達しない', async () => {
    const response = await GET(request('http://localhost/api/admin/settings/voices/female-mc-candidates'))
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('GET: 有効Cookieは/admin/me検証後にCookieを上流の候補マスタAPIへ転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, `[${candidateBody}]`))

    const response = await GET(
      request('http://localhost/api/admin/settings/voices/female-mc-candidates', { cookie: 'admin_session=valid-token' }),
    )

    expect(response.status).toBe(200)
    const body = await response.json()
    expect(body[0].voice_name).toBe('morigawa')
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/settings/voices/female-mc-candidates',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({ Cookie: 'admin_session=valid-token' }),
      }),
    )
  })

  it('POST: bodyとCookieを上流へ転送する', async () => {
    const payload = JSON.stringify({ voice_name: 'morigawa', display_name: 'もりかわ' })
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(201, candidateBody))

    const response = await POST(
      request('http://localhost/api/admin/settings/voices/female-mc-candidates', {
        cookie: 'admin_session=valid-token',
        method: 'POST',
        body: payload,
      }),
    )

    expect(response.status).toBe(201)
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/settings/voices/female-mc-candidates',
      expect.objectContaining({
        method: 'POST',
        body: payload,
        headers: expect.objectContaining({ Cookie: 'admin_session=valid-token' }),
      }),
    )
  })

  it('POST: 上流が409を返した場合はそのまま転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(409, '{"detail":"voice_name already exists"}'))

    const response = await POST(
      request('http://localhost/api/admin/settings/voices/female-mc-candidates', {
        cookie: 'admin_session=valid-token',
        method: 'POST',
        body: '{}',
      }),
    )

    expect(response.status).toBe(409)
  })

  it('POST: 上流への接続に失敗した場合は504を返す', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockRejectedValueOnce(new Error('network error'))

    const response = await POST(
      request('http://localhost/api/admin/settings/voices/female-mc-candidates', {
        cookie: 'admin_session=valid-token',
        method: 'POST',
        body: '{}',
      }),
    )
    expect(response.status).toBe(504)
  })
})

describe('/api/admin/settings/voices/female-mc-candidates/[voice_name] Route Handler', () => {
  function patchRequest(cookie?: string, body = '{}') {
    const headers: Record<string, string> = {}
    if (cookie) headers.cookie = cookie
    return new NextRequest('http://localhost/api/admin/settings/voices/female-mc-candidates/morigawa', {
      method: 'PATCH',
      headers,
      body,
    })
  }

  it('Cookieなしは401で上流へ到達しない', async () => {
    const response = await PATCH(patchRequest(), { params: Promise.resolve({ voice_name: 'morigawa' }) })
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('有効Cookieはbodyを上流へ転送する', async () => {
    const payload = JSON.stringify({ is_active: false })
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, candidateBody))

    const response = await PATCH(patchRequest('admin_session=valid-token', payload), {
      params: Promise.resolve({ voice_name: 'morigawa' }),
    })

    expect(response.status).toBe(200)
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/settings/voices/female-mc-candidates/morigawa',
      expect.objectContaining({
        method: 'PATCH',
        body: payload,
        headers: expect.objectContaining({ Cookie: 'admin_session=valid-token' }),
      }),
    )
  })

  it('上流が404を返した場合はそのまま転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(404, '{"detail":"Female MC candidate not found"}'))

    const response = await PATCH(patchRequest('admin_session=valid-token'), {
      params: Promise.resolve({ voice_name: 'unknown' }),
    })
    expect(response.status).toBe(404)
  })

  it('上流への接続に失敗した場合は504を返す', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockRejectedValueOnce(new Error('network error'))

    const response = await PATCH(patchRequest('admin_session=valid-token'), {
      params: Promise.resolve({ voice_name: 'morigawa' }),
    })
    expect(response.status).toBe(504)
  })
})
