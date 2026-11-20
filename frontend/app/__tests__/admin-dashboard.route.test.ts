/** @jest-environment node */

import { NextRequest } from 'next/server'
import { GET } from '../api/admin/dashboard/stats/route'

function request(url: string, cookie?: string) {
  return new NextRequest(url, cookie ? { headers: { cookie } } : undefined)
}

function upstream(status = 200, body = '{}') {
  return { status, ok: status >= 200 && status < 400, text: () => Promise.resolve(body) }
}

beforeEach(() => {
  global.fetch = jest.fn()
})

describe('/api/admin/dashboard/stats Route Handler', () => {
  it('Cookieなしは401で上流へ到達しない', async () => {
    const response = await GET(request('http://localhost/api/admin/dashboard/stats?range=7d'))
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('失効セッションは業務APIを呼ばず401を返す', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(upstream(401, '{"detail":"Not authenticated"}'))
    const response = await GET(request('http://localhost/api/admin/dashboard/stats?range=7d', 'admin_session=expired'))
    expect(response.status).toBe(401)
    expect(global.fetch).toHaveBeenCalledTimes(1)
  })

  it('有効Cookieは range クエリを維持して集計APIへ転送する', async () => {
    const body = '{"range":"30d"}'
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, body))
    const response = await GET(request('http://localhost/api/admin/dashboard/stats?range=30d', 'admin_session=valid'))
    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({ range: '30d' })
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/admin/dashboard/stats?range=30d',
      expect.objectContaining({ headers: expect.objectContaining({ Cookie: 'admin_session=valid' }) }),
    )
  })

  it('上流のエラーステータス（422）をそのまま返す', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(422, '{"detail":"invalid"}'))
    const response = await GET(request('http://localhost/api/admin/dashboard/stats?range=1d', 'admin_session=valid'))
    expect(response.status).toBe(422)
  })

  it('上流への接続に失敗した場合は504を返す', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockRejectedValueOnce(new Error('network error'))
    const response = await GET(request('http://localhost/api/admin/dashboard/stats', 'admin_session=valid'))
    expect(response.status).toBe(504)
  })
})
