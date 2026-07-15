import '@testing-library/jest-dom'

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import MisreadingReportForm from '../components/MisreadingReportForm'

jest.mock('../lib/misreading-report', () => ({
  submitMisreadingReport: jest.fn(),
}))

const { submitMisreadingReport } = jest.requireMock('../lib/misreading-report')

function getCorrectReadingInput() {
  return screen.getByPlaceholderText('例: じんこうちのう')
}

function getIncorrectReadingInput() {
  return screen.getByPlaceholderText(/と読んでいた/)
}

function getNotesTextarea() {
  return screen.getByPlaceholderText('必要に応じて補足情報を入力')
}

function getSubmitButton() {
  return screen.getByRole('button', { name: '送信する' })
}

describe('MisreadingReportForm (再生経由)', () => {
  const playbackContext = {
    episodeId: 1,
    articleId: 100,
    generationId: 'gen_abc_100',
    playbackPosition: 30.5,
    targetSentence: '再生中の該当箇所のテキスト',
    allowEditTarget: false,
  }

  const onClose = jest.fn()

  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('再生経由時に読み取り専用の対象文を表示する', () => {
    render(
      <MisreadingReportForm playbackContext={playbackContext} onClose={onClose} />
    )
    expect(screen.getByText('再生中に聞こえた箇所')).toBeInTheDocument()
    expect(screen.getByText('再生中の該当箇所のテキスト')).toBeInTheDocument()
  })

  it('正しいpayloadで送信し成功時にcloseを呼ぶ', async () => {
    submitMisreadingReport.mockResolvedValueOnce(undefined)
    const user = userEvent.setup()

    render(
      <MisreadingReportForm playbackContext={playbackContext} onClose={onClose} />
    )

    await user.type(getCorrectReadingInput(), 'せいかくなよみ')
    await user.click(getSubmitButton())

    await waitFor(() => {
      expect(submitMisreadingReport).toHaveBeenCalledWith({
        episode_id: 1,
        target_text: '再生中の該当箇所のテキスト',
        correct_reading: 'せいかくなよみ',
        article_id: 100,
        audio_generation_id: 'gen_abc_100',
        playback_position: 30.5,
        notes: undefined,
      })
    })
    expect(onClose).toHaveBeenCalled()
  })

  it('APIエラー時にエラーメッセージを表示しフォーム内容を保持する', async () => {
    submitMisreadingReport.mockRejectedValueOnce(
      new Error('バリデーションエラー: target_textは必須です')
    )
    const user = userEvent.setup()

    render(
      <MisreadingReportForm playbackContext={playbackContext} onClose={onClose} />
    )

    await user.type(getCorrectReadingInput(), 'てすとよみ')
    await user.click(getSubmitButton())

    await waitFor(() => {
      expect(screen.getByText(/バリデーションエラー/)).toBeInTheDocument()
    })

    expect(getCorrectReadingInput()).toHaveValue('てすとよみ')
    expect(screen.getByText(/時間をおいてもう一度/)).toBeInTheDocument()
  })

  it('APIエラー後に再送信できる（エラーメッセージがクリアされる）', async () => {
    submitMisreadingReport
      .mockRejectedValueOnce(new Error('1回目エラー'))
      .mockResolvedValueOnce(undefined)
    const user = userEvent.setup()

    render(
      <MisreadingReportForm playbackContext={playbackContext} onClose={onClose} />
    )

    await user.type(getCorrectReadingInput(), 'さいそうよみ')
    await user.click(getSubmitButton())

    await waitFor(() => {
      expect(screen.getByText(/1回目エラー/)).toBeInTheDocument()
    })

    await user.click(getSubmitButton())

    await waitFor(() => {
      expect(submitMisreadingReport).toHaveBeenCalledTimes(2)
      expect(onClose).toHaveBeenCalled()
    })
  })

  it('incorrectReadingをnotesに統合して送信する', async () => {
    submitMisreadingReport.mockResolvedValueOnce(undefined)
    const user = userEvent.setup()

    render(
      <MisreadingReportForm playbackContext={playbackContext} onClose={onClose} />
    )

    await user.type(getCorrectReadingInput(), 'てすとよみ')
    await user.type(getIncorrectReadingInput(), 'まちがったよみ')
    await user.type(getNotesTextarea(), '補足情報です')

    await user.click(getSubmitButton())

    await waitFor(() => {
      expect(submitMisreadingReport).toHaveBeenCalledWith({
        episode_id: 1,
        target_text: '再生中の該当箇所のテキスト',
        correct_reading: 'てすとよみ',
        article_id: 100,
        audio_generation_id: 'gen_abc_100',
        playback_position: 30.5,
        notes: '誤読内容: まちがったよみ\n補足情報です',
      })
    })
  })

  it('generationIdがnullでも送信をブロックしない', async () => {
    submitMisreadingReport.mockResolvedValueOnce(undefined)
    const ctxWithNullGen = { ...playbackContext, generationId: null }
    const user = userEvent.setup()

    render(
      <MisreadingReportForm playbackContext={ctxWithNullGen} onClose={onClose} />
    )

    await user.type(getCorrectReadingInput(), 'てすとよみ')
    await user.click(getSubmitButton())

    await waitFor(() => {
      expect(submitMisreadingReport).toHaveBeenCalledWith(
        expect.objectContaining({
          audio_generation_id: null,
        })
      )
    })
  })
})

describe('MisreadingReportForm (手動入力)', () => {
  const onClose = jest.fn()

  beforeEach(() => {
    jest.clearAllMocks()
  })

  it('playbackContextがnullの時は全て手動入力フォームを表示する', () => {
    render(
      <MisreadingReportForm playbackContext={null} onClose={onClose} />
    )
    expect(screen.getByText('読み間違いを報告')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('読み間違いがあった箇所を入力してください')).toBeInTheDocument()
    expect(getCorrectReadingInput()).toBeInTheDocument()
    expect(getIncorrectReadingInput()).toBeInTheDocument()
    expect(getNotesTextarea()).toBeInTheDocument()
  })

  it('必須項目未入力で送信しようとするとエラーを表示する', async () => {
    const user = userEvent.setup()

    render(
      <MisreadingReportForm playbackContext={null} onClose={onClose} />
    )

    await user.click(getSubmitButton())

    expect(submitMisreadingReport).not.toHaveBeenCalled()
    expect(screen.getByText('対象の箇所を入力してください')).toBeInTheDocument()
  })

  it('通信例外（fetch failure）でもcatchしてエラー表示する', async () => {
    submitMisreadingReport.mockRejectedValueOnce(new Error('Failed to fetch'))
    const user = userEvent.setup()

    render(
      <MisreadingReportForm playbackContext={null} onClose={onClose} />
    )

    await user.type(screen.getByPlaceholderText('読み間違いがあった箇所を入力してください'), 'テスト対象文')
    await user.type(getCorrectReadingInput(), 'てすと')
    await user.click(getSubmitButton())

    await waitFor(() => {
      expect(screen.getByText('Failed to fetch')).toBeInTheDocument()
    })
  })
})
