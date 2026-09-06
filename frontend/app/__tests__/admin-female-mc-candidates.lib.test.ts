/** @jest-environment jsdom */

import {
  fetchFemaleMcCandidatesClient,
  createFemaleMcCandidateClient,
  updateFemaleMcCandidateClient,
} from '../lib/admin-female-mc-candidates'

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  }
}

const backendCandidate = {
  id: 1,
  voice_name: 'morigawa',
  display_name: 'もりかわ',
  sample_text: 'サンプル文',
  is_active: true,
  sample: {
    // バックエンドが返す生パス（ブラウザから直接は到達できない）
    url: '/settings/voices/categories/samples/morigawa',
    text: 'サンプル文',
    media_type: 'audio/wav',
    available: true,
  },
}

beforeEach(() => {
  global.fetch = jest.fn()
})

describe('admin-female-mc-candidates client helpers', () => {
  it('fetchFemaleMcCandidatesClient: sample.url を中継API経由のパスへ書き換える', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(jsonResponse(200, [backendCandidate]))
    const result = await fetchFemaleMcCandidatesClient()
    expect(result[0].sample.url).toBe('/api/admin/settings/voices/categories/samples/morigawa')
  })

  it('createFemaleMcCandidateClient: 追加応答の sample.url も書き換える', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(jsonResponse(201, backendCandidate))
    const result = await createFemaleMcCandidateClient({ voice_name: 'morigawa', display_name: 'もりかわ' })
    expect(result.sample.url).toBe('/api/admin/settings/voices/categories/samples/morigawa')
  })

  it('createFemaleMcCandidateClient: 409応答は重複エラーメッセージに変換する', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(jsonResponse(409, { detail: 'voice_name already exists' }))
    await expect(
      createFemaleMcCandidateClient({ voice_name: 'morigawa', display_name: 'もりかわ' }),
    ).rejects.toThrow('voice_name already exists')
  })

  it('updateFemaleMcCandidateClient: 更新応答の sample.url も書き換える', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(jsonResponse(200, { ...backendCandidate, is_active: false }))
    const result = await updateFemaleMcCandidateClient('morigawa', { is_active: false })
    expect(result.is_active).toBe(false)
    expect(result.sample.url).toBe('/api/admin/settings/voices/categories/samples/morigawa')
  })

  it('updateFemaleMcCandidateClient: detailの無い503応答は既定メッセージに変換する', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(jsonResponse(503, {}))
    await expect(updateFemaleMcCandidateClient('morigawa', { is_active: false })).rejects.toThrow(
      '保存できませんでした。しばらく後でもう一度お試しください。',
    )
  })
})
