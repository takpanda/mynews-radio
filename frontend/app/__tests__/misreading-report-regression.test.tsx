import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

jest.mock('../components/EpisodeAudioPlayer', () => ({
  __esModule: true,
  default: function MockAudioPlayer({
    onMisreadingReport,
  }: {
    onMisreadingReport?: () => void
  }) {
    return (
      <div data-testid="mock-audio-player">
        <button
          type="button"
          aria-label="その他"
          onClick={() => onMisreadingReport?.()}
        >
          ⋯
        </button>
      </div>
    )
  },
}))

jest.mock('../components/SynthesizeAudioButton', () => ({
  __esModule: true,
  default: () => <div data-testid="mock-synthesize-btn" />,
}))

import EpisodeDetailShell from '../components/EpisodeDetailShell'
import ArticleLinks from '../components/ArticleLinks'
import type { DetailEpisode, EpisodeSummary } from '../components/EpisodeDetailShell'
import type { Article } from '../lib/api'
import type { Script } from '../lib/api'

// ============================================================
// EpisodeDetailShell 回帰テスト（再生導線）
// ============================================================

describe('EpisodeDetailShell 再生導線（回帰テスト）', () => {
  const baseEpisode: DetailEpisode = {
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
      { speaker: 'male', text: '一行目', article_id: 5, section: 'intro', start_time: 0 },
      { speaker: 'female', text: '二行目', article_id: null, section: 'main', start_time: 10 },
    ],
  }

  const articles: Article[] = [
    { id: 1, title: '記事A', url: 'https://example.com/a', source: 'sourceA' },
  ]

  const summary: EpisodeSummary = { intro: '概要です', topics: ['トピック1'] }

  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
      text: async () => '{}',
    }) as jest.Mock
  })

  afterEach(() => {
    jest.restoreAllMocks()
  })

  const clickPlayerMenu = async (user: ReturnType<typeof userEvent.setup>) => {
    const playerButtons = screen.getAllByLabelText('その他')
    await user.click(playerButtons[0])
  }

  it('音声プレーヤーの「読み間違いを報告」からフォームが開く', async () => {
    const user = userEvent.setup()
    render(
      <EpisodeDetailShell
        episode={baseEpisode}
        script={script}
        articles={articles}
        summary={summary}
      />,
    )
    await clickPlayerMenu(user)
    await user.click(screen.getByText('読み間違いを報告'))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getAllByText(/一行目/).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByRole('button', { name: /送信する/i })).toBeDisabled()
  })

  it('audioUrlがなければモックプレーヤーは表示されない', () => {
    render(
      <EpisodeDetailShell
        episode={{ ...baseEpisode, audioUrl: null }}
        script={script}
        articles={articles}
        summary={summary}
      />,
    )
    expect(screen.queryByTestId('mock-audio-player')).not.toBeInTheDocument()
    expect(screen.queryByTestId('mock-synthesize-btn')).toBeInTheDocument()
  })

  it('script === null でも再生導線は開き allowEditTarget になる', async () => {
    const user = userEvent.setup()
    render(
      <EpisodeDetailShell
        episode={baseEpisode}
        script={null}
        articles={articles}
        summary={summary}
      />,
    )
    await clickPlayerMenu(user)
    await user.click(screen.getByText('読み間違いを報告'))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(
      screen.getByPlaceholderText('読み間違いがあった箇所を入力してください'),
    ).toBeInTheDocument()
  })

  it('linesが空でも再生導線はallowEditTargetになる', async () => {
    const user = userEvent.setup()
    render(
      <EpisodeDetailShell
        episode={baseEpisode}
        script={{ title: '', lines: [] }}
        articles={articles}
        summary={summary}
      />,
    )
    await clickPlayerMenu(user)
    await user.click(screen.getByText('読み間違いを報告'))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(
      screen.getByPlaceholderText('読み間違いがあった箇所を入力してください'),
    ).toBeInTheDocument()
  })
})

// ============================================================
// ArticleLinks 回帰テスト（タッチ/キーボード導線）
// ============================================================

describe('ArticleLinks 導線（回帰テスト）', () => {
  const articles: Article[] = [
    { id: 10, title: 'テスト記事', url: 'https://example.com/test', source: 'テストソース' },
  ]

  it('onReportArticleがあるとき「…」メニューが表示される', () => {
    render(<ArticleLinks articles={articles} onReportArticle={jest.fn()} />)
    expect(screen.getByLabelText('その他')).toBeInTheDocument()
  })

  it('メニューを開いて「読み間違いを報告」 → onReportArticleが呼ばれる', async () => {
    const user = userEvent.setup()
    const onReport = jest.fn()
    render(<ArticleLinks articles={articles} onReportArticle={onReport} />)
    await user.click(screen.getByLabelText('その他'))
    await user.click(screen.getByText('読み間違いを報告'))
    expect(onReport).toHaveBeenCalledWith(articles[0])
  })

  it('Tabキーで「その他」にフォーカスできる（キーボード導線）', async () => {
    const user = userEvent.setup()
    render(<ArticleLinks articles={articles} onReportArticle={jest.fn()} />)
    await user.tab()
    await user.tab()
    expect(screen.getByLabelText('その他')).toHaveFocus()
  })

  it('onReportArticleがないとき「…」メニューは表示されない', () => {
    render(<ArticleLinks articles={articles} />)
    expect(screen.queryByLabelText('その他')).not.toBeInTheDocument()
  })

  it('記事がないときArticleLinksは何も表示しない', () => {
    const { container } = render(<ArticleLinks articles={[]} />)
    expect(container.innerHTML).toBe('')
  })
})
