import '@testing-library/jest-dom'

import { fireEvent, render } from '@testing-library/react'
import { TextEncoder } from 'util'
import EpisodeThumbnail from '../EpisodeThumbnail'

// react-dom/server は jsdom に無い TextEncoder を要求するため、import 前に補う
Object.assign(globalThis, { TextEncoder })
const { renderToString } = require('react-dom/server') as typeof import('react-dom/server')

const FALLBACK = '/images/categories/general.png'
const SRC = '/api/episodes/1/thumbnail'

// jsdom は画像を読み込まないため、マウント時点の complete / naturalWidth を差し替えて状態を再現する
function mockImageState(complete: boolean, naturalWidth: number) {
  jest.spyOn(HTMLImageElement.prototype, 'complete', 'get').mockReturnValue(complete)
  jest.spyOn(HTMLImageElement.prototype, 'naturalWidth', 'get').mockReturnValue(naturalWidth)
}

describe('EpisodeThumbnail マウント時の読み込み状態確認', () => {
  afterEach(() => jest.restoreAllMocks())

  it('onError 発火前でも、マウント時に complete=true かつ naturalWidth=0 ならフォールバックへ切り替える', () => {
    mockImageState(true, 0)
    const { container } = render(<EpisodeThumbnail src={SRC} fallbackSrc={FALLBACK} />)
    expect(container.querySelector('img')?.getAttribute('src')).toBe(FALLBACK)
  })

  it('読み込み中（complete=false）は元のURLを維持する', () => {
    mockImageState(false, 0)
    const { container } = render(<EpisodeThumbnail src={SRC} fallbackSrc={FALLBACK} />)
    expect(container.querySelector('img')?.getAttribute('src')).toBe(SRC)
  })

  it('読み込み成功済み（naturalWidth>0）は元のURLを維持する', () => {
    mockImageState(true, 1280)
    const { container } = render(<EpisodeThumbnail src={SRC} fallbackSrc={FALLBACK} />)
    expect(container.querySelector('img')?.getAttribute('src')).toBe(SRC)
  })

  it('src が無い場合はフォールバックを表示する', () => {
    const { container } = render(<EpisodeThumbnail src={null} fallbackSrc={FALLBACK} />)
    expect(container.querySelector('img')?.getAttribute('src')).toBe(FALLBACK)
  })
})

describe('EpisodeThumbnail スケルトン表示と軽量版URL', () => {
  afterEach(() => jest.restoreAllMocks())
  const skeleton = (c: HTMLElement) => c.querySelector('[data-testid="thumbnail-skeleton"]')

  it('読み込み中はスケルトンを表示する（画像自体は opacity-0 で隠さない）', () => {
    mockImageState(false, 0)
    const { container } = render(<EpisodeThumbnail src={SRC} fallbackSrc={FALLBACK} />)
    expect(skeleton(container)).toBeInTheDocument()
    expect(container.querySelector('img')?.className).not.toContain('opacity-0')
  })

  it('onLoad でスケルトンが消え画像が表示される', () => {
    mockImageState(false, 0)
    const { container } = render(<EpisodeThumbnail src={SRC} fallbackSrc={FALLBACK} />)
    fireEvent.load(container.querySelector('img') as HTMLImageElement)
    expect(skeleton(container)).not.toBeInTheDocument()
    expect(container.querySelector('img')?.className).not.toContain('opacity-0')
  })

  it('SSR済みで読み込み完了済み（complete=true, naturalWidth>0）ならスケルトンを出さない', () => {
    mockImageState(true, 1280)
    const { container } = render(<EpisodeThumbnail src={SRC} fallbackSrc={FALLBACK} />)
    expect(skeleton(container)).not.toBeInTheDocument()
  })

  it('読み込み失敗時はフォールバックを表示しスケルトンは残らない', () => {
    mockImageState(false, 0)
    const { container } = render(<EpisodeThumbnail src={SRC} fallbackSrc={FALLBACK} />)
    fireEvent.error(container.querySelector('img') as HTMLImageElement)
    expect(container.querySelector('img')?.getAttribute('src')).toBe(FALLBACK)
    expect(skeleton(container)).not.toBeInTheDocument()
  })

  it('SSR済みで読み込み失敗済みならフォールバックでスケルトンなし', () => {
    mockImageState(true, 0)
    const { container } = render(<EpisodeThumbnail src={SRC} fallbackSrc={FALLBACK} />)
    expect(container.querySelector('img')?.getAttribute('src')).toBe(FALLBACK)
    expect(skeleton(container)).not.toBeInTheDocument()
  })

  it('src が無い回はスケルトンを出さない', () => {
    const { container } = render(<EpisodeThumbnail src={null} fallbackSrc={FALLBACK} />)
    expect(skeleton(container)).not.toBeInTheDocument()
  })

  it('size 指定で size クエリを付与し、既存クエリがあれば & で連結する', () => {
    mockImageState(false, 0)
    const a = render(<EpisodeThumbnail src={SRC} fallbackSrc={FALLBACK} size="card" />)
    expect(a.container.querySelector('img')?.getAttribute('src')).toBe(`${SRC}?size=card`)
    const b = render(<EpisodeThumbnail src={`${SRC}?v=2`} fallbackSrc={FALLBACK} size="detail" />)
    expect(b.container.querySelector('img')?.getAttribute('src')).toBe(`${SRC}?v=2&size=detail`)
  })

  it('width/height を指定し、通常は lazy、priority 時は eager + fetchpriority=high', () => {
    mockImageState(false, 0)
    const { container, rerender } = render(<EpisodeThumbnail src={SRC} fallbackSrc={FALLBACK} size="card" />)
    const img = () => container.querySelector('img') as HTMLImageElement
    expect(img().getAttribute('width')).toBe('640')
    expect(img().getAttribute('height')).toBe('360')
    expect(img().getAttribute('loading')).toBe('lazy')
    expect(img().getAttribute('fetchpriority')).toBeNull()
    rerender(<EpisodeThumbnail src={SRC} fallbackSrc={FALLBACK} size="card" priority />)
    expect(img().getAttribute('loading')).toBe('eager')
    expect(img().getAttribute('fetchpriority')).toBe('high')
  })

  it('スケルトンは prefers-reduced-motion でアニメーションを止めるクラスを持つ', () => {
    mockImageState(false, 0)
    const { container } = render(<EpisodeThumbnail src={SRC} fallbackSrc={FALLBACK} />)
    expect(skeleton(container)?.className).toContain('motion-reduce:animate-none')
  })
})

describe('EpisodeThumbnail SSR 出力（ハイドレーション前の状態）', () => {
  it('SSR時点の画像は opacity-0 で隠れず、JSが動かなくても表示される', () => {
    const html = renderToString(<EpisodeThumbnail src={SRC} fallbackSrc={FALLBACK} size="card" />)
    expect(html).toContain('<img')
    expect(html).not.toContain('opacity-0')
  })
})
