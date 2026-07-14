/**
 * 読み間違い報告UI 結合テスト
 *
 * 注意: このテストはBackendの `POST /api/misreading-reports` エンドポイントおよび
 * `GET /episodes/{id}` の `generation_id` フィールドが実装された後に有効化してください。
 *
 * 実行方法（Jest + @testing-library/react インストール後）:
 *   npx jest frontend/app/__tests__/misreading-report-integration.test.ts
 *
 * テスト対象の3ケース:
 *   A. 台本なし（script === null）
 *   B. start_time 未設定の行のみ
 *   C. 再生時刻0（currentTime === 0）
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import MisreadingReportForm, {
  type PlaybackContext,
} from '../components/MisreadingReportForm'

// ============================================================
// ヘルパー
// ============================================================

function mockFetch(data: unknown) {
  return jest.fn().mockResolvedValue({
    ok: true,
    json: async () => data,
    text: async () => JSON.stringify(data),
  })
}

function renderForm(ctx: PlaybackContext | null) {
  const onClose = jest.fn()
  const utils = render(
    <MisreadingReportForm playbackContext={ctx} onClose={onClose} />,
  )
  return { ...utils, onClose }
}

function typeCorrectReading(value: string) {
  const input = screen.getByPlaceholderText('例: じんこうえいせい')
  userEvent.clear(input)
  userEvent.type(input, value)
}

async function clickSubmit() {
  const btn = screen.getByRole('button', { name: /送信する/i })
  await userEvent.click(btn)
}

// ============================================================
// ケースA: 台本なし（script === null）
// ============================================================

describe('ケースA: 台本なし', () => {
  const ctx: PlaybackContext = {
    episodeId: 1,
    articleId: null,
    generationId: 'gen_abc123',
    playbackPosition: null,
    targetSentence: '',
    allowEditTarget: true,
    needsGenerationId: true,
  }

  beforeEach(() => {
    global.fetch = mockFetch({}) as jest.Mock
  })

  it('対象文の入力欄が表示される', () => {
    renderForm(ctx)
    expect(
      screen.getByPlaceholderText('読み間違いがあった箇所を入力してください'),
    ).toBeInTheDocument()
  })

  it('対象文 + 正しい読みを入力して送信するとpayloadに含まれる', async () => {
    renderForm(ctx)
    userEvent.type(
      screen.getByPlaceholderText('読み間違いがあった箇所を入力してください'),
      '人工衛星の打ち上げ',
    )
    typeCorrectReading('じんこうえいせい')
    await clickSubmit()

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/misreading-reports',
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('"target_sentence":"人工衛星の打ち上げ"'),
        }),
      )
    })
  })

  it('audio_generation_id に実IDがセットされている', async () => {
    renderForm(ctx)
    userEvent.type(
      screen.getByPlaceholderText('読み間違いがあった箇所を入力してください'),
      'テスト',
    )
    typeCorrectReading('てすと')
    await clickSubmit()

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/misreading-reports',
        expect.objectContaining({
          body: expect.stringContaining('"audio_generation_id":"gen_abc123"'),
        }),
      )
    })
  })
})

// ============================================================
// ケースB: start_time 未設定の行のみ
// ============================================================

describe('ケースB: start_time未設定行のみ', () => {
  /**
   * findCurrentLine は start_time が undefined の行をスキップする。
   * その結果 currentLine === null となり、allowEditTarget: true でフォームが開く。
   */
  const ctx: PlaybackContext = {
    episodeId: 2,
    articleId: null,
    generationId: 'gen_def456',
    playbackPosition: 120,
    targetSentence: '',
    allowEditTarget: true,
    needsGenerationId: true,
  }

  beforeEach(() => {
    global.fetch = mockFetch({}) as jest.Mock
  })

  it('対象文が空でフォームが開き、入力欄が表示される', () => {
    renderForm(ctx)
    expect(
      screen.getByPlaceholderText('読み間違いがあった箇所を入力してください'),
    ).toBeInTheDocument()
    expect(screen.getByDisplayValue('')).toBeInTheDocument()
  })

  it('手動入力した対象文が payload の target_sentence に反映される', async () => {
    renderForm(ctx)
    userEvent.type(
      screen.getByPlaceholderText('読み間違いがあった箇所を入力してください'),
      'これはstart_timeなしの行',
    )
    typeCorrectReading('てすと')
    await clickSubmit()

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/misreading-reports',
        expect.objectContaining({
          body: expect.stringContaining('"target_sentence":"これはstart_timeなしの行"'),
        }),
      )
    })
  })
})

// ============================================================
// ケースC: 再生時刻0（currentTime === 0）
// ============================================================

describe('ケースC: 再生時刻0', () => {
  /**
   * currentTime === 0 の場合、start_time > 0 の行はマッチせず、
   * currentLine === null → allowEditTarget: true でフォームが開く。
   */
  const ctx: PlaybackContext = {
    episodeId: 3,
    articleId: null,
    generationId: 'gen_ghi789',
    playbackPosition: null,
    targetSentence: '',
    allowEditTarget: true,
    needsGenerationId: true,
  }

  beforeEach(() => {
    global.fetch = mockFetch({}) as jest.Mock
  })

  it('再生時刻0でもフォームが開き、手動入力できる', async () => {
    renderForm(ctx)
    userEvent.type(
      screen.getByPlaceholderText('読み間違いがあった箇所を入力してください'),
      '開始直後の読み間違い',
    )
    typeCorrectReading('しせい')
    await clickSubmit()

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        '/api/misreading-reports',
        expect.objectContaining({
          body: expect.stringContaining('"target_sentence":"開始直後の読み間違い"'),
        }),
      )
    })
  })
})

// ============================================================
// 補足: 再生画面送信ブロック（実ID未提供時）
// ============================================================

describe('再生画面送信ブロック（実ID未提供時）', () => {
  const ctx: PlaybackContext = {
    episodeId: 4,
    articleId: null,
    generationId: null,
    playbackPosition: 30,
    targetSentence: '既存の台本行',
    allowEditTarget: false,
    needsGenerationId: true,
  }

  it('generationId が null の場合、送信ボタンが disabled である', () => {
    renderForm(ctx)
    expect(screen.getByRole('button', { name: /送信する/i })).toBeDisabled()
  })

  it('generationId が null で直接 submit を試みるとエラーメッセージが表示される', async () => {
    renderForm(ctx)
    const btn = screen.getByRole('button', { name: /送信する/i })
    // disabled でも form submit を直接発火（セキュリティガードの確認）
    const form = btn.closest('form')!
    jest.spyOn(form, 'requestSubmit').mockImplementation(() => {})
    form.dispatchEvent(new Event('submit', { cancelable: true }))

    await waitFor(() => {
      expect(
        screen.getByText(/音声生成IDの連携が未確定/),
      ).toBeInTheDocument()
    })
  })
})

// ============================================================
// 補足: 記事詳細経由（needsGenerationId: false）
// ============================================================

describe('記事詳細経由（generationId不要）', () => {
  const ctx: PlaybackContext = {
    episodeId: 5,
    articleId: 10,
    generationId: null,
    playbackPosition: null,
    targetSentence: '',
    allowEditTarget: true,
    needsGenerationId: false,
  }

  beforeEach(() => {
    global.fetch = mockFetch({}) as jest.Mock
  })

  it('generationId が null でも送信可能', async () => {
    renderForm(ctx)
    userEvent.type(
      screen.getByPlaceholderText('読み間違いがあった箇所を入力してください'),
      '記事の読み間違い',
    )
    typeCorrectReading('きじ')
    await clickSubmit()

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalled()
    })
  })
})
