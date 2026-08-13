import { render, screen } from '@testing-library/react'
import HomeShell, { type HeroEpisode } from '../HomeShell'
import type { EpisodeListItem } from '../../lib/api'

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a>,
}))

jest.mock('../../lib/api', () => ({
  fetchEpisodes: jest.fn(),
}))

jest.mock('../EpisodeAudioPlayer', () => ({ __esModule: true, default: () => <div data-testid="audio-player" /> }))
jest.mock('../SynthesizeAudioButton', () => ({ __esModule: true, default: () => null }))
jest.mock('../PushSubscriptionToggle', () => ({ __esModule: true, default: () => <div data-testid="push-toggle" /> }))

function episode(categories?: string[]): EpisodeListItem {
  return {
    id: 1,
    title: 'テストエピソード',
    subtitle: 'テスト概要',
    date: '2026-08-01',
    duration: 180,
    audio_url: '',
    status: 'completed',
    categories,
  }
}

function renderArchive(categories?: string[]) {
  return render(
    <HomeShell
      latest={null}
      chapters={[]}
      initialEpisodes={categories === undefined ? [episode()] : [episode(categories)]}
      initialHasNext={false}
    />,
  )
}

function renderArchiveEpisodes(episodes: EpisodeListItem[]) {
  return render(
    <HomeShell
      latest={null}
      chapters={[]}
      initialEpisodes={episodes}
      initialHasNext={false}
    />,
  )
}

describe('HomeShell archive category badges', () => {
  it.each([
    ['1件', ['テック・IT']],
    ['3件', ['テック・IT', 'AI・先端技術', 'ビジネス']],
  ])('カテゴリ%sを保存順で表示する', (_label, categories) => {
    renderArchive(categories)
    expect(screen.getByLabelText('カテゴリ').textContent).toBe(categories.join(''))
    expect(screen.getByLabelText('カテゴリ').children).toHaveLength(categories.length)
  })

  it('カテゴリ未設定ではバッジ領域を表示しない', () => {
    renderArchive()
    expect(screen.queryByLabelText('カテゴリ')).toBeNull()
  })

  it('カテゴリ0件ではバッジ領域を表示しない', () => {
    renderArchive([])
    expect(screen.queryByLabelText('カテゴリ')).toBeNull()
  })

  it('4件以上のカテゴリを表示しない', () => {
    renderArchive(['政治・行政', '経済・金融', '社会・暮らし', '国際'])
    expect(screen.getByLabelText('カテゴリ').children).toHaveLength(3)
  })
})

describe('HomeShell archive thumbnail', () => {
  it('テックカテゴリではテック用画像を表示する', () => {
    const { container } = renderArchiveEpisodes([{ ...episode(), title: 'テックニュースまとめ' }])
    const img = container.querySelector('.archive-thumb img')
    expect(img?.getAttribute('src')).toBe('/images/categories/tech.jpg')
  })

  it('一般カテゴリでは一般用画像を表示する', () => {
    const { container } = renderArchiveEpisodes([{ ...episode(), title: '一般ニュースまとめ' }])
    const img = container.querySelector('.archive-thumb img')
    expect(img?.getAttribute('src')).toBe('/images/categories/general.png')
  })

  it('解説カテゴリでは解説用画像を表示する', () => {
    const { container } = renderArchiveEpisodes([{ ...episode(), title: 'テック解説回', type: 'commentary' }])
    const img = container.querySelector('.archive-thumb img')
    expect(img?.getAttribute('src')).toBe('/images/categories/commentary.png')
  })

  it.each([
    ['テック', { ...episode(), title: 'テックニュースまとめ' }],
    ['一般', { ...episode(), title: '一般ニュースまとめ' }],
    ['解説', { ...episode(), title: 'テック解説回', type: 'commentary' }],
  ])('%sカテゴリの画像はトリミングせず全体を表示する(object-contain)', (_label, ep) => {
    const { container } = renderArchiveEpisodes([ep])
    const img = container.querySelector('.archive-thumb img')
    expect(img?.className).toContain('object-contain')
    expect(img?.className).not.toContain('object-cover')
  })

  it('テック画像上でもエピソードコード・バッジ・再生アイコン・カード選択が共存する', () => {
    const { container } = renderArchiveEpisodes([{ ...episode(), id: 7, title: 'テックニュースまとめ' }])
    const thumb = container.querySelector('.archive-thumb')
    expect(thumb).not.toBeNull()

    const img = thumb?.querySelector('img')
    expect(img?.getAttribute('src')).toBe('/images/categories/tech.jpg')

    const code = thumb?.querySelector('.archive-thumb-code')
    expect(code?.textContent).toBe('E007')

    const badge = thumb?.querySelector('.archive-episode-badge')
    expect(badge?.textContent).toBe('#7')

    expect(thumb?.querySelector('.archive-play-icon')).not.toBeNull()

    const cardLink = container.querySelector('.archive-card a')
    expect(cardLink?.getAttribute('href')).toBe('/episodes/7')
  })

  it('一般・解説画像上でもエピソードコード・バッジ・再生アイコン・カード選択が共存する', () => {
    const { container } = renderArchiveEpisodes([{ ...episode(), id: 3, title: '一般ニュースまとめ', type: 'commentary' }])
    const thumb = container.querySelector('.archive-thumb')
    expect(thumb).not.toBeNull()

    const img = thumb?.querySelector('img')
    expect(img?.getAttribute('src')).toBe('/images/categories/commentary.png')

    expect(thumb?.querySelector('.archive-thumb-code')?.textContent).toBe('E003')
    expect(thumb?.querySelector('.archive-episode-badge')?.textContent).toBe('#3')
    expect(thumb?.querySelector('.archive-play-icon')).not.toBeNull()

    const cardLink = container.querySelector('.archive-card a')
    expect(cardLink?.getAttribute('href')).toBe('/episodes/3')
  })
})

function heroEpisode(overrides: Partial<HeroEpisode> = {}): HeroEpisode {
  return {
    id: 1,
    title: '最新エピソードのタイトル',
    subtitle: '最新エピソードの副題',
    dateLabel: '8月13日(木)',
    isCommentary: false,
    sourceUrl: null,
    audioUrl: 'https://example.com/audio.mp3',
    durationSeconds: 300,
    keyPoints: [],
    categories: [],
    ...overrides,
  }
}

function renderHero(latest: HeroEpisode | null) {
  return render(
    <HomeShell latest={latest} chapters={[]} initialEpisodes={[]} initialHasNext={false} />,
  )
}

describe('HomeShell ヒーローのトピック表示', () => {
  it('key_pointsがある場合は先頭から最大3件を「今回の3トピック」として表示する', () => {
    renderHero(heroEpisode({ keyPoints: ['トピックA', 'トピックB', 'トピックC', 'トピックD'] }))
    const list = screen.getByLabelText('今回の3トピック')
    expect(list.textContent).toBe('トピックAトピックBトピックC')
    expect(list.children).toHaveLength(3)
  })

  it('key_pointsがなくカテゴリがある場合はカテゴリを最大3件表示する', () => {
    renderHero(heroEpisode({ keyPoints: [], categories: ['テック・IT', 'AI・先端技術', 'ビジネス', '国際'] }))
    const list = screen.getByLabelText('今回の3トピック')
    expect(list.textContent).toBe('テック・ITAI・先端技術ビジネス')
    expect(list.children).toHaveLength(3)
  })

  it('key_pointsもカテゴリもない場合はトピック領域を表示しない', () => {
    renderHero(heroEpisode({ keyPoints: [], categories: [] }))
    expect(screen.queryByLabelText('今回の3トピック')).toBeNull()
  })

  it('通知操作は再生プレーヤーより後に配置される', () => {
    const { container } = renderHero(heroEpisode())
    const player = container.querySelector('[data-testid="audio-player"]')
    const toggle = container.querySelector('[data-testid="push-toggle"]')
    expect(player).not.toBeNull()
    expect(toggle).not.toBeNull()
    const position = player!.compareDocumentPosition(toggle!)
    expect(position & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})
