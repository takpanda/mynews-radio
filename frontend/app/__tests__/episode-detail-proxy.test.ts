/** @jest-environment node */

import { NextRequest } from 'next/server'
import * as episodeDetailRoute from '../api/episodes/[id]/route'

function request(url: string, cookie = '') {
  return new NextRequest(url, {
    headers: cookie ? { cookie } : {},
  })
}

const upstream = { status: 200, ok: true, body: null, text: () => Promise.resolve('{"id":1,"status":"completed"}') }

beforeEach(() => {
  global.fetch = jest.fn().mockResolvedValue(upstream)
})

describe('エピソード詳細プロキシの認証情報転送', () => {
  it('admin_sessionを持つ場合は上流へCookieとして転送する', async () => {
    await episodeDetailRoute.GET(request('http://localhost/api/episodes/1', 'admin_session=session-token'), {
      params: Promise.resolve({ id: '1' }),
    })

    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('/episodes/1'), expect.objectContaining({
      headers: { Cookie: 'admin_session=session-token' },
      cache: 'no-store',
    }))
  })

  it('admin_session以外のCookie（tracking, csrfなど）は転送しない', async () => {
    await episodeDetailRoute.GET(request('http://localhost/api/episodes/1', 'tracking=t; admin_session=session-token; csrf=c'), {
      params: Promise.resolve({ id: '1' }),
    })

    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('/episodes/1'), expect.objectContaining({
      headers: { Cookie: 'admin_session=session-token' },
    }))
  })

  it('Cookieがない場合は上流へCookieヘッダーを送らない', async () => {
    await episodeDetailRoute.GET(request('http://localhost/api/episodes/1'), {
      params: Promise.resolve({ id: '1' }),
    })

    const upstreamHeaders = (global.fetch as jest.Mock).mock.calls[0][1].headers
    expect(upstreamHeaders).not.toHaveProperty('Cookie')
  })

  it('公開/管理の取得条件の判定結果（上流のステータス・本文）をそのまま転送する', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ...upstream,
      status: 404,
      ok: false,
      text: () => Promise.resolve('{"detail":"Episode not found"}'),
    })

    const response = await episodeDetailRoute.GET(request('http://localhost/api/episodes/1'), {
      params: Promise.resolve({ id: '1' }),
    })

    expect(response.status).toBe(404)
    expect(await response.text()).toBe('{"detail":"Episode not found"}')
  })

  it('上流障害は504にし、内部情報を返さない', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('http://internal:8010 API_KEY=secret'))

    const response = await episodeDetailRoute.GET(request('http://localhost/api/episodes/1'), {
      params: Promise.resolve({ id: '1' }),
    })
    const body = await response.text()

    expect(response.status).toBe(504)
    expect(body).toBe(JSON.stringify({ error: 'upstream error' }))
    expect(body).not.toContain('internal:8010')
    expect(body).not.toContain('secret')
  })
})
