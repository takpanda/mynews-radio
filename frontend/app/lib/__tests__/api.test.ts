import { describeGenerationError, formatGeneratedAt, generateEpisode } from '../api'

describe('formatGeneratedAt', () => {
  it('UTC 13:00 → JST 22:00 に変換される', () => {
    const result = formatGeneratedAt('2026-07-23T13:00:00Z')
    expect(result).toMatch(/2026\/07\/23 22:00/)
  })

  it('UTC 0:00 → JST 9:00 に変換される（日付跨ぎなし）', () => {
    const result = formatGeneratedAt('2026-01-15T00:00:00Z')
    expect(result).toMatch(/2026\/01\/15 0?9:00/)
  })

  it('UTC 23:00 → JST 翌日 8:00 に変換される（日付跨ぎ）', () => {
    const result = formatGeneratedAt('2026-06-01T23:00:00Z')
    expect(result).toMatch(/2026\/06\/02 0?8:00/)
  })

  it('出力書式が YYYY/MM/DD HH:mm の形式である', () => {
    const result = formatGeneratedAt('2026-12-31T15:30:00Z')
    expect(result).toMatch(/^\d{4}\/\d{2}\/\d{2} \d{2}:\d{2}$/)
  })

  it('分の値が正しく保持される', () => {
    const result = formatGeneratedAt('2026-03-15T07:45:00Z')
    expect(result).toMatch(/:45$/)
  })
})

describe('generateEpisode settings snapshot', () => {
  it('設定スナップショットを生成payloadへ含める', async () => {
    const previousFetch = global.fetch
    const fetchMock = jest.fn().mockResolvedValue(
      { ok: true, json: async () => ({ episode_id: 12 }) },
    )
    global.fetch = fetchMock as typeof fetch
    await generateEpisode('2026-07-25', 6, 'hatena_bookmark', 'aivispeech', false, undefined, undefined, undefined, {
      priority_themes: ['technology'],
      excluded_themes: ['sports'],
      duration_preset: 'short',
    })

    const request = JSON.parse((fetchMock.mock.calls[0][1]?.body as string))
    expect(request.settings_snapshot).toEqual({
      priority_themes: ['technology'],
      excluded_themes: ['sports'],
      duration_preset: 'short',
    })
    global.fetch = previousFetch
  })

  it('指定したIdempotency-Keyをリクエストへ転送する', async () => {
    const previousFetch = global.fetch
    const fetchMock = jest.fn().mockResolvedValue(
      { ok: true, json: async () => ({ episode_id: 12 }) },
    )
    global.fetch = fetchMock as typeof fetch
    await generateEpisode('2026-07-25', 6, 'hatena_bookmark', 'aivispeech', false, undefined, undefined, undefined, undefined, 'same-operation-key')

    expect(fetchMock.mock.calls[0][1]?.headers).toEqual(expect.objectContaining({ 'Idempotency-Key': 'same-operation-key' }))
    global.fetch = previousFetch
  })
})

describe('生成制御エラー', () => {
  it('429はRetry-Afterの待機時間を案内する', () => {
    expect(describeGenerationError(429, '', '60')).toBe('利用制限に達しました。約1分後に再試行できます。')
  })

  it.each([
    [401, 'ログインが必要です。再度ログインしてください。'],
    [403, 'この操作を実行する権限がありません。'],
    [409, '同じ操作が競合しています。入力内容を確認して再試行してください。'],
  ])('%sを専用メッセージにする', (status, message) => {
    expect(describeGenerationError(status, '')).toBe(message)
  })
})
