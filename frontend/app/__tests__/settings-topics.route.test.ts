/** @jest-environment node */

import { NextRequest } from 'next/server'
import { GET, POST } from '../api/settings/topics/route'
import { PUT, DELETE } from '../api/settings/topics/[id]/route'

const req = (method: string, body?: string, cookie = 'admin_session=tok; other=1') =>
  new NextRequest('http://localhost/api/settings/topics', { method, headers: { cookie }, ...(body !== undefined ? { body } : {}) })
const up = (status: number, body = '') => ({ status, text: () => Promise.resolve(body) })

beforeEach(() => { global.fetch = jest.fn() })

describe('/api/settings/topics proxy', () => {
  it('GET: admin_session のみ転送する', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(up(200, '{"topics":[]}'))
    const r = await GET(req('GET'))
    expect(r.status).toBe(200)
    const [url, init] = (global.fetch as jest.Mock).mock.calls[0]
    expect(url).toMatch(/\/settings\/topics$/)
    expect(init.headers.Cookie).toBe('admin_session=tok')
  })

  it('POST: ボディと409をそのまま返す', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(up(409, '{"detail":"dup"}'))
    const r = await POST(req('POST', '{"name":"a"}'))
    expect(r.status).toBe(409)
    expect((global.fetch as jest.Mock).mock.calls[0][1].body).toBe('{"name":"a"}')
  })

  it('PUT/DELETE: idをパスへ渡し、204は空ボディ', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(up(200, '{"id":3}')).mockResolvedValueOnce(up(204))
    await PUT(req('PUT', '{}'), { params: Promise.resolve({ id: '3' }) })
    const d = await DELETE(req('DELETE'), { params: Promise.resolve({ id: '3' }) })
    expect((global.fetch as jest.Mock).mock.calls[0][0]).toMatch(/\/settings\/topics\/3$/)
    expect(d.status).toBe(204)
  })

  it('idに / や ? を含んでもパス・クエリを変更できない', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(up(404, '{}'))
    await DELETE(req('DELETE'), { params: Promise.resolve({ id: '1/../x?y=1' }) })
    expect((global.fetch as jest.Mock).mock.calls[0][0]).toMatch(/\/settings\/topics\/1%2F\.\.%2Fx%3Fy%3D1$/)
  })

  it('Cookieがなければ転送しない', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(up(401, '{}'))
    const r = await GET(new NextRequest('http://localhost/api/settings/topics'))
    expect(r.status).toBe(401)
    expect((global.fetch as jest.Mock).mock.calls[0][1].headers.Cookie).toBeUndefined()
  })
})
