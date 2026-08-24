/** @jest-environment node */

import { NextRequest } from 'next/server'
import { GET } from '../api/admin/episodes/[id]/logs/route'

function request(url: string, cookie?: string) {
  return new NextRequest(url, cookie ? { headers: { cookie } } : undefined)
}

function upstream(status = 200, body = '{}') {
  return { status, ok: status >= 200 && status < 400, text: () => Promise.resolve(body) }
}

beforeEach(() => {
  global.fetch = jest.fn()
})

describe('/api/admin/episodes/[id]/logs Route Handler', () => {
  it('Cookieなしは401で上流へ到達しない', async () => {
    const response = await GET(request('http://localhost/api/admin/episodes/7/logs'), { params: Promise.resolve({ id: '7' }) })
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('有効Cookieは/admin/me検証後にCookieを上流のエピソードログAPIへ転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, '{"episode":{"id":7}}'))

    const response = await GET(
      request('http://localhost/api/admin/episodes/7/logs', 'admin_session=valid-token'),
      { params: Promise.resolve({ id: '7' }) },
    )

    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({ episode: { id: 7 } })
    expect(global.fetch).toHaveBeenNthCalledWith(
      1,
      expect.stringContaining('/admin/me'),
      expect.objectContaining({ headers: { Cookie: 'admin_session=valid-token' } }),
    )
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/admin/episodes/7/logs',
      expect.objectContaining({ headers: expect.objectContaining({ Cookie: 'admin_session=valid-token' }) }),
    )
  })

  it('phase_log_idクエリを上流URLへ転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, '{"lines":[]}'))

    await GET(
      request('http://localhost/api/admin/episodes/7/logs?phase_log_id=3', 'admin_session=valid-token'),
      { params: Promise.resolve({ id: '7' }) },
    )

    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/admin/episodes/7/logs?phase_log_id=3',
      expect.anything(),
    )
  })

  it('上流が404を返した場合はそのまま転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(404, '{"detail":"Episode not found"}'))

    const response = await GET(
      request('http://localhost/api/admin/episodes/999/logs', 'admin_session=valid-token'),
      { params: Promise.resolve({ id: '999' }) },
    )
    expect(response.status).toBe(404)
    expect(await response.json()).toEqual({ detail: 'Episode not found' })
  })

  it('上流への接続に失敗した場合は504を返す', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockRejectedValueOnce(new Error('network error'))

    const response = await GET(
      request('http://localhost/api/admin/episodes/7/logs', 'admin_session=valid-token'),
      { params: Promise.resolve({ id: '7' }) },
    )
    expect(response.status).toBe(504)
  })
})
