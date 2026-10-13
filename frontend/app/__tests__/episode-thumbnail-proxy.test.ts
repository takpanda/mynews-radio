/** @jest-environment node */

import { NextRequest } from 'next/server'
import * as thumbnailRoute from '../api/episodes/[id]/thumbnail/route'

function request(url: string, cookie = '') {
  return new NextRequest(url, { headers: cookie ? { cookie } : {} })
}

beforeEach(() => {
  global.fetch = jest.fn().mockResolvedValue(
    new Response(new Uint8Array([137, 80, 78, 71]), {
      status: 200,
      headers: { 'Content-Type': 'image/png' },
    }),
  )
})

describe('エピソードサムネイル中継', () => {
  it('admin_session のみ上流へ転送し、共有キャッシュを禁止する', async () => {
    const response = await thumbnailRoute.GET(
      request('http://localhost/api/episodes/12/thumbnail', 'tracking=t; admin_session=session-token; csrf=c'),
      { params: Promise.resolve({ id: '12' }) },
    )

    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/episodes/12/thumbnail'),
      expect.objectContaining({
        headers: { Cookie: 'admin_session=session-token' },
        cache: 'no-store',
      }),
    )
    expect(response.status).toBe(200)
    expect(response.headers.get('content-type')).toBe('image/png')
    expect(response.headers.get('cache-control')).toBe('private, no-store')
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(new Uint8Array([137, 80, 78, 71]))
  })

  it('管理セッションが無いときはCookieを転送しない', async () => {
    await thumbnailRoute.GET(
      request('http://localhost/api/episodes/12/thumbnail'),
      { params: Promise.resolve({ id: '12' }) },
    )

    const options = (global.fetch as jest.Mock).mock.calls[0][1]
    expect(options.headers).not.toHaveProperty('Cookie')
  })

  it('上流の404を維持し、404も共有キャッシュへ保存させない', async () => {
    global.fetch = jest.fn().mockResolvedValue(new Response(null, { status: 404 }))

    const response = await thumbnailRoute.GET(
      request('http://localhost/api/episodes/12/thumbnail'),
      { params: Promise.resolve({ id: '12' }) },
    )

    expect(response.status).toBe(404)
    expect(response.headers.get('cache-control')).toBe('private, no-store')
  })
})
