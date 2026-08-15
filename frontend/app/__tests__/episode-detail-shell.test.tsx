import '@testing-library/jest-dom'
import React from 'react'

import { render, screen } from '@testing-library/react'
import EpisodeDetailShell from '../components/EpisodeDetailShell'
import type { DetailEpisode } from '../components/EpisodeDetailShell'

jest.mock('../components/EpisodeAudioPlayer', () => {
  const MockEpisodeAudioPlayer = React.forwardRef(() => <div data-testid="mock-audio-player" />)
  MockEpisodeAudioPlayer.displayName = 'MockEpisodeAudioPlayer'
  return {
    __esModule: true,
    default: MockEpisodeAudioPlayer,
  }
})

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

describe('EpisodeDetailShell llmModel 表示', () => {
  it('llmModel がある場合にモデル名ラベルを表示する', () => {
    render(
      <EpisodeDetailShell
        episode={createEpisode({ llmModel: 'qwen3:8b' })}
        script={null}
        articles={[]}
        episodeItems={[]}
        summary={null}
      />
    )
    const label = screen.getByText('qwen3:8b')
    expect(label).toBeInTheDocument()
    expect(label).toHaveAttribute('aria-label', 'LLMモデル: qwen3:8b')
  })

  it.each([null, undefined, ''])('llmModel が %p の場合はラベルを表示しない', (llmModel) => {
    render(
      <EpisodeDetailShell
        episode={createEpisode({ llmModel })}
        script={null}
        articles={[]}
        episodeItems={[]}
        summary={null}
      />
    )
    expect(screen.queryByLabelText(/LLMモデル:/)).not.toBeInTheDocument()
  })

  it('長いモデル名でもラベルに収まり、タイトルと同じ行の表示を維持する', () => {
    const model = 'very-long-model-name-without-spaces-' + 'x'.repeat(80)
    render(
      <EpisodeDetailShell
        episode={createEpisode({ llmModel: model })}
        script={null}
        articles={[]}
        episodeItems={[]}
        summary={null}
      />
    )
    const label = screen.getByText(model)
    expect(label).toHaveClass('max-w-full', 'break-all')
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
    const anchorEl = screen.getByRole('link', { name: '台本' }).closest('div')!
    const keyPointsPos = Array.from(overview.children).indexOf(keyPointsEl)
    const anchorPos = Array.from(overview.children).indexOf(anchorEl)
    expect(keyPointsPos).toBeLessThan(anchorPos)
  })
})

describe('EpisodeDetailShell 元記事見出し', () => {
  it('通常回では見出しが「元記事」になる', () => {
    render(
      <EpisodeDetailShell
        episode={createEpisode({ isCommentary: false, sourceUrl: null })}
        script={null}
        articles={[{ id: 1, title: 'A', source: null, url: 'https://example.com/a' }]}
        episodeItems={[]}
        summary={null}
      />
    )
    expect(screen.getByRole('heading', { name: '元記事' })).toBeInTheDocument()
    expect(screen.queryByText('解説の元記事')).not.toBeInTheDocument()
  })

  it('単一URLの解説回では見出しが「解説の元記事」になる', () => {
    render(
      <EpisodeDetailShell
        episode={createEpisode({ isCommentary: true, sourceUrl: 'https://example.com/source' })}
        script={null}
        articles={[]}
        episodeItems={[]}
        summary={null}
      />
    )
    expect(screen.getByRole('heading', { name: '解説の元記事' })).toBeInTheDocument()
  })

  it('解説回でも記事一覧が別途ある場合は見出しが「元記事」のままになる', () => {
    render(
      <EpisodeDetailShell
        episode={createEpisode({ isCommentary: true, sourceUrl: 'https://example.com/source' })}
        script={null}
        articles={[{ id: 1, title: 'A', source: null, url: 'https://example.com/a' }]}
        episodeItems={[]}
        summary={null}
      />
    )
    expect(screen.getByRole('heading', { name: '元記事' })).toBeInTheDocument()
  })
})

describe('EpisodeDetailShell sourceUrl 全文表示防止', () => {
  it('単一URLの解説回でもsourceUrl全文がカード上部に表示されない', () => {
    const sourceUrl = 'https://www.commentary-source.example.com/2026/08/13/deep-dive-article'
    render(
      <EpisodeDetailShell
        episode={createEpisode({ isCommentary: true, sourceUrl })}
        script={null}
        articles={[]}
        episodeItems={[]}
        summary={null}
      />
    )
    expect(screen.queryByText(sourceUrl)).not.toBeInTheDocument()
    expect(screen.queryByText((content) => content.includes(sourceUrl))).not.toBeInTheDocument()
  })

  it('通常回でもsourceUrlが設定されていれば全文表示されない', () => {
    const sourceUrl = 'https://example.com/normal-episode-source'
    render(
      <EpisodeDetailShell
        episode={createEpisode({ isCommentary: false, sourceUrl })}
        script={null}
        articles={[{ id: 1, title: 'A', source: null, url: 'https://example.com/a' }]}
        episodeItems={[]}
        summary={null}
      />
    )
    expect(screen.queryByText(sourceUrl)).not.toBeInTheDocument()
  })
})

describe('EpisodeDetailShell 生成詳細ログへの導線', () => {
  it('isAuthenticatedがtrueの場合、対象エピソードの管理ログページへのリンクを表示する', () => {
    render(
      <EpisodeDetailShell
        episode={createEpisode({ id: 42 })}
        script={null}
        articles={[]}
        episodeItems={[]}
        summary={null}
        isAuthenticated
      />
    )
    const link = screen.getByRole('link', { name: '生成詳細ログ' })
    expect(link).toHaveAttribute('href', '/admin/episodes/42/logs')
  })

  it('isAuthenticatedがfalseの場合、リンクを表示しない', () => {
    render(
      <EpisodeDetailShell
        episode={createEpisode()}
        script={null}
        articles={[]}
        episodeItems={[]}
        summary={null}
        isAuthenticated={false}
      />
    )
    expect(screen.queryByRole('link', { name: '生成詳細ログ' })).not.toBeInTheDocument()
  })

  it('isAuthenticatedを省略した場合(デフォルトfalse)、リンクを表示しない', () => {
    render(
      <EpisodeDetailShell
        episode={createEpisode()}
        script={null}
        articles={[]}
        episodeItems={[]}
        summary={null}
      />
    )
    expect(screen.queryByRole('link', { name: '生成詳細ログ' })).not.toBeInTheDocument()
  })
})
