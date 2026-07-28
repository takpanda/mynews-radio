/** @jest-environment node */

import { NextRequest } from 'next/server'
import * as generateRoute from '../api/generate/route'
import * as settingsRoute from '../api/settings/route'
import * as synthesizeRoute from '../api/episodes/[id]/synthesize/route'

function request(url: string, body = '{}') {
  return new NextRequest(url, {
    method: 'POST',
    headers: { cookie: 'admin_session=session-token', 'content-type': 'application/json' },
    body,
  })
}

const upstream = { status: 200, ok: true, body: null, text: () => Promise.resolve('{}') }

beforeEach(() => {
  global.fetch = jest.fn().mockResolvedValue(upstream)
})

describe('オーナー操作プロキシの認証情報転送', () => {
  it('生成はCookieを転送し共有API_KEYを付与しない', async () => {
    await generateRoute.POST(request('http://localhost/api/generate'))
    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('/generate'), expect.objectContaining({
      headers: { 'Content-Type': 'application/json', Cookie: 'admin_session=session-token' },
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
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', Cookie: 'admin_session=session-token' },
    }))
  })
})
