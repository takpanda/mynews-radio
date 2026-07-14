import { forwardRef, useState } from 'react'
import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

beforeAll(() => {
  const mockObserve = jest.fn()
  const mockDisconnect = jest.fn()
  global.IntersectionObserver = jest.fn(() => ({
    observe: mockObserve,
    unobserve: jest.fn(),
    disconnect: mockDisconnect,
    root: null,
    rootMargin: '',
    thresholds: [],
    takeRecords: () => [],
  })) as unknown as typeof IntersectionObserver

  HTMLAudioElement.prototype.play = jest.fn().mockResolvedValue(undefined)
  HTMLAudioElement.prototype.pause = jest.fn()
})

afterEach(() => {
  jest.restoreAllMocks()
})

jest.mock('../components/SynthesizeAudioButton', () => ({
  __esModule: true,
  default: () => <div data-testid="mock-synthesize-btn" />,
}))
jest.mock('../components/ArticleLinks', () => ({
  __esModule: true,
  default: function MockArticleLinks() {
    return <div data-testid="mock-article-links" />
  },
}))
jest.mock('../components/ScriptViewer', () => ({
  __esModule: true,
  default: function MockScriptViewer() {
    return <div data-testid="mock-script-viewer" />
  },
}))

import EpisodeAudioPlayer from '../components/EpisodeAudioPlayer'
import EpisodeDetailShell from '../components/EpisodeDetailShell'
import type { DetailEpisode, EpisodeSummary } from '../components/EpisodeDetailShell'
import type { Article } from '../lib/api'
import type { Script } from '../lib/api'

describe('実 EpisodeAudioPlayer メニュー操作', () => {
  const baseProps = {
    audioUrl: '/audio/test.mp3',
    title: 'テスト音声',
    durationSeconds: 120,
  }

  it('「…」ボタンをクリック → ドロップダウンが開く', async () => {
    const user = userEvent.setup()
    render(<EpisodeAudioPlayer {...baseProps} onMisreadingReport={jest.fn()} />)

    const menuButton = screen.getByLabelText('その他')
    expect(menuButton).toBeInTheDocument()
    expect(menuButton).toHaveAttribute('aria-haspopup', 'true')
    expect(menuButton).toHaveAttribute('aria-expanded', 'false')

    await user.click(menuButton)
    expect(screen.getByText('読み間違いを報告')).toBeInTheDocument()
    expect(menuButton).toHaveAttribute('aria-expanded', 'true')
  })

  it('ドロップダウン内の「読み間違いを報告」をクリック → onMisreadingReportが呼ばれる', async () => {
    const user = userEvent.setup()
    const onReport = jest.fn()
    render(<EpisodeAudioPlayer {...baseProps} onMisreadingReport={onReport} />)

    await user.click(screen.getByLabelText('その他'))
    await user.click(screen.getByText('読み間違いを報告'))
    expect(onReport).toHaveBeenCalledTimes(1)
  })

  it('onMisreadingReport未指定 → 「…」ボタンが表示されない', () => {
    render(<EpisodeAudioPlayer {...baseProps} />)
    expect(screen.queryByLabelText('その他')).not.toBeInTheDocument()
  })

  it('menu外クリックでドロップダウンが閉じる', async () => {
    const user = userEvent.setup()
    render(
      <div>
        <EpisodeAudioPlayer {...baseProps} onMisreadingReport={jest.fn()} />
        <div data-testid="outside" />
      </div>,
    )

    await user.click(screen.getByLabelText('その他'))
    expect(screen.getByText('読み間違いを報告')).toBeInTheDocument()

    await user.click(screen.getByTestId('outside'))
    expect(screen.queryByText('読み間違いを報告')).not.toBeInTheDocument()
  })

  it('「…」→「読み間違いを報告」でonMisreadingReport後、メニューが閉じている', async () => {
    const user = userEvent.setup()
    let menuState = false
    const onReport = jest.fn(() => { menuState = false })
    render(
      <div>
        <div data-testid="outside" />
        <EpisodeAudioPlayer {...baseProps} onMisreadingReport={onReport} />
      </div>,
    )

    await user.click(screen.getByLabelText('その他'))
    expect(screen.getByText('読み間違いを報告')).toBeInTheDocument()

    await user.click(screen.getByText('読み間違いを報告'))
    expect(onReport).toHaveBeenCalled()
  })
})

describe('EpisodeDetailShell + 実EpisodeAudioPlayer 導線', () => {
  const episode: DetailEpisode = {
    id: 1,
    title: 'テストエピソード',
    subtitle: '',
    dateLabel: '2026/07/14(火)',
    isCommentary: false,
    sourceUrl: null,
    audioUrl: '/audio/test.mp3',
    durationSeconds: 120,
  }

  const script: Script = {
    title: 'テスト台本',
    lines: [
      { speaker: 'male', text: '該当行', article_id: 5, section: 'main', start_time: 0 },
    ],
  }

  const articles: Article[] = []

  const summary: EpisodeSummary = { intro: '概要', topics: [] }

  it('実プレーヤーメニュー → フォームが開き対象文が表示される', async () => {
    const user = userEvent.setup()
    render(
      <EpisodeDetailShell
        episode={episode}
        script={script}
        articles={articles}
        summary={summary}
      />,
    )

    const menuButton = screen.getByLabelText('その他')
    await user.click(menuButton)
    await user.click(screen.getByText('読み間違いを報告'))

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('再生中に聞こえた箇所')).toBeInTheDocument()
    expect(screen.getByText('該当行')).toBeInTheDocument()
  })
})
