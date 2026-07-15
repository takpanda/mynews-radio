import { submitMisreadingReport } from '../lib/misreading-report'

describe('submitMisreadingReport (API契約準拠)', () => {
  let originalFetch: typeof global.fetch

  beforeEach(() => {
    originalFetch = global.fetch
  })

  afterEach(() => {
    global.fetch = originalFetch
  })

  it('200系レスポンスで成功する', async () => {
    global.fetch = jest.fn().mockResolvedValueOnce({ ok: true })

    await expect(
      submitMisreadingReport({
        episode_id: 1,
        target_text: 'テスト',
        correct_reading: 'てすと',
      })
    ).resolves.toBeUndefined()

    expect(global.fetch).toHaveBeenCalledWith('/api/reports/misreading', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        episode_id: 1,
        target_text: 'テスト',
        correct_reading: 'てすと',
      }),
    })
  })

  it('422バリデーションエラーでdetailメッセージをthrowする', async () => {
    global.fetch = jest.fn().mockResolvedValueOnce({
      ok: false,
      status: 422,
      text: () =>
        Promise.resolve(
          JSON.stringify({ detail: [{ msg: 'target_text: field required' }] })
        ),
    })

    await expect(
      submitMisreadingReport({
        episode_id: 1,
        target_text: 'テスト',
        correct_reading: 'てすと',
      })
    ).rejects.toThrow('target_text: field required')
  })

  it('409重複エラーでdetailメッセージをthrowする', async () => {
    global.fetch = jest.fn().mockResolvedValueOnce({
      ok: false,
      status: 409,
      text: () =>
        Promise.resolve(
          JSON.stringify({
            detail:
              'Duplicate report: same target_text and correct_reading within 24 hours',
          })
        ),
    })

    await expect(
      submitMisreadingReport({
        episode_id: 1,
        target_text: '重複',
        correct_reading: 'ちょうふく',
      })
    ).rejects.toThrow('Duplicate report')
  })

  it('通信エラー（ネットワーク障害）でエラーをthrowする', async () => {
    global.fetch = jest.fn().mockRejectedValueOnce(new TypeError('Failed to fetch'))

    await expect(
      submitMisreadingReport({
        episode_id: 1,
        target_text: 'テスト',
        correct_reading: 'てすと',
      })
    ).rejects.toThrow('Failed to fetch')
  })

  it('JSONではないエラーボディでもfallbackメッセージをthrowする', async () => {
    global.fetch = jest.fn().mockResolvedValueOnce({
      ok: false,
      status: 500,
      text: () => Promise.resolve('Internal Server Error'),
    })

    await expect(
      submitMisreadingReport({
        episode_id: 1,
        target_text: 'テスト',
        correct_reading: 'てすと',
      })
    ).rejects.toThrow('Internal Server Error')
  })

  it('必須フィールドと全任意フィールドを含めたpayloadを送信する', async () => {
    global.fetch = jest.fn().mockResolvedValueOnce({ ok: true })

    await submitMisreadingReport({
      episode_id: 1,
      target_text: '対象テキスト',
      correct_reading: 'たいしょうてきすと',
      article_id: 100,
      audio_generation_id: 'gen_abc_100',
      playback_position: 30.5,
      notes: '補足情報',
      app_version: '1.0.0',
    })

    expect(global.fetch).toHaveBeenCalledWith(
      '/api/reports/misreading',
      expect.objectContaining({
        body: JSON.stringify({
          episode_id: 1,
          target_text: '対象テキスト',
          correct_reading: 'たいしょうてきすと',
          article_id: 100,
          audio_generation_id: 'gen_abc_100',
          playback_position: 30.5,
          notes: '補足情報',
          app_version: '1.0.0',
        }),
      })
    )
  })
})
