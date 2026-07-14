import '@testing-library/jest-dom'

/**
 * 読み間違い報告UI 単体テスト
 *
 * 実行方法: npm test
 *
 * 注意:
 * - このテストはフォームUIとContext生成ロジックの単体テストです
 * - Backendの `POST /api/misreading-reports` および `GET /episodes/{id}` に
 *   `generation_id` が追加された後の結合テストは別途必要です
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import MisreadingReportForm from '../components/MisreadingReportForm'

// ============================================================
// Context生成ロジックのテスト（純粋関数による実経路検証）
// ============================================================

import {
  findCurrentLine,
  buildPlaybackReportContext,
  buildArticleReportContext,
} from '../lib/misreading-report-context'
import type { Script } from '../lib/api'

// ============================================================
// findCurrentLine のテスト
// ============================================================

describe('findCurrentLine', () => {
  const lines: Script['lines'] = [
    { speaker: 'male', text: '最初の行', article_id: null, section: 'intro', start_time: 0 },
    { speaker: 'female', text: '二番目の行', article_id: null, section: 'main', start_time: 10 },
    { speaker: 'male', text: '三番目の行', article_id: null, section: 'main', start_time: 20 },
  ]

  it('linesが空ならnullを返す', () => {
    expect(findCurrentLine([], 0)).toBeNull()
  })

  it('linesがnull相当ならnullを返す', () => {
    expect(findCurrentLine(null as unknown as Script['lines'], 0)).toBeNull()
  })

  it('currentTime 0でstart_time 0の行を返す（ケースC: 再生時刻0）', () => {
    const result = findCurrentLine(lines, 0)
    expect(result).not.toBeNull()
    expect(result!.text).toBe('最初の行')
  })

  it('currentTimeがstart_time範囲内の最新行を返す', () => {
    expect(findCurrentLine(lines, 15)!.text).toBe('二番目の行')
  })

  it('start_timeがundefinedの行をスキップする（ケースB: start_time未設定）', () => {
    const withUndefined: Script['lines'] = [
      { speaker: 'male', text: '時間なし行', article_id: null, section: 'main' },
    ]
    expect(findCurrentLine(withUndefined, 0)).toBeNull()
  })
})

// ============================================================
// buildPlaybackReportContext のテスト（実経路検証）
// ============================================================

describe('buildPlaybackReportContext', () => {
  const episode = { id: 1, audioUrl: '/audio/test.mp3' }

  it('script === null なら targetSentence空＋allowEditTarget（ケースA: 台本なし）', () => {
    const ctx = buildPlaybackReportContext(episode, null, 30)
    expect(ctx.episodeId).toBe(1)
    expect(ctx.targetSentence).toBe('')
    expect(ctx.allowEditTarget).toBe(true)
    expect(ctx.needsGenerationId).toBe(true)
    expect(ctx.generationId).toBeNull()
  })

  it('linesが空でも同様に allowEditTarget になる', () => {
    const script = { title: '', lines: [] }
    const ctx = buildPlaybackReportContext(episode, script, 0)
    expect(ctx.targetSentence).toBe('')
    expect(ctx.allowEditTarget).toBe(true)
  })

  it('start_time未設定行のみ → findCurrentLineがnull → allowEditTarget（ケースB）', () => {
    const script: Script = {
      title: '',
      lines: [
        { speaker: 'male', text: '時間なし', article_id: null, section: 'main' },
        { speaker: 'female', text: '時間なし二', article_id: null, section: 'main' },
      ],
    }
    const ctx = buildPlaybackReportContext(episode, script, 0)
    expect(ctx.targetSentence).toBe('')
    expect(ctx.allowEditTarget).toBe(true)
  })

  it('currentTime === 0 で該当行なし → allowEditTarget（ケースC: 再生時刻0）', () => {
    const script: Script = {
      title: '',
      lines: [
        { speaker: 'male', text: '10秒以降の行', article_id: null, section: 'main', start_time: 10 },
      ],
    }
    const ctx = buildPlaybackReportContext(episode, script, 0)
    expect(ctx.targetSentence).toBe('')
    expect(ctx.allowEditTarget).toBe(true)
  })

  it('該当行あり → targetSentence＋allowEditTarget=false', () => {
    const script: Script = {
      title: '',
      lines: [
        { speaker: 'male', text: '該当行', article_id: 5, section: 'main', start_time: 10 },
      ],
    }
    const ctx = buildPlaybackReportContext(episode, script, 15)
    expect(ctx.targetSentence).toBe('該当行')
    expect(ctx.allowEditTarget).toBe(false)
    expect(ctx.articleId).toBe(5)
    expect(ctx.playbackPosition).toBe(15)
  })

  it('articleIdはcurrentLineから引き継がれる', () => {
    const script: Script = {
      title: '',
      lines: [
        { speaker: 'male', text: '記事行', article_id: 99, section: 'main', start_time: 5 },
      ],
    }
    const ctx = buildPlaybackReportContext(episode, script, 10)
    expect(ctx.articleId).toBe(99)
  })

  it('playbackPositionはcurrentTime > 0 の場合のみ設定される', () => {
    const script: Script = {
      title: '',
      lines: [
        { speaker: 'male', text: '行', article_id: null, section: 'main', start_time: 0 },
      ],
    }
    const ctxAt0 = buildPlaybackReportContext(episode, script, 0)
    expect(ctxAt0.playbackPosition).toBeNull()

    const ctxAt5 = buildPlaybackReportContext(episode, script, 5)
    expect(ctxAt5.playbackPosition).toBe(5)
  })

  it('generationIdはnull（Backend実ID提供後に差し替え）', () => {
    const script: Script = {
      title: '',
      lines: [],
    }
    const ctx = buildPlaybackReportContext(episode, script, 0)
    expect(ctx.generationId).toBeNull()
  })
})

// ============================================================
// buildArticleReportContext のテスト
// ============================================================

describe('buildArticleReportContext', () => {
  it('episodeIdとarticleIdをセット、allowEditTarget=true、needsGenerationId=false', () => {
    const ctx = buildArticleReportContext(10, 20)
    expect(ctx.episodeId).toBe(10)
    expect(ctx.articleId).toBe(20)
    expect(ctx.targetSentence).toBe('')
    expect(ctx.allowEditTarget).toBe(true)
    expect(ctx.needsGenerationId).toBe(false)
    expect(ctx.generationId).toBeNull()
    expect(ctx.playbackPosition).toBeNull()
  })
})

// ============================================================
// MisreadingReportForm コンポーネントテスト
// ============================================================

function mockFetch(data = {}) {
  return jest.fn().mockResolvedValue({
    ok: true,
    json: async () => data,
    text: async () => JSON.stringify(data),
  })
}

function getFormElements() {
  return {
    targetTextarea: screen.queryByPlaceholderText('読み間違いがあった箇所を入力してください'),
    correctInput: screen.getByPlaceholderText('例: じんこうえいせい'),
    submitButton: screen.getByRole('button', { name: /送信する/i }),
    cancelButton: screen.getByRole('button', { name: /キャンセル/i }),
  }
}

describe('MisreadingReportForm', () => {
  beforeEach(() => {
    global.fetch = mockFetch() as jest.Mock
  })

  afterEach(() => {
    jest.restoreAllMocks()
  })

  // ---- 実IDブロック ----

  describe('再生画面経由（generationId欠如でブロック）', () => {
    it('generationIdがnullでneedsGenerationId=true → 送信ボタンdisabled', () => {
      render(
        <MisreadingReportForm
          playbackContext={{
            episodeId: 1,
            articleId: null,
            generationId: null,
            playbackPosition: 30,
            targetSentence: '自動取得行',
            allowEditTarget: false,
            needsGenerationId: true,
          }}
          onClose={jest.fn()}
        />,
      )
      const { submitButton } = getFormElements()
      expect(submitButton).toBeDisabled()
    })

    it('disabled状態でsubmit発火 → エラーメッセージ（title属性）', async () => {
      render(
        <MisreadingReportForm
          playbackContext={{
            episodeId: 1,
            articleId: null,
            generationId: null,
            playbackPosition: 30,
            targetSentence: '自動取得行',
            allowEditTarget: false,
            needsGenerationId: true,
          }}
          onClose={jest.fn()}
        />,
      )
      const submitButton = screen.getByRole('button', { name: /送信する/i })
      expect(submitButton).toHaveAttribute('title', '音声生成IDの連携が未確定のため送信できません')
    })
  })

  // ---- 記事詳細経由 ----

  describe('記事詳細経由（generationId不要）', () => {
    it('generationId=nullでも送信ボタンが有効', () => {
      render(
        <MisreadingReportForm
          playbackContext={{
            episodeId: 1,
            articleId: 10,
            generationId: null,
            playbackPosition: null,
            targetSentence: '',
            allowEditTarget: true,
            needsGenerationId: false,
          }}
          onClose={jest.fn()}
        />,
      )
      const { submitButton } = getFormElements()
      expect(submitButton).not.toBeDisabled()
    })

    it('正しい読み未入力で送信 → バリデーションエラー', async () => {
      const user = userEvent.setup()
      render(
        <MisreadingReportForm
          playbackContext={{
            episodeId: 1,
            articleId: 10,
            generationId: null,
            playbackPosition: null,
            targetSentence: '',
            allowEditTarget: true,
            needsGenerationId: false,
          }}
          onClose={jest.fn()}
        />,
      )
      await user.click(screen.getByRole('button', { name: /送信する/i }))
      expect(screen.getByText('正しい読みを入力してください')).toBeInTheDocument()
    })

    it('対象文＋正しい読みを入力して送信 → fetchが呼ばれる', async () => {
      const user = userEvent.setup()
      render(
        <MisreadingReportForm
          playbackContext={{
            episodeId: 1,
            articleId: 10,
            generationId: null,
            playbackPosition: null,
            targetSentence: '',
            allowEditTarget: true,
            needsGenerationId: false,
          }}
          onClose={jest.fn()}
        />,
      )
      await user.type(
        screen.getByPlaceholderText('読み間違いがあった箇所を入力してください'),
        '対象の箇所',
      )
      await user.type(screen.getByPlaceholderText('例: じんこうえいせい'), 'じんこうえいせい')
      await user.click(screen.getByRole('button', { name: /送信する/i }))

      await waitFor(() => {
        expect(global.fetch).toHaveBeenCalledWith(
          '/api/misreading-reports',
          expect.objectContaining({ method: 'POST' }),
        )
      })
    })
  })

  // ---- 再生画面（対象文自動取得あり） ----

  describe('再生画面経由（対象文自動取得）', () => {
    it('readonly表示でtargetSentenceが表示される', () => {
      render(
        <MisreadingReportForm
          playbackContext={{
            episodeId: 1,
            articleId: null,
            generationId: null,
            playbackPosition: 30,
            targetSentence: '自動取得された行',
            allowEditTarget: false,
            needsGenerationId: true,
          }}
          onClose={jest.fn()}
        />,
      )
      expect(screen.getByText('自動取得された行')).toBeInTheDocument()
    })
  })
})
