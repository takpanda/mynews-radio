/** @jest-environment node */

import { NextRequest } from 'next/server'
import * as generateRoute from '../api/generate/route'
import * as settingsRoute from '../api/settings/route'
import * as synthesizeRoute from '../api/episodes/[id]/synthesize/route'

function request(url: string, body = '{}', cookie = 'admin_session=session-token') {
  return new NextRequest(url, {
    method: 'POST',
    headers: { ...(cookie ? { cookie } : {}), 'content-type': 'application/json' },
    body,
  })
}

const upstream = { status: 200, ok: true, body: null, text: () => Promise.resolve('{}') }

beforeEach(() => {
  global.fetch = jest.fn().mockResolvedValue(upstream)
})

describe('オーナー操作プロキシの認証情報転送', () => {
  it('生成は上流のRetry-Afterを転送する', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ...upstream,
      status: 429,
      ok: false,
      headers: new Headers({ 'Retry-After': '60' }),
    })

    const response = await generateRoute.POST(request('http://localhost/api/generate'))

    expect(response.headers.get('Retry-After')).toBe('60')
  })

  it('再合成は上流のRetry-Afterを転送する', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ...upstream,
      ok: false,
      status: 429,
      headers: new Headers({ 'Retry-After': '120' }),
      text: () => Promise.resolve('{"detail":"rate limited"}'),
    })

    const response = await synthesizeRoute.POST(
      request('http://localhost/api/episodes/1/synthesize'),
      { params: { id: '1' } },
    )

    expect(response.headers.get('Retry-After')).toBe('120')
  })

  it('生成はCookieを転送し共有API_KEYを付与しない', async () => {
    await generateRoute.POST(request('http://localhost/api/generate'))
    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('/generate'), expect.objectContaining({
      headers: expect.objectContaining({ 'Content-Type': 'application/json', Cookie: 'admin_session=session-token', 'Idempotency-Key': expect.any(String) }),
    }))
  })

  it('設定更新はCookieを転送し共有API_KEYを付与しない', async () => {
    await settingsRoute.PUT(request('http://localhost/api/settings'), '[]')
    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('/settings'), expect.objectContaining({
      headers: { 'Content-Type': 'application/json', Cookie: 'admin_session=session-token' },
    }))
  })

  it('再合成はCookieを転送し共有API_KEYを付与しない', async () => {
    await synthesizeRoute.POST(request('http://localhost/api/episodes/1/synthesize'), { params: { id: '1' } })
    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('/episodes/1/synthesize'), expect.objectContaining({
      headers: expect.objectContaining({ 'Content-Type': 'application/json', Accept: 'text/event-stream', Cookie: 'admin_session=session-token', 'Idempotency-Key': expect.any(String) }),
    }))
  })

  it.each([
    ['生成', '/generate'],
    ['再合成', '/episodes/1/synthesize'],
  ])('%sは保証されていないx-forwarded-forを上流へ転送しない', async (_name, path) => {
    const relayRequest = request(`http://localhost/api${path}`)
    relayRequest.headers.set('x-forwarded-for', '198.51.100.42, 10.0.0.1')
    if (path === '/generate') {
      await generateRoute.POST(relayRequest)
    } else {
      await synthesizeRoute.POST(relayRequest, { params: { id: '1' } })
    }
    const upstreamHeaders = (global.fetch as jest.Mock).mock.calls[0][1].headers
    expect(upstreamHeaders).not.toHaveProperty('X-Proxy-Client-IP')
    expect(upstreamHeaders).not.toHaveProperty('X-Proxy-Auth')
  })

  it.each([
    ['生成', '/generate'],
    ['再合成', '/episodes/1/synthesize'],
  ])('%sへ直接アクセスして任意のx-verified-client-ipを付けても署名を発行しない', async (_name, path) => {
    const directRequest = request(`http://localhost/api${path}`)
    directRequest.headers.set('x-verified-client-ip', '198.51.100.42')
    if (path === '/generate') {
      await generateRoute.POST(directRequest)
    } else {
      await synthesizeRoute.POST(directRequest, { params: { id: '1' } })
    }
    const upstreamHeaders = (global.fetch as jest.Mock).mock.calls[0][1].headers
    expect(upstreamHeaders).not.toHaveProperty('X-Verified-Client-IP')
    expect(upstreamHeaders).not.toHaveProperty('X-Verified-Client-IP-Timestamp')
    expect(upstreamHeaders).not.toHaveProperty('X-Verified-Client-IP-Signature')
  })

  it.each([
    ['生成', () => generateRoute.POST(request('http://localhost/api/generate', '{}', 'tracking=t; admin_session=session-token; csrf=c'))],
    ['設定', () => settingsRoute.PUT(request('http://localhost/api/settings', '{}', 'tracking=t; admin_session=session-token; csrf=c'), '{}')],
    ['再合成', () => synthesizeRoute.POST(request('http://localhost/api/episodes/1/synthesize', '{}', 'tracking=t; admin_session=session-token; csrf=c'), { params: { id: '1' } })],
  ])('%sはadmin_sessionだけを転送する', async (_name, invoke) => {
    await invoke()
    expect((global.fetch as jest.Mock).mock.calls[0][1].headers.Cookie).toBe('admin_session=session-token')
  })

  it.each([
    ['生成', () => generateRoute.POST(request('http://localhost/api/generate', '{}', 'tracking=t'))],
    ['設定', () => settingsRoute.PUT(request('http://localhost/api/settings', '{}', 'tracking=t'), '{}')],
    ['再合成', () => synthesizeRoute.POST(request('http://localhost/api/episodes/1/synthesize', '{}', 'tracking=t'), { params: { id: '1' } })],
  ])('%sはCookieなしで上流へCookieを送らない', async (_name, invoke) => {
    await invoke()
    expect((global.fetch as jest.Mock).mock.calls[0][1].headers).not.toHaveProperty('Cookie')
  })
})
