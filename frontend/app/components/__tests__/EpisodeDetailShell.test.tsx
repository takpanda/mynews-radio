import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'
import EpisodeDetailShell, { type DetailEpisode } from '../EpisodeDetailShell'

jest.mock('../EpisodeAudioPlayer', () => ({ __esModule: true, default: () => <div data-testid="audio-player" /> }))
jest.mock('../SynthesizeAudioButton', () => ({ __esModule: true, default: () => <div data-testid="synthesize-button" /> }))
jest.mock('../ScriptViewer', () => ({ __esModule: true, default: () => <div data-testid="script-viewer" /> }))
jest.mock('../ArticleLinks', () => ({ __esModule: true, default: () => <div data-testid="article-links" /> }))
jest.mock('../MisreadingReportForm', () => ({ __esModule: true, default: () => null }))

function episode(overrides: Partial<DetailEpisode> = {}): DetailEpisode {
  return {
    id: 1,
    title: 'テストエピソード',
    subtitle: '',
    date: '2026-09-18',
    dateLabel: '9月18日(金)',
    isCommentary: false,
    sourceUrl: null,
    audioUrl: null,
    durationSeconds: 0,
    ...overrides,
  }
}

describe('EpisodeDetailShell 生成待ち表示', () => {
  it('status=waitingで音声も台本も未準備のとき「生成待ち」バッジと説明を表示する', () => {
    render(
      <EpisodeDetailShell
        episode={episode({ status: 'waiting' })}
        script={null}
        articles={[]}
        episodeItems={[]}
        summary={null}
      />,
    )

    expect(screen.getByText('生成待ち')).toBeInTheDocument()
    expect(screen.getByText('前の生成が終わり次第、自動的に開始します。')).toBeInTheDocument()
    expect(screen.queryByText('音声ファイルを準備中です')).not.toBeInTheDocument()
  })

  it('statusがgeneratingなど非waitingで未準備のときは従来の準備中メッセージを表示する', () => {
    render(
      <EpisodeDetailShell
        episode={episode({ status: 'generating' })}
        script={null}
        articles={[]}
        episodeItems={[]}
        summary={null}
      />,
    )

    expect(screen.getByText('音声ファイルを準備中です')).toBeInTheDocument()
    expect(screen.queryByText('生成待ち')).not.toBeInTheDocument()
  })
})

describe('EpisodeDetailShell サムネイル表示', () => {
  const renderShell = (ep: DetailEpisode) =>
    render(<EpisodeDetailShell episode={ep} script={null} articles={[]} episodeItems={[]} summary={null} />)

  it('thumbnailUrl がある場合はその画像を lazy load で表示する', () => {
    const { container } = renderShell(episode({ thumbnailUrl: '/api/episodes/1/thumbnail' }))
    const img = container.querySelector('[data-testid="episode-thumbnail"] img')
    expect(img?.getAttribute('src')).toBe('/api/episodes/1/thumbnail')
    expect(img?.getAttribute('loading')).toBe('lazy')
  })

  it('thumbnailUrl が null の場合はカテゴリ別のデフォルト画像を表示する', () => {
    const { container } = renderShell(episode({ thumbnailUrl: null }))
    const img = container.querySelector('[data-testid="episode-thumbnail"] img')
    expect(img?.getAttribute('src')).toBe('/images/categories/general.png')
  })

  it('画像の読み込みに失敗した場合はデフォルト画像に切り替える', () => {
    const { container } = renderShell(episode({ thumbnailUrl: '/api/episodes/1/thumbnail', categories: ['テック・IT'] }))
    const img = container.querySelector('[data-testid="episode-thumbnail"] img') as HTMLImageElement
    fireEvent.error(img)
    expect(img.getAttribute('src')).toBe('/images/categories/tech.jpg')
  })
})
