/** @jest-environment node */

import { NextRequest } from 'next/server'
import { GET as getCall } from '../api/admin/episodes/[id]/llm-calls/[callId]/route'
import { GET as getDownload } from '../api/admin/episodes/[id]/llm-calls/download/route'

function request(url: string, cookie?: string) {
  return new NextRequest(url, cookie ? { headers: { cookie } } : undefined)
}

function upstream(status = 200, body = '{}', headers: Record<string, string> = {}) {
  return {
    status,
    ok: status >= 200 && status < 400,
    text: () => Promise.resolve(body),
    arrayBuffer: () => Promise.resolve(new TextEncoder().encode(body).buffer),
    headers: { get: (name: string) => headers[name.toLowerCase()] ?? null },
  }
}

beforeEach(() => {
  global.fetch = jest.fn()
})

describe('/api/admin/episodes/[id]/llm-calls/[callId] Route Handler', () => {
  it('Cookieなしは401で上流へ到達しない', async () => {
    const response = await getCall(
      request('http://localhost/api/admin/episodes/7/llm-calls/call-1'),
      { params: Promise.resolve({ id: '7', callId: 'call-1' }) },
    )
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('有効Cookieは1件の本文を上流から取得しCookieを転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, '{"call_id":"call-1","prompt_text":"p"}'))

    const response = await getCall(
      request('http://localhost/api/admin/episodes/7/llm-calls/call-1', 'admin_session=valid-token'),
      { params: Promise.resolve({ id: '7', callId: 'call-1' }) },
    )

    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({ call_id: 'call-1', prompt_text: 'p' })
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/admin/episodes/7/llm-calls/call-1',
      expect.objectContaining({ headers: expect.objectContaining({ Cookie: 'admin_session=valid-token' }) }),
    )
  })

  it('上流が404を返した場合はそのまま転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(404, '{"detail":"LLM call not found"}'))

    const response = await getCall(
      request('http://localhost/api/admin/episodes/7/llm-calls/missing', 'admin_session=valid-token'),
      { params: Promise.resolve({ id: '7', callId: 'missing' }) },
    )
    expect(response.status).toBe(404)
  })

  it('上流への接続に失敗した場合は504を返す', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockRejectedValueOnce(new Error('network error'))

    const response = await getCall(
      request('http://localhost/api/admin/episodes/7/llm-calls/call-1', 'admin_session=valid-token'),
      { params: Promise.resolve({ id: '7', callId: 'call-1' }) },
    )
    expect(response.status).toBe(504)
  })
})

describe('/api/admin/episodes/[id]/llm-calls/download Route Handler', () => {
  it('Cookieなしは401で上流へ到達しない', async () => {
    const response = await getDownload(
      request('http://localhost/api/admin/episodes/7/llm-calls/download'),
      { params: Promise.resolve({ id: '7' }) },
    )
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('JSONLの本文とContent-Disposition/Content-Typeを転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(
        upstream(200, '{"call_id":"call-1"}\n', {
          'content-type': 'application/x-ndjson',
          'content-disposition': 'attachment; filename="episode-7-llm-calls.jsonl"',
        }),
      )

    const response = await getDownload(
      request('http://localhost/api/admin/episodes/7/llm-calls/download', 'admin_session=valid-token'),
      { params: Promise.resolve({ id: '7' }) },
    )

    expect(response.status).toBe(200)
    expect(response.headers.get('content-type')).toBe('application/x-ndjson')
    expect(response.headers.get('content-disposition')).toBe('attachment; filename="episode-7-llm-calls.jsonl"')
    expect(await response.text()).toBe('{"call_id":"call-1"}\n')
  })

  it('上流への接続に失敗した場合は504を返す', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockRejectedValueOnce(new Error('network error'))

    const response = await getDownload(
      request('http://localhost/api/admin/episodes/7/llm-calls/download', 'admin_session=valid-token'),
      { params: Promise.resolve({ id: '7' }) },
    )
    expect(response.status).toBe(504)
  })
})
