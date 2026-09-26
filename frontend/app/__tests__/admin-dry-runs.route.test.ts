/** @jest-environment node */

import { NextRequest } from 'next/server'
import { GET } from '../api/admin/dry-runs/[[...slug]]/route'
import { POST } from '../api/admin/programs/[id]/dry-run/route'

function request(url: string, init?: { cookie?: string; method?: string; body?: string; idempotencyKey?: string }) {
  const headers: Record<string, string> = {}
  if (init?.cookie) headers.cookie = init.cookie
  if (init?.idempotencyKey) headers['idempotency-key'] = init.idempotencyKey
  return new NextRequest(url, {
    method: init?.method,
    headers,
    ...(init?.body !== undefined ? { body: init.body } : {}),
  })
}

function upstream(status = 200, body = '{}', headers?: Record<string, string>) {
  return {
    status,
    ok: status >= 200 && status < 400,
    text: () => Promise.resolve(body),
    headers: { get: (name: string) => headers?.[name] ?? null },
  }
}

beforeEach(() => {
  global.fetch = jest.fn()
})

describe('/api/admin/dry-runs Route Handler', () => {
  it('GET: Cookieなしは401で上流へ到達しない', async () => {
    const response = await GET(request('http://localhost/api/admin/dry-runs'))
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('GET: 有効Cookieはstatusクエリ付きで一覧APIへ転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, '[]'))

    const response = await GET(
      request('http://localhost/api/admin/dry-runs?status=queued', { cookie: 'admin_session=valid-token' }),
    )

    expect(response.status).toBe(200)
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/admin/dry-runs?status=queued',
      expect.objectContaining({ method: 'GET', headers: expect.objectContaining({ Cookie: 'admin_session=valid-token' }) }),
    )
  })

  it('GET: サブパスはジョブIDへ転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, '{"id":5,"status":"completed"}'))

    const response = await GET(
      request('http://localhost/api/admin/dry-runs/5', { cookie: 'admin_session=valid-token' }),
    )

    expect(response.status).toBe(200)
    expect(global.fetch).toHaveBeenNthCalledWith(2, 'http://api:8010/admin/dry-runs/5', expect.objectContaining({ method: 'GET' }))
  })

  it('GET: 上流の404をそのまま透過する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(404, '{"detail":"Dry-run not found"}'))

    const response = await GET(request('http://localhost/api/admin/dry-runs/999', { cookie: 'admin_session=valid-token' }))
    expect(response.status).toBe(404)
  })
})

describe('/api/admin/programs/[id]/dry-run Route Handler', () => {
  it('POST: Cookieなしは401で上流へ到達しない', async () => {
    const response = await POST(request('http://localhost/api/admin/programs/p1/dry-run', { method: 'POST', body: '{}' }), {
      params: Promise.resolve({ id: 'p1' }),
    })
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('POST: Cookie・body・Idempotency-Keyを上流へ転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(202, '{"id":1,"status":"queued"}'))

    const response = await POST(
      request('http://localhost/api/admin/programs/p1/dry-run', {
        cookie: 'admin_session=valid-token',
        method: 'POST',
        body: '{"input_episode_id":1}',
        idempotencyKey: 'test-key-1',
      }),
      { params: Promise.resolve({ id: 'p1' }) },
    )

    expect(response.status).toBe(202)
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/admin/programs/p1/dry-run',
      expect.objectContaining({
        method: 'POST',
        body: '{"input_episode_id":1}',
        headers: expect.objectContaining({ Cookie: 'admin_session=valid-token', 'Idempotency-Key': 'test-key-1' }),
      }),
    )
  })

  it('POST: 429応答のRetry-Afterヘッダーを透過する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(429, '{"detail":"Generation queue is full"}', { 'Retry-After': '60' }))

    const response = await POST(
      request('http://localhost/api/admin/programs/p1/dry-run', {
        cookie: 'admin_session=valid-token',
        method: 'POST',
        body: '{}',
        idempotencyKey: 'test-key-2',
      }),
      { params: Promise.resolve({ id: 'p1' }) },
    )

    expect(response.status).toBe(429)
    expect(response.headers.get('Retry-After')).toBe('60')
  })

  it('POST: 上流の422をそのまま透過する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(422, '{"detail":"dry-run は radio 番組のみ対応します"}'))

    const response = await POST(
      request('http://localhost/api/admin/programs/p1/dry-run', {
        cookie: 'admin_session=valid-token',
        method: 'POST',
        body: '{}',
        idempotencyKey: 'test-key-3',
      }),
      { params: Promise.resolve({ id: 'p1' }) },
    )

    expect(response.status).toBe(422)
    const body = await response.json()
    expect(body.detail).toBe('dry-run は radio 番組のみ対応します')
  })
})
