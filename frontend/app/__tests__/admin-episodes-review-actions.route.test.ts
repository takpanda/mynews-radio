/** @jest-environment node */

import { NextRequest } from 'next/server'
import { POST as POST_VALIDATE } from '../api/admin/episodes/[id]/validate/route'
import { POST as POST_APPROVE } from '../api/admin/episodes/[id]/approve/route'
import { POST as POST_REJECT } from '../api/admin/episodes/[id]/reject/route'
import { POST as POST_PREVIEW } from '../api/admin/episodes/[id]/lines/[idx]/preview-audio/route'

function request(url: string, init?: { cookie?: string; method?: string; body?: string }) {
  const headers: Record<string, string> = {}
  if (init?.cookie) headers.cookie = init.cookie
  return new NextRequest(url, {
    method: init?.method ?? 'POST',
    headers,
    ...(init?.body !== undefined ? { body: init.body } : {}),
  })
}

function jsonUpstream(status = 200, body = '{}') {
  return { status, ok: status >= 200 && status < 400, text: () => Promise.resolve(body) }
}

function meUpstream() {
  return jsonUpstream(200, '{"admin_user_id":1}')
}

beforeEach(() => {
  global.fetch = jest.fn()
})

describe('/api/admin/episodes/[id]/validate Route Handler', () => {
  it('Cookieなしは401で上流へ到達しない', async () => {
    const response = await POST_VALIDATE(request('http://localhost/api/admin/episodes/7/validate'), {
      params: Promise.resolve({ id: '7' }),
    })
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('有効Cookieは上流の検査APIへ転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(meUpstream())
      .mockResolvedValueOnce(jsonUpstream(200, '{"revision":3,"can_approve":true,"results":[]}'))

    const response = await POST_VALIDATE(
      request('http://localhost/api/admin/episodes/7/validate', { cookie: 'admin_session=valid-token' }),
      { params: Promise.resolve({ id: '7' }) },
    )

    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({ revision: 3, can_approve: true, results: [] })
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/admin/episodes/7/validate',
      expect.objectContaining({ method: 'POST', headers: expect.objectContaining({ Cookie: 'admin_session=valid-token' }) }),
    )
  })
})

describe('/api/admin/episodes/[id]/approve Route Handler', () => {
  it('Cookieなしは401で上流へ到達しない', async () => {
    const response = await POST_APPROVE(request('http://localhost/api/admin/episodes/7/approve'), {
      params: Promise.resolve({ id: '7' }),
    })
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('検査errorが残っている場合の409をそのまま転送する', async () => {
    const conflict = JSON.stringify({ detail: { message: 'Script has validation errors', can_approve: false, results: [] } })
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(meUpstream()).mockResolvedValueOnce(jsonUpstream(409, conflict))

    const response = await POST_APPROVE(
      request('http://localhost/api/admin/episodes/7/approve', { cookie: 'admin_session=valid-token' }),
      { params: Promise.resolve({ id: '7' }) },
    )

    expect(response.status).toBe(409)
    expect((await response.json()).detail.can_approve).toBe(false)
  })
})

describe('/api/admin/episodes/[id]/reject Route Handler', () => {
  it('Cookieなしは401で上流へ到達しない', async () => {
    const response = await POST_REJECT(
      request('http://localhost/api/admin/episodes/7/reject', { body: JSON.stringify({ action: 'discard' }) }),
      { params: Promise.resolve({ id: '7' }) },
    )
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('actionを含むbodyを上流へ転送する', async () => {
    const payload = JSON.stringify({ action: 'discard' })
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(meUpstream())
      .mockResolvedValueOnce(jsonUpstream(200, '{"episode_id":7,"status":"discarded"}'))

    const response = await POST_REJECT(
      request('http://localhost/api/admin/episodes/7/reject', { cookie: 'admin_session=valid-token', body: payload }),
      { params: Promise.resolve({ id: '7' }) },
    )

    expect(response.status).toBe(200)
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/admin/episodes/7/reject',
      expect.objectContaining({ method: 'POST', body: payload }),
    )
  })
})

describe('/api/admin/episodes/[id]/lines/[idx]/preview-audio Route Handler', () => {
  function request2(url: string, cookie?: string) {
    return new NextRequest(url, { method: 'POST', headers: cookie ? { cookie } : {} })
  }

  it('Cookieなしは401で上流へ到達しない', async () => {
    const response = await POST_PREVIEW(request2('http://localhost/api/admin/episodes/7/lines/0/preview-audio'), {
      params: Promise.resolve({ id: '7', idx: '0' }),
    })
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('成功時はWAV本体とContent-Typeをそのまま転送する', async () => {
    const wavBytes = new Uint8Array([1, 2, 3, 4]).buffer
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(meUpstream()).mockResolvedValueOnce({
      status: 200,
      ok: true,
      arrayBuffer: () => Promise.resolve(wavBytes),
      headers: new Headers({ 'content-type': 'audio/wav' }),
    })

    const response = await POST_PREVIEW(
      request2('http://localhost/api/admin/episodes/7/lines/0/preview-audio', 'admin_session=valid-token'),
      { params: Promise.resolve({ id: '7', idx: '0' }) },
    )

    expect(response.status).toBe(200)
    expect(response.headers.get('content-type')).toBe('audio/wav')
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(new Uint8Array(wavBytes))
  })

  it('上流の429（レート制限）をそのまま転送する', async () => {
    const errorBody = Buffer.from(JSON.stringify({ detail: 'Preview audio rate limit exceeded' }))
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(meUpstream()).mockResolvedValueOnce({
      status: 429,
      ok: false,
      arrayBuffer: () => Promise.resolve(errorBody.buffer.slice(errorBody.byteOffset, errorBody.byteOffset + errorBody.byteLength)),
      headers: new Headers({ 'content-type': 'application/json' }),
    })

    const response = await POST_PREVIEW(
      request2('http://localhost/api/admin/episodes/7/lines/0/preview-audio', 'admin_session=valid-token'),
      { params: Promise.resolve({ id: '7', idx: '0' }) },
    )

    expect(response.status).toBe(429)
    expect(await response.json()).toEqual({ detail: 'Preview audio rate limit exceeded' })
  })

  it('上流の502（合成失敗）をそのまま転送する', async () => {
    const errorBody = Buffer.from(JSON.stringify({ detail: 'Preview audio synthesis failed' }))
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(meUpstream()).mockResolvedValueOnce({
      status: 502,
      ok: false,
      arrayBuffer: () => Promise.resolve(errorBody.buffer.slice(errorBody.byteOffset, errorBody.byteOffset + errorBody.byteLength)),
      headers: new Headers({ 'content-type': 'application/json' }),
    })

    const response = await POST_PREVIEW(
      request2('http://localhost/api/admin/episodes/7/lines/0/preview-audio', 'admin_session=valid-token'),
      { params: Promise.resolve({ id: '7', idx: '0' }) },
    )

    expect(response.status).toBe(502)
    expect(await response.json()).toEqual({ detail: 'Preview audio synthesis failed' })
  })

  it('上流への接続に失敗した場合は504を返す', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(meUpstream()).mockRejectedValueOnce(new Error('network error'))

    const response = await POST_PREVIEW(
      request2('http://localhost/api/admin/episodes/7/lines/0/preview-audio', 'admin_session=valid-token'),
      { params: Promise.resolve({ id: '7', idx: '0' }) },
    )
    expect(response.status).toBe(504)
  })
})
