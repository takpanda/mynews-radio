import '@testing-library/jest-dom'
import React from 'react'

import { render, screen } from '@testing-library/react'
import EpisodeDetailShell from '../components/EpisodeDetailShell'
import type { DetailEpisode } from '../components/EpisodeDetailShell'

jest.mock('../components/EpisodeAudioPlayer', () => ({
  __esModule: true,
  default: React.forwardRef(() => <div data-testid="mock-audio-player" />),
}))

jest.mock('../components/ScriptViewer', () => ({
  __esModule: true,
  default: () => <div data-testid="mock-script-viewer" />,
}))

jest.mock('../components/ArticleLinks', () => ({
  __esModule: true,
  default: () => <div data-testid="mock-article-links" />,
}))

jest.mock('../components/SynthesizeAudioButton', () => ({
  __esModule: true,
  default: () => <div data-testid="mock-synthesize-button" />,
}))

jest.mock('../components/MisreadingReportForm', () => ({
  __esModule: true,
  default: () => <div data-testid="mock-report-form" />,
}))

function createEpisode(overrides: Partial<DetailEpisode> = {}): DetailEpisode {
  return {
    id: 1,
    title: 'テストエピソード',
    subtitle: 'サブタイトル',
    date: '2026-07-23',
    dateLabel: '7月23日（木）',
    isCommentary: false,
    sourceUrl: null,
    audioUrl: '/audio/test.mp3',
    durationSeconds: 600,
    ...overrides,
  }
}

describe('EpisodeDetailShell generatedAtLabel 表示', () => {
  it('generatedAtLabel がある場合「生成」ラベルが表示される', () => {
    render(
      <EpisodeDetailShell
        episode={createEpisode({ generatedAtLabel: '2026/07/23 22:00' })}
        script={null}
        articles={[]}
        episodeItems={[]}
        summary={null}
      />
    )
    expect(screen.getByText((c) => c.includes('生成 2026/07/23 22:00'))).toBeInTheDocument()
  })

  it('generatedAtLabel がない場合「生成」ラベルは表示されない', () => {
    render(
      <EpisodeDetailShell
        episode={createEpisode()}
        script={null}
        articles={[]}
        episodeItems={[]}
        summary={null}
      />
    )
    expect(screen.queryByText((c) => c.includes('生成'))).not.toBeInTheDocument()
  })

  it('generatedAtLabel がない場合でも日付ラベルは表示される', () => {
    render(
      <EpisodeDetailShell
        episode={createEpisode()}
        script={null}
        articles={[]}
        episodeItems={[]}
        summary={null}
      />
    )
    expect(screen.getByText(/エピソード ・ 7月23日/)).toBeInTheDocument()
  })
})
