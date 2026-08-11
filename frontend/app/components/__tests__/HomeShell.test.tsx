import { render, screen } from '@testing-library/react'
import HomeShell from '../HomeShell'
import type { EpisodeListItem } from '../../lib/api'

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a>,
}))

jest.mock('../../lib/api', () => ({
  fetchEpisodes: jest.fn(),
}))

jest.mock('../EpisodeAudioPlayer', () => ({ __esModule: true, default: () => null }))
jest.mock('../SynthesizeAudioButton', () => ({ __esModule: true, default: () => null }))
jest.mock('../PushSubscriptionToggle', () => ({ __esModule: true, default: () => null }))

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

  it('一般カテゴリでは従来のグラデーションを表示する', () => {
    const { container } = renderArchiveEpisodes([{ ...episode(), title: '一般ニュースまとめ' }])
    expect(container.querySelector('.archive-thumb img')).toBeNull()
    expect(container.querySelector('.archive-thumb-coral')).not.toBeNull()
  })

  it('解説カテゴリでは従来のグラデーションを表示する', () => {
    const { container } = renderArchiveEpisodes([{ ...episode(), title: 'テック解説回', type: 'commentary' }])
    expect(container.querySelector('.archive-thumb img')).toBeNull()
  })
})
