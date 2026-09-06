/** @jest-environment jsdom */

import { fetchCategoryFemaleMcClient, saveCategoryFemaleMcClient } from '../lib/admin-category-female-mc'

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  }
}

const backendBody = {
  categories: ['テック・IT'],
  category_female_voices: { 'テック・IT': 'morigawa' },
  default_voice: 'morigawa',
  voices: [
    {
      display_name: 'morigawa',
      value: 'morigawa',
      sample: {
        // バックエンドが返す生パス（ブラウザから直接は到達できない）
        url: '/settings/voices/categories/samples/morigawa',
        text: 'サンプル文',
        media_type: 'audio/wav',
        available: true,
      },
    },
  ],
}

beforeEach(() => {
  global.fetch = jest.fn()
})

describe('admin-category-female-mc client helpers', () => {
  it('fetchCategoryFemaleMcClient: sample.url を中継API経由のパスへ書き換える', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(jsonResponse(200, backendBody))
    const result = await fetchCategoryFemaleMcClient()
    expect(result.voices[0].sample.url).toBe('/api/admin/settings/voices/categories/samples/morigawa')
  })

  it('saveCategoryFemaleMcClient: 保存応答の sample.url も中継API経由のパスへ書き換える', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(jsonResponse(200, backendBody))
    const result = await saveCategoryFemaleMcClient({ 'テック・IT': 'morigawa' })
    expect(result.voices[0].sample.url).toBe('/api/admin/settings/voices/categories/samples/morigawa')
  })
})
