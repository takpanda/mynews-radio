/** @jest-environment jsdom */

import { fetchPrograms, createProgram, replaceProgram, fetchMcs, createMc, replaceMc } from '../lib/admin-programs'

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  }
}

const program = {
  id: 'p1',
  name: 'テスト番組',
  kind: 'radio',
  definition: {
    id: 'p1',
    name: 'テスト番組',
    kind: 'radio',
    cast: [],
    segments: [],
    options: { style: null, mc_gender: null, narrative_arc: false, review_mode: 'on_failure' },
  },
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

beforeEach(() => {
  global.fetch = jest.fn()
})

describe('admin-programs client helpers', () => {
  it('fetchPrograms: include_inactiveをクエリへ反映して/api経由で取得する', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(jsonResponse(200, [program]))
    const result = await fetchPrograms(true)
    expect(result).toEqual([program])
    expect(global.fetch).toHaveBeenCalledWith('/api/admin/programs?include_inactive=true', expect.anything())
  })

  it('createProgram: 409応答は本文をそのままエラーメッセージにする', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: false,
      status: 409,
      text: () => Promise.resolve('Program slug already exists'),
    })
    await expect(
      createProgram({
        id: 'p1',
        name: 'n',
        kind: 'radio',
        cast: [],
        segments: [],
        options: { style: null, mc_gender: null, narrative_arc: false, review_mode: 'on_failure' },
        is_active: true,
      }),
    ).rejects.toThrow('Program slug already exists')
  })

  it('replaceProgram: 422応答のdetail文字列をエラーメッセージにする', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      jsonResponse(422, { detail: 'Unknown or inactive MC: radio_male' }),
    )
    await expect(
      replaceProgram('p1', {
        id: 'p1',
        name: 'n',
        kind: 'radio',
        cast: [],
        segments: [],
        options: { style: null, mc_gender: null, narrative_arc: false, review_mode: 'on_failure' },
        is_active: true,
      }),
    ).rejects.toThrow('Unknown or inactive MC: radio_male')
  })

  it('replaceProgram: FastAPIの標準422形式(detailが配列)もメッセージへ変換する', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      jsonResponse(422, { detail: [{ loc: ['body', 'kind'], msg: 'Input should be radio or commentary', type: 'literal_error' }] }),
    )
    await expect(
      replaceProgram('p1', {
        id: 'p1',
        name: 'n',
        kind: 'radio',
        cast: [],
        segments: [],
        options: { style: null, mc_gender: null, narrative_arc: false, review_mode: 'on_failure' },
        is_active: true,
      }),
    ).rejects.toThrow('Input should be radio or commentary')
  })

  it('fetchMcs: include_inactiveなしはクエリを付けない', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(jsonResponse(200, []))
    await fetchMcs(false)
    expect(global.fetch).toHaveBeenCalledWith('/api/admin/mcs', expect.anything())
  })

  it('createMc: 401応答は認証エラーメッセージにする', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce({ ok: false, status: 401, text: () => Promise.resolve('') })
    await expect(
      createMc({ id: 'mc1', name: 'n', role: 'r', voice_fishs2pro: null, voice_aivispeech: null, voice_voicevox: null, is_active: true }),
    ).rejects.toThrow('認証されていません。再度ログインしてください。')
  })

  it('replaceMc: 成功時はJSONをそのまま返す', async () => {
    const mc = { id: 'mc1', name: 'n', role: 'r', voice_fishs2pro: null, voice_aivispeech: null, voice_voicevox: null, is_active: false, created_at: '', updated_at: '' }
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(jsonResponse(200, mc))
    const result = await replaceMc('mc1', mc)
    expect(result).toEqual(mc)
    expect(global.fetch).toHaveBeenCalledWith('/api/admin/mcs/mc1', expect.objectContaining({ method: 'PUT' }))
  })
})
