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

describe('EpisodeDetailShell この回で分かること 表示', () => {
  it('keyPoints が1件の場合に表示される', () => {
    render(
      <EpisodeDetailShell
        episode={createEpisode({ keyPoints: ['AIの最新動向が分かります'] })}
        script={null}
        articles={[]}
        episodeItems={[]}
        summary={null}
      />
    )
    expect(screen.getByText('この回で分かること')).toBeInTheDocument()
    expect(screen.getByText('AIの最新動向が分かります')).toBeInTheDocument()
  })

  it('keyPoints が3件の場合に全て表示される', () => {
    const points = ['ポイントA', 'ポイントB', 'ポイントC']
    render(
      <EpisodeDetailShell
        episode={createEpisode({ keyPoints: points })}
        script={null}
        articles={[]}
        episodeItems={[]}
        summary={null}
      />
    )
    expect(screen.getByText('この回で分かること')).toBeInTheDocument()
    points.forEach((p) => expect(screen.getByText(p)).toBeInTheDocument())
  })

  it('keyPoints が空配列の場合に非表示', () => {
    render(
      <EpisodeDetailShell
        episode={createEpisode({ keyPoints: [] })}
        script={null}
        articles={[]}
        episodeItems={[]}
        summary={null}
      />
    )
    expect(screen.queryByText('この回で分かること')).not.toBeInTheDocument()
  })

  it('keyPoints が undefined の場合に非表示', () => {
    render(
      <EpisodeDetailShell
        episode={createEpisode({ keyPoints: undefined })}
        script={null}
        articles={[]}
        episodeItems={[]}
        summary={null}
      />
    )
    expect(screen.queryByText('この回で分かること')).not.toBeInTheDocument()
  })

  it('アンカーリンク（台本）より前に「この回で分かること」が表示される', () => {
    const script = { title: 't', lines: [{ speaker: 'male' as const, text: 'hello', article_id: null, section: 'intro' }] }
    render(
      <EpisodeDetailShell
        episode={createEpisode({ keyPoints: ['ポイント'] })}
        script={script}
        articles={[]}
        episodeItems={[]}
        summary={null}
      />
    )
    const overview = screen.getByText('この回で分かること').closest('section')!
    const keyPointsEl = screen.getByText('ポイント').closest('div')!
    const anchorEl = screen.getByText('台本').closest('div')!
    const keyPointsPos = Array.from(overview.children).indexOf(keyPointsEl.parentElement!)
    const anchorPos = Array.from(overview.children).indexOf(anchorEl.parentElement!)
    expect(keyPointsPos).toBeLessThan(anchorPos)
  })
})
