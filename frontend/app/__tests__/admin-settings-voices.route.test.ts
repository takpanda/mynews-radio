/** @jest-environment node */

import { NextRequest } from 'next/server'
import { GET, PUT } from '../api/admin/settings/voices/route'
import { GET as GET_OPTIONS } from '../api/admin/settings/voices/options/route'

function request(url: string, init?: { cookie?: string; method?: string; body?: string }) {
  const headers: Record<string, string> = {}
  if (init?.cookie) headers.cookie = init.cookie
  return new NextRequest(url, {
    method: init?.method,
    headers,
    ...(init?.body !== undefined ? { body: init.body } : {}),
  })
}

function upstream(status = 200, body = '{}') {
  return { status, ok: status >= 200 && status < 400, text: () => Promise.resolve(body) }
}

beforeEach(() => {
  global.fetch = jest.fn()
})

describe('/api/admin/settings/voices Route Handler', () => {
  it('GET: Cookieなしは401で上流へ到達しない', async () => {
    const response = await GET(request('http://localhost/api/admin/settings/voices'))
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('GET: 有効Cookieは/admin/me検証後にCookieを上流のボイス設定APIへ転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(
        upstream(
          200,
          JSON.stringify({
            aivispeech_speaker_male: 1310138976,
            aivispeech_speaker_female: 1388823424,
            voicevox_speaker_male: 11,
            voicevox_speaker_female: 2,
            fishs2pro_voice_male: 'male',
            fishs2pro_voice_female: 'morigawa',
          }),
        ),
      )

    const response = await GET(
      request('http://localhost/api/admin/settings/voices', { cookie: 'admin_session=valid-token' }),
    )

    expect(response.status).toBe(200)
    const body = await response.json()
    expect(body.aivispeech_speaker_male).toBe(1310138976)
    expect(global.fetch).toHaveBeenNthCalledWith(
      1,
      expect.stringContaining('/admin/me'),
      expect.objectContaining({ headers: { Cookie: 'admin_session=valid-token' } }),
    )
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/settings/voices',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({ Cookie: 'admin_session=valid-token' }),
      }),
    )
  })

  it('PUT: bodyとCookieを上流へ転送する', async () => {
    const payload = JSON.stringify({
      aivispeech_speaker_male: 1310138976,
      aivispeech_speaker_female: 1388823424,
      voicevox_speaker_male: 11,
      voicevox_speaker_female: 2,
      fishs2pro_voice_male: 'male',
      fishs2pro_voice_female: 'morigawa',
    })
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, payload))

    const response = await PUT(
      request('http://localhost/api/admin/settings/voices', {
        cookie: 'admin_session=valid-token',
        method: 'PUT',
        body: payload,
      }),
    )

    expect(response.status).toBe(200)
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/settings/voices',
      expect.objectContaining({
        method: 'PUT',
        body: payload,
        headers: expect.objectContaining({ Cookie: 'admin_session=valid-token' }),
      }),
    )
  })

  it('PUT: 上流が422を返した場合はそのまま転送する', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(422, '{"detail":"must be an integer speaker id"}'))

    const response = await PUT(
      request('http://localhost/api/admin/settings/voices', {
        cookie: 'admin_session=valid-token',
        method: 'PUT',
        body: '{}',
      }),
    )

    expect(response.status).toBe(422)
    const body = await response.json()
    expect(body.detail).toBe('must be an integer speaker id')
  })

  it('PUT: 上流への接続に失敗した場合は504を返す', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockRejectedValueOnce(new Error('network error'))

    const response = await PUT(
      request('http://localhost/api/admin/settings/voices', {
        cookie: 'admin_session=valid-token',
        method: 'PUT',
        body: '{}',
      }),
    )
    expect(response.status).toBe(504)
  })
})

describe('/api/admin/settings/voices/options Route Handler', () => {
  it('Cookieなしは401で上流へ到達しない', async () => {
    const response = await GET_OPTIONS(request('http://localhost/api/admin/settings/voices/options'))
    expect(response.status).toBe(401)
    expect(global.fetch).not.toHaveBeenCalled()
  })

  it('有効Cookieは一覧APIへ転送し、一部エンジンのエラーもそのまま透過する', async () => {
    const optionsBody = JSON.stringify({
      aivispeech: { status: 'ok', options: [{ display_name: 'A - ノーマル', value: 1, speaker_name: 'A', style_name: 'ノーマル' }], error: null },
      voicevox: { status: 'error', options: [], error: '話者一覧を取得できませんでした' },
      fishs2pro: { status: 'ok', options: [{ display_name: 'morigawa', value: 'morigawa', speaker_name: null, style_name: null }], error: null },
    })
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockResolvedValueOnce(upstream(200, optionsBody))

    const response = await GET_OPTIONS(
      request('http://localhost/api/admin/settings/voices/options', { cookie: 'admin_session=valid-token' }),
    )

    expect(response.status).toBe(200)
    const body = await response.json()
    expect(body.voicevox.status).toBe('error')
    expect(body.aivispeech.status).toBe('ok')
    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'http://api:8010/settings/voices/options',
      expect.objectContaining({ headers: expect.objectContaining({ Cookie: 'admin_session=valid-token' }) }),
    )
  })

  it('上流への接続に失敗した場合は504を返す', async () => {
    ;(global.fetch as jest.Mock)
      .mockResolvedValueOnce(upstream(200, '{"admin_user_id":1}'))
      .mockRejectedValueOnce(new Error('network error'))

    const response = await GET_OPTIONS(
      request('http://localhost/api/admin/settings/voices/options', { cookie: 'admin_session=valid-token' }),
    )
    expect(response.status).toBe(504)
  })
})
