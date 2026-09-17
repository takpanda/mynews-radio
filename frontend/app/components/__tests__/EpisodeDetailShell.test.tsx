import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
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
