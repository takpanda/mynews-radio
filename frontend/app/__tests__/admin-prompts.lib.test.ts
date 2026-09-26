/** @jest-environment jsdom */

import { fetchPrompts, fetchPromptVersions, createPromptTemplate, createPromptVersion } from '../lib/admin-prompts'

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  }
}

const template = {
  id: 1,
  template_key: 'category',
  program_id: null,
  required_variables: ['categories', 'source'],
  allowed_variables: ['categories', 'source'],
  versions: [{ id: 10, version: 1, status: 'active', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' }],
}

beforeEach(() => {
  global.fetch = jest.fn()
})

describe('admin-prompts client helpers', () => {
  it('fetchPrompts: /api経由で一覧を取得する', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(jsonResponse(200, [template]))
    const result = await fetchPrompts()
    expect(result).toEqual([template])
    expect(global.fetch).toHaveBeenCalledWith('/api/admin/prompts', expect.anything())
  })

  it('fetchPrompts: program_idを指定するとクエリへ反映する', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(jsonResponse(200, []))
    await fetchPrompts('radio-test')
    expect(global.fetch).toHaveBeenCalledWith('/api/admin/prompts?program_id=radio-test', expect.anything())
  })

  it('fetchPromptVersions: 版一覧を取得する', async () => {
    const response = { prompt_id: 1, template_key: 'category', program_id: null, versions: [] }
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(jsonResponse(200, response))
    const result = await fetchPromptVersions(1)
    expect(result).toEqual(response)
    expect(global.fetch).toHaveBeenCalledWith('/api/admin/prompts/1/versions', expect.anything())
  })

  it('createPromptTemplate: 409応答は本文をそのままエラーメッセージにする', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: false,
      status: 409,
      text: () => Promise.resolve('Prompt template already exists'),
    })
    await expect(createPromptTemplate({ template_key: 'category', program_id: 'radio-test' })).rejects.toThrow(
      'Prompt template already exists',
    )
  })

  it('createPromptVersion: 成功時はJSONをそのまま返す', async () => {
    const created = { id: 11, template_id: 1, version: 2, content: 'test', status: 'draft' }
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(jsonResponse(201, created))
    const result = await createPromptVersion(1, 'test')
    expect(result).toEqual(created)
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/admin/prompts/1/versions',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ content: 'test' }) }),
    )
  })

  it('createPromptVersion: 422応答のdetail文字列をエラーメッセージにする', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      jsonResponse(422, { detail: 'Missing required variables: source' }),
    )
    await expect(createPromptVersion(1, 'test')).rejects.toThrow('Missing required variables: source')
  })

  it('createPromptVersion: FastAPIの標準422形式(detailが配列)もメッセージへ変換する', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      jsonResponse(422, { detail: [{ loc: ['body', 'content'], msg: 'field required', type: 'missing' }] }),
    )
    await expect(createPromptVersion(1, '')).rejects.toThrow('field required')
  })
})
