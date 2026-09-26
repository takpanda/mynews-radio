/** @jest-environment jsdom */

import { createDryRunClient, fetchDryRunClient, DryRunApiError, DryRunQueueFullError } from '../lib/admin-dry-runs'

function jsonResponse(status: number, body: unknown, headers?: Record<string, string>) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
    headers: { get: (name: string) => headers?.[name] ?? null },
  }
}

beforeEach(() => {
  global.fetch = jest.fn()
})

describe('admin-dry-runs client helpers', () => {
  it('createDryRunClient: Idempotency-Keyヘッダーを付けてBFFへ送信する', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(jsonResponse(202, { id: 1, status: 'queued' }))
    const result = await createDryRunClient('p1', {
      draft_program_definition: null,
      draft_prompt_version_id: null,
      input_episode_id: null,
    })
    expect(result).toEqual({ id: 1, status: 'queued' })
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/admin/programs/p1/dry-run',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Idempotency-Key': expect.any(String) }),
      }),
    )
  })

  it('createDryRunClient: 429はRetry-Afterを保持したDryRunQueueFullErrorを投げる', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(jsonResponse(429, { detail: 'Generation queue is full' }, { 'Retry-After': '60' }))
    await expect(createDryRunClient('p1', {})).rejects.toBeInstanceOf(DryRunQueueFullError)
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(jsonResponse(429, { detail: 'Generation queue is full' }, { 'Retry-After': '60' }))
    try {
      await createDryRunClient('p1', {})
      fail('should have thrown')
    } catch (err) {
      expect(err).toBeInstanceOf(DryRunQueueFullError)
      expect((err as DryRunQueueFullError).retryAfterSeconds).toBe(60)
    }
  })

  it('createDryRunClient: 422応答のdetailをそのままメッセージにする', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(
      jsonResponse(422, { detail: '指定エピソードの summaries.json が読み取れません' }),
    )
    await expect(createDryRunClient('p1', { input_episode_id: 99999 })).rejects.toThrow(
      '指定エピソードの summaries.json が読み取れません',
    )
  })

  it('createDryRunClient: 404は番組未対応/未検出のメッセージへ変換する', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: false,
      status: 404,
      text: () => Promise.resolve(''),
      headers: { get: () => null },
    })
    await expect(createDryRunClient('p1', {})).rejects.toThrow('対象が見つかりませんでした。')
  })

  it('fetchDryRunClient: 完了したジョブの詳細を取得する', async () => {
    const detail = {
      id: 5,
      program_id: 'p1',
      program_definition: {},
      draft_program_definition: null,
      prompt_version_id: null,
      input_episode_id: null,
      script_json: { current: { lines: [{ speaker: 'host', text: 'hello', section: 'news' }] } },
      validation_json: { current: [] },
      status: 'completed',
      error: null,
      created_at: '',
      updated_at: '',
    }
    ;(global.fetch as jest.Mock).mockResolvedValueOnce(jsonResponse(200, detail))
    const result = await fetchDryRunClient(5)
    expect(result).toEqual(detail)
    expect(global.fetch).toHaveBeenCalledWith('/api/admin/dry-runs/5', expect.anything())
  })

  it('fetchDryRunClient: 404はDryRunApiErrorになる', async () => {
    ;(global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: false,
      status: 404,
      text: () => Promise.resolve(''),
      headers: { get: () => null },
    })
    await expect(fetchDryRunClient(999)).rejects.toBeInstanceOf(DryRunApiError)
  })
})
