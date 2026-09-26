/** @jest-environment node */

import { NextRequest } from 'next/server'
import { GET } from '../api/admin/episodes/route'

function request(url: string, cookie?: string) {
  return new NextRequest(url, cookie ? { headers: { cookie } } : undefined)
}

function upstream(status = 200, body = '[]') {
  return { status, ok: status >= 200 && status < 400, text: () => Promise.resolve(body) }
}

beforeEach(() => {
  global.fetch = jest.fn()
})

describe('/api/admin/episodes Route Handler', () => {
  it('Cookieなしは401で上流へ到達しない', async () => {
    const response = await GET(request('http://localhost/api/admin/episodes?status=awaiting_review'))
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('Cookieがあっても/admin/meが401を返す失効セッションでは、業務APIを呼ばず401を返す', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(upstream(401, '{"detail":"Not authenticated"}'))

    const response = await GET(
      request('http://localhost/api/admin/episodes?status=awaiting_review', 'admin_session=expired-token'),
    )

    expect(response.status).toBe(401)
    expect(global.fetch).toHaveBeenCalledTimes(1)
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/admin/me'),
      expect.objectContaining({ headers: { Cookie: 'admin_session=expired-token' } }),
    )
  })

  it('有効Cookieはstatusクエリを維持したまま上流の一覧APIへ転送する', async () => {
    const body = JSON.stringify([{ id: 1, episode_date: '2026-09-20', seq: 1, status: 'awaiting_review' }])
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, body))

    const response = await GET(
      request('http://localhost/api/admin/episodes?status=awaiting_review', 'admin_session=valid-token'),
    )

    expect(response.status).toBe(200)
    expect(await response.json()).toEqual(JSON.parse(body))
    expect(global.fetch).toHaveBeenNthCalledWith(
      1,
      expect.stringContaining('/admin/me'),
      expect.objectContaining({ headers: { Cookie: 'admin_session=valid-token' } }),
    )
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/admin/episodes?status=awaiting_review',
      expect.objectContaining({ headers: expect.objectContaining({ Cookie: 'admin_session=valid-token' }) }),
    )
  })

  it('公開用エピソードAPI(/episodes)は呼び出さない', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, '[]'))

    await GET(request('http://localhost/api/admin/episodes?status=awaiting_review', 'admin_session=valid-token'))

    const calledUrls = (global.fetch as jest.Mock).mock.calls.map((call) => call[0])
    expect(calledUrls.some((url: string) => url === 'http://api:8010/episodes')).toBe(false)
  })

  it('上流への接続に失敗した場合は504を返す', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockRejectedValueOnce(new Error('network error'))

    const response = await GET(
      request('http://localhost/api/admin/episodes?status=awaiting_review', 'admin_session=valid-token'),
    )
    expect(response.status).toBe(504)
  })
})
